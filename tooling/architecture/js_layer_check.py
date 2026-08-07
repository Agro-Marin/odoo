"""Feature-Sliced Design layering gate for the ``web`` addon's JavaScript.

The Python framework core has a drift-zero import-direction gate
(``layer_check.py``). The JavaScript side had *no* equivalent hard gate: the
same Feature-Sliced layering ("import direction is law") is encoded only as
ESLint ``no-restricted-imports`` rules (``eslint.config.mjs``), whose
violations fold into the single aggregate ESLint *count* baseline
(``tooling/ratchet/baselines/eslint.json`` ~= 122k). A new layering breach is
therefore only +1 in a six-figure floor — invisible signal-in-noise, and the
ratchet's ``exact`` mode lets unrelated lint churn mask it.

This gate gives JS layering its *own* drift-zero contract, exactly like the
Python side: any forbidden import that is not an explicitly pinned
``KNOWN_VIOLATIONS`` entry fails immediately.

It does two things the ESLint rules don't:

  1. Single source of truth. One ``CONTRACTS`` table instead of seven
     copy-pasted ``no-restricted-imports`` blocks.
  2. Closes a real gap. The ESLint ``model/`` rule forbids the widget/page
     layers but NOT ``@web/fields/*`` — an entity->feature breach (FSD:
     entities sit below features) that currently passes lint. The
     ``entity-no-feature`` contract below locks it at zero.

Layer model (low -> high; a file may import only its own layer or lower):

    shared    core/  services/  ui/  components/        (@web/{core,services,ui,components,env,session})
    entity    model/  core/domain.js                    (@web/model)
    feature   fields/                                   (@web/fields)
    widget    views/  search/                           (@web/views, @web/search)
    page      webclient/                                (@web/webclient)

Usage::

    python tooling/architecture/js_layer_check.py            # human-readable report
    python tooling/architecture/js_layer_check.py --check    # CI mode, exit 1 on any new violation
    python tooling/architecture/js_layer_check.py --json     # machine-readable

Type-only imports do NOT count: JSDoc ``@import`` tags and ``import("...")``
references inside comments create no runtime module edge, so comments are
stripped (newline-preserving, string-aware) before imports are collected —
mirroring how ``layer_check.py`` skips ``if TYPE_CHECKING:`` blocks.
"""

import argparse
import json
import re
import string
import sys
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

# Located by marker, not by counting parents — see _repo_root.
ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_layer_check")
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"


@dataclass(frozen=True)
class Contract:
    """A "forbidden import" rule: files under ``source`` (path prefixes,
    relative to the web ``static/src`` root) may not import any ``forbidden``
    module specifier (``@web/...`` prefix), unless it matches an ``allow``
    prefix.
    """

    name: str
    source: tuple[str, ...]
    forbidden: tuple[str, ...]
    allow: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class Known:
    """A pre-existing, tolerated violation pinned with its remediation.

    The gate is drift-zero: any import not on this list fails immediately.
    Entries here are visible technical debt. ``module`` is a path prefix
    (relative to the web ``static/src`` root); ``imports`` is a ``@web/...``
    specifier prefix.
    """

    module: str
    imports: str
    reason: str


# The web framework's JS layering is clean at zero today (verified: core/,
# services/, ui/, components/ import nothing from the feature/widget/page
# layers, and model/ imports neither views/ nor fields/). Keep it that way.
KNOWN_VIOLATIONS: tuple[Known, ...] = ()


CONTRACTS: tuple[Contract, ...] = (
    Contract(
        name="shared-below-feature-widget-page",
        source=("core", "services", "ui", "components"),
        forbidden=("@web/fields", "@web/views", "@web/search", "@web/webclient"),
        allow=(),
        rationale=(
            "The shared layer (core/, services/, ui/, components/) is the "
            "bottom of the dependency graph: it must not reach up into the "
            "feature (fields/), widget (views/, search/) or page (webclient/) "
            "layers. Cross-layer needs are met by registry indirection or "
            "dependency injection. Mirrors the ESLint core/services/ui/"
            "components rules as one contract."
        ),
    ),
    Contract(
        name="entity-below-widget-page",
        source=("model", "core/domain.js"),
        forbidden=("@web/views", "@web/search", "@web/webclient"),
        allow=(),
        rationale=(
            "The entity layer (the relational data model, plus core/domain.js) "
            "must not import the widget (views/, search/) or page (webclient/) "
            "layers. The data layer talks to the UI only through injected hooks "
            "(makeModelUIHooks). Mirrors the ESLint model/ + core/domain.js "
            "rules."
        ),
    ),
    Contract(
        name="entity-below-feature",
        source=("model",),
        forbidden=("@web/fields",),
        allow=(),
        rationale=(
            "GAP-CLOSING: FSD places entities below features, so the data "
            "model (model/) must not import field widgets (fields/). The "
            "ESLint model/ rule omits this, letting an entity->feature import "
            "pass lint. Verified zero today; locked here so it stays zero — a "
            "model that reached into a specific widget would re-couple the data "
            "layer to the view layer the makeModelUIHooks seam exists to "
            "decouple."
        ),
    ),
    Contract(
        name="feature-below-widget-page",
        source=("fields",),
        forbidden=("@web/views", "@web/search", "@web/webclient"),
        allow=(),
        rationale=(
            "The feature layer (fields/) must not import the widget (views/, "
            "search/) or page (webclient/) layers. Shared field/view code lives "
            "in core/ or is reached via registry indirection. Mirrors the "
            "ESLint fields/ rule."
        ),
    ),
)


@dataclass
class Violation:
    contract: str
    module: str
    imports: str
    path: str
    lineno: int


# ---------------------------------------------------------------------------
# Import collection
# ---------------------------------------------------------------------------

# Runtime ESM import forms (after comments are stripped):
#   import X from "spec";  import {a} from "spec";  import * as n from "spec";
#   export {a} from "spec";  export * from "spec";          -> _FROM_RE
#   import "spec";                                           -> _SIDE_EFFECT_RE
#   import("spec")                                           -> _DYNAMIC_RE
# The specifier class excludes newlines: a module specifier is a single-line
# string literal, so allowing one let these patterns run across unrelated string
# and template-literal content and invent specifiers hundreds of characters long
# (a Python snippet in `api_doc`, a `console.error` block in `point_of_sale`).
_FROM_RE = re.compile(r"""\bfrom\s*['"]([^'"\n]+)['"]""")
_SIDE_EFFECT_RE = re.compile(r"""\bimport\s*['"]([^'"\n]+)['"]""")
_DYNAMIC_RE = re.compile(r"""\bimport\s*\(\s*['"]([^'"\n]+)['"]""")


#: Identifier characters, for deciding whether a ``/`` follows a value.
_IDENT_CHARS = frozenset(string.ascii_letters + string.digits + "_$")

#: A ``/`` right after one of these ends a VALUE, so it is division, not a
#: regex. Everything else (operators, ``(``, ``,``, ``=``, ``{``, ``;``, ...)
#: puts the scanner in expression position, where ``/`` opens a regex literal.
_VALUE_END_CHARS = frozenset(")]\"'`")

#: ...except after these keywords, which are followed by an expression.
_REGEX_PRECEDING_KEYWORDS = frozenset(
    {
        "return",
        "typeof",
        "instanceof",
        "in",
        "of",
        "new",
        "delete",
        "void",
        "throw",
        "case",
        "do",
        "else",
        "yield",
        "await",
    }
)


def _starts_regex(tail: str) -> bool:
    """Whether a ``/`` seen after ``tail`` opens a regex literal."""
    stripped = tail.rstrip()
    if not stripped:
        return True
    last = stripped[-1]
    if last in _IDENT_CHARS:
        end = len(stripped)
        while end and stripped[end - 1] in _IDENT_CHARS:
            end -= 1
        return stripped[end:] in _REGEX_PRECEDING_KEYWORDS
    return last not in _VALUE_END_CHARS


def _regex_literal_end(src: str, start: int) -> int | None:
    """Index just past the closing ``/`` of the regex literal at ``start``.

    ``None`` when it does not close on the same line — a regex literal cannot
    span a newline, so that means ``/`` was division after all.

    That bound caps a misread at one line, which is NOT the same as harmless:
    a module specifier contains slashes, so a misread that starts before a
    same-line ``import("@web/x")`` or ``export {y} from "@web/x"`` closes on
    the slash inside the specifier and blanks the import. What keeps that from
    happening is :func:`_starts_regex` being fed real source, not the blanked
    output — see ``strip_comments``.
    """
    i, n = start + 1, len(src)
    in_class = False
    while i < n:
        c = src[i]
        if c == "\n":
            return None
        if c == "\\":
            i += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "/":
            return i + 1
        i += 1
    return None


#: Characters that can start a construct the scanner must resolve. Everything
#: between two of them is ordinary code and is copied in one slice, which is
#: what makes this a ~7x faster scan than stepping character by character.
_INTERESTING_RE = re.compile(r"""[/'"`]""")

#: How much preceding source :func:`_starts_regex` needs. Only the last token
#: matters, and no JS keyword is longer than ``instanceof``.
_TAIL_KEEP = 16


def strip_comments(src: str) -> str:
    """Blank ``//`` line comments, ``/* */`` block comments and regex literals,
    preserving every newline (so line numbers stay exact) and respecting string
    / template literals. Blanked characters become spaces; the text length and
    all newline positions are preserved.

    Regex literals are recognised, not just tolerated, because the scanner has
    no other way to know that the ``/*`` in ``name.replace(/^\\/*/, "")`` is not
    a comment. Without it the scanner desynchronises at the first such literal
    and everything after it is read in the wrong state — which is how a JSDoc
    ``import("@web/env")`` at ``public/public_boot.js:110`` became a runtime
    edge in the cycle graph, and how a real ``@web/webclient`` import placed
    after ``const re = /^\\/*/;`` became invisible to the layering gate.

    Their bodies are blanked rather than kept: no import, export or module
    specifier can live inside a regex, so blanking them costs nothing and
    removes the only remaining way a literal can be mistaken for one.

    Regex-vs-division is decided from ``tail``, the last significant characters
    of the SOURCE. It used to be decided from the last 32 entries of the OUTPUT
    buffer, which is a different thing the moment a comment precedes the ``/``:
    a comment blanks to spaces, so a block comment of 32 characters or more
    emptied the window, ``_starts_regex`` read that as expression position, and
    a plain division was consumed as a regex — closing on the next ``/`` in the
    line, which for ``let r = a /* explain the units here */ / b;
    import("@web/x")`` is the slash inside the specifier. The import vanished
    and the gate passed. Comments do not contribute to ``tail``, so the
    decision no longer depends on what happens to be nearby.
    """
    out: list[str] = []
    tail = ""  # last significant source chars; comments never enter it
    after_value = False  # last construct was a string/regex literal (a value)
    i, n = 0, len(src)
    while i < n:
        match = _INTERESTING_RE.search(src, i)
        if match is None:
            out.append(src[i:])
            break
        j = match.start()
        if j > i:
            chunk = src[i:j]
            out.append(chunk)
            if stripped := chunk.strip():
                tail = (tail + stripped)[-_TAIL_KEEP:]
                after_value = False
        char = src[j]
        nxt = src[j + 1] if j + 1 < n else ""

        if char == "/" and nxt == "/":
            end = src.find("\n", j)
            end = n if end == -1 else end
            out.append(" " * (end - j))
            i = end
            continue

        if char == "/" and nxt == "*":
            end = src.find("*/", j + 2)
            end = n if end == -1 else end + 2
            out.append("".join("\n" if c == "\n" else " " for c in src[j:end]))
            i = end
            continue

        if char == "/":
            if not after_value and _starts_regex(tail):
                end = _regex_literal_end(src, j)
                if end is not None:
                    out.append(" " * (end - j))
                    # A regex literal is a value: the next `/` divides it. The
                    # fail-safe reading anyway — division blanks nothing.
                    after_value = True
                    i = end
                    continue
            out.append("/")
            tail = (tail + "/")[-_TAIL_KEEP:]
            after_value = False
            i = j + 1
            continue

        # String or template literal: copied verbatim, escapes honoured.
        end = j + 1
        while end < n:
            c = src[end]
            if c == "\\":
                end += 2
                continue
            end += 1
            if c == char:
                break
        out.append(src[j:end])
        tail = (tail + char)[-_TAIL_KEEP:]
        after_value = True
        i = end
    return "".join(out)


def collect_imports(src: str) -> list[tuple[str, int]]:
    """Return ``[(specifier, lineno), ...]`` of runtime imports in ``src``."""
    cleaned = strip_comments(src)
    # Precompute line-start offsets for O(log n) line lookups.
    line_starts = [0]
    line_starts.extend(m.end() for m in re.finditer(r"\n", cleaned))

    def lineno_at(pos: int) -> int:
        return bisect_right(line_starts, pos)

    found: list[tuple[str, int]] = []
    for regex in (_FROM_RE, _SIDE_EFFECT_RE, _DYNAMIC_RE):
        found.extend(
            (m.group(1), lineno_at(m.start(1))) for m in regex.finditer(cleaned)
        )
    return found


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _matches_path(rel: str, prefixes: tuple[str, ...]) -> bool:
    """True if ``rel`` (a forward-slash path relative to the web src root)
    equals or sits under any of ``prefixes``."""
    return any(rel == p or rel.startswith(p + "/") for p in prefixes)


def _matches_spec(spec: str, prefixes: tuple[str, ...]) -> bool:
    """True if a ``@web/...`` import ``spec`` equals or sits under any of
    ``prefixes`` (slash-delimited)."""
    return any(spec == p or spec.startswith(p + "/") for p in prefixes)


def _is_known(rel: str, target: str) -> bool:
    return any(
        _matches_path(rel, (k.module,)) and _matches_spec(target, (k.imports,))
        for k in KNOWN_VIOLATIONS
    )


def iter_source_files() -> list[Path]:
    if not WEB_SRC.is_dir():
        return []
    return [
        f
        for f in sorted(WEB_SRC.rglob("*.js"))
        if "__pycache__" not in f.parts
        # legacy/ predates the layering; not governed by these contracts.
        and "legacy" not in f.relative_to(WEB_SRC).parts
    ]


def check(
    files: list[Path] | None = None,
) -> tuple[list[Violation], list[Violation]]:
    """Return ``(new_violations, known_violations)``.

    ``files`` lets a caller that already walked the tree pass the result in,
    so the reported "Files scanned" count describes the walk that was actually
    checked instead of a second one taken moments later. ``layer_check.py``
    already threads it this way; the two JS gates did not.
    """
    new: list[Violation] = []
    known: list[Violation] = []
    for path in files if files is not None else iter_source_files():
        rel = path.relative_to(WEB_SRC).as_posix()
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover
            print(f"warning: could not read {path}: {exc}", file=sys.stderr)
            continue
        imports = collect_imports(src)
        for contract in CONTRACTS:
            if not _matches_path(rel, contract.source):
                continue
            for target, lineno in imports:
                if not target.startswith("@web/"):
                    continue
                if not _matches_spec(target, contract.forbidden):
                    continue
                if contract.allow and _matches_spec(target, contract.allow):
                    continue
                v = Violation(
                    contract=contract.name,
                    module=rel,
                    imports=target,
                    path=str(path.relative_to(ROOT)),
                    lineno=lineno,
                )
                (known if _is_known(rel, target) else new).append(v)
    return new, known


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any NEW violation"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    files = iter_source_files()
    new, known = check(files)
    scanned = len(files)

    if args.json:
        print(
            json.dumps(
                {
                    "new": [v.__dict__ for v in new],
                    "known": [v.__dict__ for v in known],
                    "files_scanned": scanned,
                },
                indent=2,
            )
        )
    else:
        print("JS architecture layering check (Feature-Sliced Design)")
        print("=" * 64)
        for contract in CONTRACTS:
            n = sum(v.contract == contract.name for v in new)
            k = sum(v.contract == contract.name for v in known)
            status = "FAIL" if n else "ok"
            suffix = f" (+{k} known)" if k else ""
            print(f"[{status:>4}] {contract.name}: {n} new{suffix}")
        print("-" * 64)
        if new:
            print(f"\n{len(new)} NEW violation(s) — these fail the gate:\n")
            for v in new:
                print(f"  {v.path}:{v.lineno}")
                print(f"      {v.module}  ->  {v.imports}")
                print(f"      breaks contract: {v.contract}")
        else:
            print("\nNo new violations. All JS layering contracts hold. ✓")
        if known:
            print(f"\n{len(known)} known exception(s) tolerated (tracked debt):\n")
            for v in known:
                print(f"  {v.path}:{v.lineno}  {v.module} -> {v.imports}")
        print(f"\nFiles scanned: {scanned}")
        print(f"New: {len(new)}   Known/tolerated: {len(known)}")

    if args.check and new:
        print(f"\nFAILED: {len(new)} new JS layering violation(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
