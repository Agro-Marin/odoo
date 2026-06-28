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
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Repo root = the directory that contains ``odoo/`` and ``addons/``. This file
# lives at ``<root>/tooling/architecture/js_layer_check.py``.
ROOT = Path(__file__).resolve().parent.parent.parent
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
_FROM_RE = re.compile(r"""\bfrom\s*['"]([^'"]+)['"]""")
_SIDE_EFFECT_RE = re.compile(r"""\bimport\s*['"]([^'"]+)['"]""")
_DYNAMIC_RE = re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]""")


def strip_comments(src: str) -> str:
    """Blank out ``//`` line and ``/* */`` block comments, preserving every
    newline (so line numbers stay exact) and respecting string / template
    literals (so a ``"https://x"`` URL or a ``/regex/`` is never mistaken for
    a comment). Comment characters become spaces; the text length and all
    newline positions are preserved.
    """
    out = []
    i, n = 0, len(src)
    state = "code"  # code | line | block | sq | dq | tpl
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state == "code":
            if c == "/" and nxt == "/":
                state = "line"
                out.append("  ")
                i += 2
                continue
            if c == "/" and nxt == "*":
                state = "block"
                out.append("  ")
                i += 2
                continue
            if c == "'":
                state = "sq"
            elif c == '"':
                state = "dq"
            elif c == "`":
                state = "tpl"
            out.append(c)
            i += 1
        elif state == "line":
            if c == "\n":
                state = "code"
                out.append("\n")
            else:
                out.append(" ")
            i += 1
        elif state == "block":
            if c == "*" and nxt == "/":
                state = "code"
                out.append("  ")
                i += 2
                continue
            out.append("\n" if c == "\n" else " ")
            i += 1
        else:  # inside a string / template literal
            out.append(c)
            if c == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if (
                (state == "sq" and c == "'")
                or (state == "dq" and c == '"')
                or (state == "tpl" and c == "`")
            ):
                state = "code"
            i += 1
    return "".join(out)


def collect_imports(src: str) -> list[tuple[str, int]]:
    """Return ``[(specifier, lineno), ...]`` of runtime imports in ``src``."""
    cleaned = strip_comments(src)
    # Precompute line-start offsets for O(log n) line lookups.
    line_starts = [0]
    for m in re.finditer("\n", cleaned):
        line_starts.append(m.end())

    def lineno_at(pos: int) -> int:
        # bisect_right without importing bisect for a couple of call sites.
        lo, hi = 0, len(line_starts)
        while lo < hi:
            mid = (lo + hi) // 2
            if line_starts[mid] <= pos:
                lo = mid + 1
            else:
                hi = mid
        return lo

    found: list[tuple[str, int]] = []
    for regex in (_FROM_RE, _SIDE_EFFECT_RE, _DYNAMIC_RE):
        for m in regex.finditer(cleaned):
            found.append((m.group(1), lineno_at(m.start(1))))
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


def check() -> tuple[list[Violation], list[Violation]]:
    """Return ``(new_violations, known_violations)``."""
    new: list[Violation] = []
    known: list[Violation] = []
    for path in iter_source_files():
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

    new, known = check()
    scanned = len(iter_source_files())

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
