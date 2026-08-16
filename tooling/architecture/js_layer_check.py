import argparse
import json
import posixpath
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root
from js_imports import collect_imports

ADR = "0019"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_layer_check")
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"


@dataclass(frozen=True)
class Contract:
    name: str
    source: tuple[str, ...]
    forbidden: tuple[str, ...]
    allow: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class Known:
    module: str
    imports: str
    reason: str


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
    imports: str
    path: str
    lineno: int
    written: str = ""


def _matches_path(rel: str, prefixes: tuple[str, ...]) -> bool:
    return any(rel == p or rel.startswith(p + "/") for p in prefixes)


def _matches_spec(spec: str, prefixes: tuple[str, ...]) -> bool:
    return any(spec == p or spec.startswith(p + "/") for p in prefixes)


def normalise_spec(spec: str, rel: str) -> str | None:

    if spec.startswith("@"):
        return spec
    if not spec.startswith("."):
        return None
    target = posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec))
    if target.startswith(".."):
        return None
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
        if "__pycache__" not in f.parts and "legacy" not in f.relative_to(WEB_SRC).parts
    ]


def check(
    files: list[Path] | None = None,
) -> tuple[list[Violation], list[Violation]]:

    new: list[Violation] = []
    known: list[Violation] = []
    for path in files if files is not None else iter_source_files():
        rel = path.relative_to(WEB_SRC).as_posix()
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover
            print(f"warning: could not read {path}: {exc}", file=sys.stderr)
            continue
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
