"""Function-length budget for the ``web`` addon's JavaScript.

Nothing currently bounds how long a JS function may be. The tree's longest is
738 lines (``core/utils/dnd/draggable_hook_builder.js``'s ``makeDraggableHook``),
and the shape recurs: service ``start()`` factories at 402 and 401, a
609-line ``useListKeyboardNavigation``, a 240-line ``ListRenderer.setup()``.
This gate makes that number a contract that may only fall.

**Length, not method count.** An earlier draft of the budget proposed a
per-class method ceiling. Measured, that metric is inverted: the widest classes
are wide and *thin* — ``RelationalRecord`` has 80 members whose median is two
lines, and ``StaticList``'s 72 have no external subclasser at all — while
``FormController``, with 29 members, carries 59 downstream subclass/patch
sites. Method count would have flagged the harmless class and cleared the
load-bearing one. Function length also catches what a class-level metric cannot
see at all: the longest functions in the tree belong to no class.

**ESLint measures it, not a bespoke parser.** Function extents are a parsing
problem, and hand-rolled brace matching gets them wrong: a scan that pairs a
closing brace at the declaration's indentation misses object-literal methods
(closed by ``},``) and then runs on to a later brace, which reported
``py_interpreter.js``'s two-line ``lower()`` as 241 lines. Three attempts at
this number by regex gave 127, 114 and 117; the answer is none of them.
ESLint already parses every one of these files with a real parser, so the rule
is injected into a normal run rather than reimplemented here.

The rule is **not** added to ``eslint.config.mjs`` on purpose. There it would
land in the repo-wide aggregate baseline (~24k), where a new 300-line function
is +1 in five figures — the same signal-in-noise problem ``js_layer_check``'s
docstring documents for layering. It would also cost the pristine
"702 linted, 0 errors, 0 warnings" result that makes the normal run a useful
signal. A scoped count of its own keeps both.

The count feeds the shared ratchet, so the bookkeeping is not reimplemented::

    python tooling/architecture/js_function_length.py --count \\
        | xargs python tooling/ratchet/ratchet.py jsfunclen --count

Generated sources are excluded: ``emoji_data.js`` is a 36k-line data table
whose eight entries would otherwise dominate every report and drown the
hand-written code the budget is about.

Usage::

    python tooling/architecture/js_function_length.py           # report
    python tooling/architecture/js_function_length.py --count   # the number only
    python tooling/architecture/js_function_length.py --json
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_function_length")
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"

# Addon-parameterised, defaulting to `web` so the existing baseline keeps its
# meaning. `mail` is the second: 392 files and 54 functions over budget, against
# web's 148, and until now nothing bounded either of them there.
GOVERNED_ADDONS = ("web", "mail")
DEFAULT_ADDON = "web"


def addon_src(addon: str = DEFAULT_ADDON):
    """The `static/src` a run measures. Returns the module-level `WEB_SRC` for
    the default addon so the suite's monkeypatching of that name still bites."""
    return (
        WEB_SRC
        if addon == DEFAULT_ADDON
        else ROOT / "addons" / addon / "static" / "src"
    )


ESLINT = ROOT / "node_modules" / ".bin" / "eslint"

# Functions longer than this are counted. Not a hard failure threshold — the
# ratchet compares the *count*, so the budget falls as code is split rather
# than blocking any single function outright.
MAX_LINES = 80

# Generated sources. Their length says nothing about anyone's design.
GENERATED = frozenset({"emoji_data.js"})

RULE = "max-lines-per-function"
RULE_CONFIG = {
    RULE: [
        "warn",
        # Count every line the function spans. Skipping blanks or comments
        # would let a long function hide behind its own documentation, and the
        # budget is about how much a reader must hold at once.
        {
            "max": MAX_LINES,
            "skipBlankLines": False,
            "skipComments": False,
            "IIFEs": True,
        },
    ]
}

_LINES_RE = re.compile(r"has too many lines \((\d+)\)")


@dataclass(frozen=True)
class LongFunction:
    file: str
    line: int
    lines: int
    what: str

    def __str__(self) -> str:
        return f"  {self.lines:5d}  {self.file}:{self.line}  {self.what}"


def _describe(message: str) -> str:
    """``Method 'setup' has too many lines (91)...`` -> ``Method 'setup'``."""
    return message.split(" has too many lines", maxsplit=1)[0]


# ``export const SearchQueryMixin = (Base) =>\n    class extends Base {`` — a
# mixin factory. Syntactically an arrow function, so ESLint reports its whole
# class body as one function; semantically it is a class declaration.
_MIXIN_FACTORY_RE = re.compile(r"=>\s*class\s+extends\b")


def _relabel_mixin_factories(found: list[LongFunction], root: Path) -> None:
    """Relabel arrow functions that are really mixin class bodies, in place.

    **The count is deliberately unchanged.** Three `search/*_mixin.js` bodies
    (338/337/257 lines) are reported as "Arrow function", which reads as a god
    function and is what misled a 2026-08-03 audit into proposing they be split.
    They are class bodies, and this gate's own docstring records that class
    *width* is the wrong metric — so the useful fix is the label, not the
    budget.

    Dropping them from the count was considered and rejected: it would move a
    number the shared ratchet pins in ``exact`` mode, redefine the metric
    mid-history, and — against this gate's stated design — make a bespoke parser
    decide what ESLint counts. A wrong label is cosmetic; a wrong count is not.
    """
    cache: dict[str, list[str]] = {}
    for i, item in enumerate(found):
        if not item.what.startswith("Arrow function"):
            continue
        lines = cache.get(item.file)
        if lines is None:
            path = root / item.file
            if not path.is_file():
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            cache[item.file] = lines
        # The arrow and the `class extends` may sit on the same line or the next.
        window = " ".join(lines[item.line - 1 : item.line + 1])
        if _MIXIN_FACTORY_RE.search(window):
            found[i] = replace(item, what="Mixin class body")


def measure(src: Path = WEB_SRC, eslint: Path = ESLINT) -> list[LongFunction]:
    """Every function over ``MAX_LINES``, longest first.

    Raises ``RuntimeError`` rather than returning an empty list when ESLint
    cannot run or matches nothing: a budget gate that reports "0 over the
    limit" because it linted nothing is worse than no gate.
    """
    if not eslint.is_file():
        raise RuntimeError(f"eslint not found at {eslint} (run `npm ci`)")
    proc = subprocess.run(
        # --no-config-lookup: measure with *only* the injected rule, so the
        # number cannot move because an unrelated rule was added to
        # eslint.config.mjs, and so the same command works on a synthetic tree
        # outside the repo (which a flat config would refuse to lint). Verified
        # to give an identical count with and without it. It also surfaces
        # "unused eslint-disable directive" notices, which the ruleId filter
        # below drops.
        [
            str(eslint),
            ".",
            "--no-config-lookup",
            "--rule",
            json.dumps(RULE_CONFIG),
            "-f",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
        # Run *inside* the tree being measured, targeting ".". Flat-config
        # ESLint refuses paths outside its working directory, which is what a
        # synthetic tree under /tmp is; reported paths are absolute either way,
        # so this changes nothing about the result.
        cwd=src,
    )
    if not proc.stdout.strip():
        raise RuntimeError(
            f"eslint produced no output (exit {proc.returncode}): {proc.stderr[:400]}"
        )
    results = json.loads(proc.stdout)
    if not results:
        raise RuntimeError(f"eslint linted no files under {src}")

    found: list[LongFunction] = []
    for entry in results:
        path = Path(entry["filePath"])
        if path.name in GENERATED:
            continue
        for msg in entry["messages"]:
            if msg.get("ruleId") != RULE:
                continue
            match = _LINES_RE.search(msg["message"])
            if match is None:  # pragma: no cover - rule message format changed
                raise RuntimeError(f"unparsable {RULE} message: {msg['message']!r}")
            found.append(
                LongFunction(
                    file=path.relative_to(ROOT).as_posix()
                    if path.is_relative_to(ROOT)
                    else path.as_posix(),
                    line=msg["line"],
                    lines=int(match.group(1)),
                    what=_describe(msg["message"]),
                )
            )
    found.sort(key=lambda f: (-f.lines, f.file))
    _relabel_mixin_factories(found, ROOT)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--top", type=int, default=15, help="offenders to list (0 = all)"
    )
    parser.add_argument(
        "--addon",
        default=DEFAULT_ADDON,
        choices=GOVERNED_ADDONS,
        help="which addon's static/src to measure (default: web)",
    )
    args = parser.parse_args(argv)

    try:
        found = measure(src=addon_src(args.addon))
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in found], indent=2))
        return 0

    print(f"JS function-length budget (> {MAX_LINES} lines, {args.addon}/static/src)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    over = {t: sum(1 for f in found if f.lines > t) for t in (150, 250, 400)}
    print(f"\n{len(found)} function(s) over {MAX_LINES} lines")
    print(f"  over 150: {over[150]}   over 250: {over[250]}   over 400: {over[400]}")
    print("\nRatchet this number:")
    suffix = "" if args.addon == DEFAULT_ADDON else f" --addon {args.addon}"
    name = "jsfunclen" if args.addon == DEFAULT_ADDON else f"jsfunclen_{args.addon}"
    print(f"  python tooling/architecture/js_function_length.py{suffix} --count \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {name} --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())
