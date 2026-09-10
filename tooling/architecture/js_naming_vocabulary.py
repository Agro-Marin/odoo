"""§2.4's method vocabulary over an addon's JavaScript, which no gate reads.

§2.4.19 is called *What a Python-only reading misses* and lists three things a
sweep of `def` statements walks past. It does not list the largest one, because
at the time the vocabulary was a Python rule: **the other half of the codebase**.
`naming_vocabulary.py` and `naming_core_vocabulary.py` both parse Python, so a
method that builds a payload, validates an argument or fetches a record is
governed when it is written in `models/` and governed by nothing when the same
operation is written in `static/src/`. §4.2 says components are PascalCase and
methods camelCase and stops there, so nothing in the workspace has an opinion
about the VERB a JS method opens with.

This is the instrument for that population and deliberately **not** a gate. It
carries no baseline file, `test_gate_adr_coverage` has no record to bind, and
nothing fails on its count. The reason is in the numbers rather than in
caution: pointed at `addons/mail` before the tables below existed it read 74,
and reading those one at a time turned up **eight** names worth renaming against
**sixty-four** rows where the verb is right and the Python table is the wrong
instrument. Fifty-eight of the sixty-four are what `IDIOM`, `PLATFORM_METHODS`
and `CONTRACT_TREES` exempt outright, which is why the reported figure at that
commit was 16 and not 74; the eight renames cleared ten of those rows -- a call
site matches the definition shape -- and took the report to 6. A gate banked on
that ratio would be a floor of sixty-four exemptions, which is §2.4.20's word
list with a JSON file around it.

**What makes the ratio that bad is that JS has its own reservations, and they
are not ours to abolish.** Each entry in `IDIOM` below is a word the Python
table calls abolished and JavaScript spells for a reason:

* `fetch` is `window.fetch`, and in this codebase it is also the store's read
  from the server -- `fetchStoreData`, `fetchMessages`, `fetchSuggestions`.
  §2.4.3 already reserves `fetch` for "the ORM read operation that loads stored
  values into the cache" and says the spellings of one contract are renamed
  together or not at all. The JS half is that contract's other end.
* `make` is the framework's own factory idiom. `makeEnv` and `makeStore` are
  `web`'s, `makeRecordProxy` and `makeRecordClass` are mail's, and the file
  holding the last two is named `make_store.js`. The Payload row abolishes
  `_make_` in Python because `_prepare_` already means it; JS has no
  `_prepare_`, and a rename here would be inventing one.
* `assign` is `Object.assign`. mail's twelve are `assignDefined`,
  `assignGetter` and `assignIn` -- three helpers in `utils/common/misc.js` and
  their call sites -- and each is named for the built-in it wraps.
* `delete` and `fill` are the two that need the CALLEE and not the word.
  `deleteBackward` and `deleteForward` are `html_editor` plugin-contract names,
  and a plugin whose method is renamed is silently unhooked; `fillRect`,
  `fillRects` and `fillText` are the Canvas 2D API. Those six are exempt by
  NAME and the two contract trees by FILE. Nothing else is: their honest
  members stay in the report, so `fillPartnersMentionToken`, which wrote into a
  payload it was handed, is `updatePartnersMentionToken`, and `fillEmpty` and
  the three `delete*` the sweep left behind are still listed for a reader to
  judge.

So the report is a candidate list on §2.4.4's terms: a population to read, not
a defect list. Where it is wrong it is wrong in the direction that costs a
reader a minute, which is the only direction a non-blocking instrument may be
wrong in.

**The first version read only a third of the definitions, and the third it
skipped was the private one.** Every shape it matched began with `[a-z]`, so
a `_`-prefixed method -- the JS spelling of exactly the population the Python
gate is FOR -- was never a candidate, and neither was a member of an object
literal (`name: (x) => ...`, `name: function (`) or a class field bound to an
arrow. Measured on `addons/mail` when this was widened: **338** private method
shorthands and **470** object-literal members had been outside the scan, and
among them `_retrieveIdFromData`, two `_buildFormData` that mutate the
`FormData` they are handed, and two `_refresh*` that reset a timer and rewrite
a state key. In the other direction the shorthand shape had no way to tell a
method definition from a bare call statement, so `fillEmpty(parent);` -- a
call into an imported `html_editor` helper -- was reported as a definition in
mail. A definition's parameter list is followed by a `{`; a call's is followed
by `;`, `)` or `,`. The shorthand now requires the brace.

Two more words are JavaScript's own and join `IDIOM`: `find` and `filter` are
`Array.prototype`, and a `findDelimiterAt` or a `filterProgressValue` is named
for the built-in it wraps, where the Python table would send them to `_get_`
and `_filtered_`. Two more names are platform contracts and join
`PLATFORM_METHODS`: `deleteProperty` is a `Proxy` trap, and `locateFile` is the
Emscripten / MediaPipe module option a WASM loader reads by that exact key.
And the store's record system under `mail/static/src/model/` declares `delete`
as its own API -- `record.delete()`, `recordList.delete(...records)` and the
no-inverse variant beside it -- mirroring `Set.prototype.delete`, so that tree
joins `CONTRACT_TREES` for the same reason `html_editor`'s plugins do.

**`--bodies` asks the two questions a regex cannot.** The regex half reads the
verb a name opens with and nothing else, so a `get` that returns nothing and a
`set` that returns a value pass it -- and `getResults`, a get that pushed into
`this.commands` and returned nothing, was this reader's OWN rename before the
body was read. `js_naming_bodies.js` beside this file parses each root with
the `acorn` that eslint already ships in `node_modules` (no new dependency:
the flag reports why and skips when `node` or the package is absent) and
reports a get/is/has/can/find with no value return and a
set/update/add/remove/reset/clear that produces one. The exemptions are the
idioms the first run over `mail` taught: a store record's `<field>OnUpdate`
hook, an empty extension-point stub, a getter/setter pair, a `return false`
guard, a delegated call, and the subscribe idiom's returned disposer.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _sources
import naming_core_vocabulary as ncv
import naming_vocabulary as nv
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve())

# The words §2.4.3 abolishes, plus §2.4.20's synonyms and the assemble verbs
# `naming_core_vocabulary` reads on the same terms. Taken from those tables
# rather than restated, so a word added there is asked about here too and this
# file never becomes a second copy that drifts.
ABOLISHED = frozenset(nv.ABOLISHED) | frozenset(ncv.SYNONYMS) | ncv.ASSEMBLE

# Argued one by one in the module docstring. These are not exceptions to the
# vocabulary; they are words whose JavaScript meaning is a different word.
IDIOM = frozenset({"fetch", "make", "assign", "find", "filter"})

# `delete` and `fill` are honest verbs in most positions and contract names in
# three trees. Exempting the WORD would lose `fillPartnersMentionToken`, which
# was a real finding; exempting the TREE loses only the names those trees own.
CONTRACT_TREES = ("/plugin/", "_plugin.js", "/html_editor/", "mail/static/src/model/")

# A Canvas 2D, DOM, Proxy or WASM-loader method the code is implementing or
# wrapping, where the name is the platform's and not ours.
PLATFORM_METHODS = frozenset(
    {
        "fillRect",
        "fillRects",
        "fillText",
        "deleteBackward",
        "deleteForward",
        "deleteProperty",
        "locateFile",
    }
)

SKIP_DIRS = frozenset({"node_modules", "lib", "libs", "vendored", "_vendor"})

# A method shorthand in a class or object literal, a `function` declaration, an
# arrow bound to a const, an object-literal member bound to an arrow or a
# `function`, and a class field bound to an arrow. Deliberately not a JS
# parser: this reports a population for a human to read, and the cost of a
# regex missing a definition is one name nobody looks at, where the cost of
# adding a JS parser to this repository is a dependency for a non-blocking
# report.
#
# A name may open with `_` or `$`: the private prefix is the JS spelling of the
# population the Python gate exists for, and the first version of this reader
# could not see it at all.
_NAME = r"([_$a-z][A-Za-z0-9_$]*)"
# A parameter list with one level of nesting, enough for a destructured
# `({ force = false, unmute = true })` and a default `(a = fn(b))`.
_PARAMS = r"\((?:[^()]|\([^()]*\))*\)"
# The brace is what separates `name(args) {` -- a definition -- from
# `name(args);`, a call at statement level, which the same regex without it
# reported as a definition.
_SHORTHAND = re.compile(
    r"^[ \t]*(?:async[ \t]+|static[ \t]+|get[ \t]+|set[ \t]+|\*)*"
    + _NAME
    + r"[ \t]*"
    + _PARAMS
    + r"[ \t]*\{",
    re.MULTILINE,
)
_FUNCTION = re.compile(r"\bfunction[ \t]*\*?[ \t]+" + _NAME + r"[ \t]*\(")
_ARROW = re.compile(
    r"^[ \t]*(?:export[ \t]+)?(?:const|let|var)[ \t]+"
    + _NAME
    + r"[ \t]*=[ \t]*(?:async[ \t]*)?\(",
    re.MULTILINE,
)
_MEMBER = re.compile(
    r"^[ \t]+"
    + _NAME
    + r"[ \t]*:[ \t]*(?:async[ \t]*)?(?:function[ \t]*\*?[ \t]*\(|"
    + _PARAMS
    + r"[ \t]*=>)",
    re.MULTILINE,
)
_CLASS_FIELD = re.compile(
    r"^[ \t]+(?:static[ \t]+)?"
    + _NAME
    + r"[ \t]*=[ \t]*(?:async[ \t]*)?"
    + _PARAMS
    + r"[ \t]*=>",
    re.MULTILINE,
)
_SHAPES = (_SHORTHAND, _FUNCTION, _ARROW, _MEMBER, _CLASS_FIELD)

# `if (`, `for (`, `while (`, `catch (` and `switch (` all match the shorthand
# shape, and so does a bare call at statement level. A keyword list is exact
# where a heuristic would not be.
_KEYWORDS = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "return",
        "typeof",
        "await",
        "yield",
        "do",
        "else",
        "function",
        "new",
        "delete",
        "void",
        "in",
        "of",
    }
)


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    name: str
    verb: str
    why: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.name}  [{self.verb}] {self.why}"


def addon_src(addon: str) -> Path:
    return ROOT / "addons" / addon / "static" / "src"


def leading_verb(name: str) -> str | None:
    """The camelCase head of a JS method name, or None when there is no tail.

    `getKeySet` opens with `get`; `fetch` alone opens with nothing, because a
    bare verb in JS is as likely to be the contract being implemented as it is
    in Python -- §2.4.6's `[review]` tier, and the same argument
    `naming_core_vocabulary` makes for holding bare verbs out of its gate.
    """
    stem = name.lstrip("_$")
    head = re.match(r"[a-z]+", stem)
    if head is None:
        return None
    verb = head.group(0)
    return verb if len(verb) < len(stem) else None


def is_exempt(path: Path, name: str, verb: str) -> bool:
    if verb in IDIOM or name in PLATFORM_METHODS:
        return True
    display = path.as_posix()
    return verb in ("delete", "fill") and any(
        tree in display for tree in CONTRACT_TREES
    )


def scan_files(root: Path) -> list[Path]:
    return [
        path for path in sorted(root.rglob("*.js")) if not (set(path.parts) & SKIP_DIRS)
    ]


def definitions(text: str) -> list[tuple[str, int]]:
    """Every name this file appears to define, with its line."""
    found: list[tuple[str, int]] = []
    for regex in _SHAPES:
        for match in regex.finditer(text):
            name = match.group(1)
            if name in _KEYWORDS:
                continue
            found.append((name, text.count("\n", 0, match.start()) + 1))
    return found


def measure(root: Path) -> list[Violation]:
    files = scan_files(root)
    if not files:
        raise RuntimeError(
            f"no JavaScript under {root} -- refusing to report a count from an "
            f"empty scan"
        )
    seen: set[tuple[str, int, str]] = set()
    found: list[Violation] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        display = Path(_sources.display_across_repos(path, ROOT)).as_posix()
        for name, line in definitions(text):
            verb = leading_verb(name)
            if verb is None or verb not in ABOLISHED:
                continue
            if is_exempt(path, name, verb):
                continue
            if (display, line, name) in seen:
                continue
            seen.add((display, line, name))
            found.append(
                Violation(
                    path=display,
                    line=line,
                    name=name,
                    verb=verb,
                    why=_why(verb),
                )
            )
    found.sort(key=lambda v: (v.path, v.line))
    return found


def _why(verb: str) -> str:
    if verb in ncv.ASSEMBLE:
        return (
            "an assemble verb -- §2.4.3's Payload row; take the row the body satisfies"
        )
    if (entry := nv.ABOLISHED.get(verb)) is not None:
        canonical = entry[0].strip("_")
        return f"§2.4.3 abolishes it; the row's canonical is `{canonical}`"
    canonical, why = ncv.SYNONYMS[verb]
    return f"§2.4.20 synonym -> {canonical} -- {why}"


BODIES_SCRIPT = Path(__file__).with_name("js_naming_bodies.js")


def measure_bodies(roots: list[Path]) -> list[Violation] | str:
    """Body-aware rows for `roots`, or the reason the pass could not run."""
    node = shutil.which("node")
    if node is None:
        return "node is not on PATH"
    node_modules = ROOT / "node_modules"
    if not (node_modules / "acorn").is_dir():
        return f"acorn is not installed under {node_modules}"
    env = dict(os.environ, NODE_PATH=str(node_modules))
    result = subprocess.run(
        [node, str(BODIES_SCRIPT), *map(str, roots)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return (
            result.stderr.strip().splitlines()[-1] if result.stderr else "node failed"
        )
    rows = json.loads(result.stdout or "[]")
    found = [
        Violation(
            path=Path(_sources.display_across_repos(Path(r["path"]), ROOT)).as_posix(),
            line=r["line"],
            name=r["name"],
            verb=r["verb"],
            why=r["why"],
        )
        for r in rows
    ]
    found.sort(key=lambda v: (v.path, v.line))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--addon", default="mail", help="addon whose static/src to read"
    )
    parser.add_argument("--roots", nargs="+", help="scan these paths instead")
    parser.add_argument("--count", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top", type=int, default=30, help="0 for all")
    parser.add_argument(
        "--bodies",
        action="store_true",
        help="also parse each file with acorn and report a verb its body contradicts",
    )
    args = parser.parse_args(argv)

    roots = (
        [Path(r).resolve() for r in args.roots]
        if args.roots
        else [addon_src(args.addon)]
    )
    found: list[Violation] = []
    try:
        for root in roots:
            found += measure(root)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    bodies_note = None
    if args.bodies:
        bodies = measure_bodies(roots)
        if isinstance(bodies, str):
            bodies_note = bodies
        else:
            found += bodies
            found.sort(key=lambda v: (v.path, v.line))

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 0

    where = ", ".join(_sources.display_across_repos(r, ROOT) for r in roots)
    print(f"§2.4 method vocabulary in JavaScript -- {where}")
    print("=" * 72)
    for item in found if args.top == 0 else found[: args.top]:
        print(f"  {item}")
    if args.top and len(found) > args.top:
        print(f"  ... and {len(found) - args.top} more (--top 0 for all)")
    print("-" * 72)
    if bodies_note:
        print(f"  --bodies skipped: {bodies_note}")
    by_verb = collections.Counter(v.verb for v in found)
    print(f"\n{len(found)} candidate(s) -- a population to READ, not a floor\n")
    for verb, n in by_verb.most_common():
        print(f"    {verb:<12}{n:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
