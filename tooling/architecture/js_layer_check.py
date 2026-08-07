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

    core/  <  ui/  <  components/  <  model/  <  fields/  <  search/  <  views/  <  webclient/

``core/domain.js`` is pinned to the entity layer alongside ``model/``.
``boot/``, ``public/`` and ``libs/`` sit outside the stack and are ungoverned.

This was once a flat *shared* tier holding ``core/``, ``services/``, ``ui/`` and
``components/`` together. Two things changed it: ``services/`` was dissolved in
2026-08 (a directory named for a mechanism rather than a concern, holding 20
registered services and 19 files that registered nothing), and the remaining
three were found to be genuinely ordered rather than peers — overlay
infrastructure sits *below* the widgets that open it. Both are recorded in the
per-contract rationales below, which are the authority; this summary is not.

Note that the order is stricter than the import graph requires. Seven of the 8!
orderings score zero against the real edges, differing in where ``model/`` and
``search/`` sit. The extra constraints are deliberate — ``model/`` is held below
``ui/`` and ``components/`` so the data layer reaches UI only through the
``makeModelUIHooks`` seam — and each one says so where it is defined.

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
import posixpath
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root
from js_imports import collect_imports  # sys.path set by conftest.py

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
        source=("core", "ui", "components"),
        forbidden=("@web/fields", "@web/views", "@web/search", "@web/webclient"),
        allow=(),
        rationale=(
            "The shared layer (core/, ui/, components/) is the bottom of the "
            "dependency graph: it must not reach up into the feature (fields/), "
            "widget (views/, search/) or page (webclient/) layers. Cross-layer "
            "needs are met by registry indirection or dependency injection. "
            "Mirrors the ESLint core/ui/components rules as one contract. "
            "`services/` was a fourth member until it was dissolved: it grouped "
            "20 modules by the fact that they call registry.add(), with zero "
            "import edges between any two of them."
        ),
    ),
    # The three contracts below order the inside of what used to be one flat
    # `shared` tier. That flatness is what let `services/` accumulate: a
    # namespace could sit among the shared layers importing freely across them
    # and break no contract. Chosen by measurement, not taste — scoring all 9!
    # orderings of the layers against the real import graph puts
    # `core < ui < components` at the minimum, and the alternative
    # `components < ui` at 15 violations against 3.
    Contract(
        name="core-below-ui-components",
        source=("core",),
        forbidden=("@web/ui", "@web/components", "@web/model"),
        allow=(),
        rationale=(
            "core/ is the floor: registry, domain, py_js, l10n, network, the "
            "browser abstraction. It owns no surface and no datapoint, so a "
            "core module reaching into ui/, components/ or model/ means "
            "something was filed too low — the edge that took "
            "`core/formatters.js` into the old `services/currency.js`."
        ),
    ),
    Contract(
        name="ui-below-components",
        source=("ui",),
        forbidden=("@web/components", "@web/model"),
        allow=(),
        rationale=(
            "Overlay infrastructure (dialog, popover, tooltip, notification, "
            "overlay) sits BELOW the widgets that use it, not above: a widget "
            "opens a popover, a popover does not know what a widget is. A "
            "ui/ module importing a component is a single-purpose service "
            "filed away from what it serves — how `datetime_picker_service` "
            "and `error_handlers` came to sit here before moving next to the "
            "components they render."
        ),
    ),
    Contract(
        name="components-below-entity",
        source=("components",),
        forbidden=("@web/model",),
        allow=(),
        rationale=(
            "Presentational components take their data as props. Reaching "
            "into model/ would let a component bind itself to the relational "
            "datapoint rather than to the values it renders."
        ),
    ),
    Contract(
        name="widget-order",
        source=("search",),
        forbidden=("@web/views", "@web/webclient"),
        allow=(),
        rationale=(
            "views/ composes search/ (the control panel is part of a view), so "
            "the dependency runs one way only. Both sit below the page layer."
        ),
    ),
    Contract(
        name="widget-below-page",
        source=("views",),
        forbidden=("@web/webclient",),
        allow=(),
        rationale=(
            "webclient/ is the app shell: it mounts views, and a view that "
            "reached back into the shell could not be rendered anywhere else — "
            "which is what a dialog, a POS screen and a public page all need."
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
    imports: str  # canonical @web/... form — what the contract matched
    path: str
    lineno: int
    #: How the import is actually spelled in the file, when that differs from
    #: ``imports``. A report that says ``core/domain.js -> @web/views/utils``
    #: over a line reading ``from "../views/utils"`` sends the reader grepping
    #: for a string that is not there.
    written: str = ""


# ---------------------------------------------------------------------------
# Import collection
# ---------------------------------------------------------------------------

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


def normalise_spec(spec: str, rel: str) -> str | None:
    """An import specifier as its canonical ``@web/...`` form, or ``None``.

    Contracts are written in ``@web/...`` terms because that is how Odoo's ESM
    normally spells a cross-directory import — but it is not the only way, and
    ``check`` used to skip anything that did not literally start with ``@web/``.
    A relative specifier resolves to the same module and crosses the same
    layers, so ``core/domain.js`` importing ``"../views/utils"`` was a real
    entity->widget breach that the gate could not see, while the identical
    ``"@web/views/utils"`` produced two violations. Measured when this was
    fixed: **448 relative specifiers** across the 698 governed files — roughly a
    third of the import edges in the gated tree were being matched against
    nothing. None of them crossed a layer, so the gate was green by luck rather
    than by enforcement, and the ESLint ``no-restricted-imports`` rules the
    module docstring cites as the weaker predecessor share the blind spot, so
    there was no backstop either.

    ``js_cycle_check._resolve`` has always resolved these; this is that
    arithmetic, applied to the layering gate.

    ``None`` for anything that is not a first-party ``web`` module: a bare
    package, another addon's ``@mail/...``, or a relative path that climbs out
    of ``static/src`` (``../../lib/...`` — vendored code, not governed here).
    """
    if spec.startswith("@"):
        return spec
    if not spec.startswith("."):
        return None  # bare package specifier (@odoo/owl is caught above)
    # posixpath, not Path: pure specifier arithmetic on forward-slash module
    # ids, with no filesystem or symlink semantics wanted.
    target = posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec))
    if target.startswith(".."):
        return None  # leaves static/src
    return "@web/" + target.removesuffix(".js")


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
        # Normalise once per file, not once per contract: the arithmetic is the
        # same for all four and depends only on the importing module's path.
        imports = [
            (normalise_spec(spec, rel), spec, lineno)
            for spec, lineno in collect_imports(src)
        ]
        for contract in CONTRACTS:
            if not _matches_path(rel, contract.source):
                continue
            for target, spelled, lineno in imports:
                if target is None or not target.startswith("@web/"):
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
                    written="" if spelled == target else spelled,
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
    scanned = len(files)
    # A gate that finds no inputs must say so rather than scan nothing and
    # report success. `cross_repo_coherence` shipped exactly that fault three
    # times over: "0 violations" and "0 files examined" printed identically,
    # and only one of them is a verdict.
    if not scanned:
        parser.error(f"no JS sources under {WEB_SRC} — the scan reached nothing")

    new, known = check(files)

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
                spelled = f'  (written "{v.written}")' if v.written else ""
                print(f"      {v.module}  ->  {v.imports}{spelled}")
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
