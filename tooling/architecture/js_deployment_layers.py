import argparse
import json
import posixpath
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root
from js_imports import collect_imports

ADR = "0019"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_deployment_layers")
ADDON_ROOTS: tuple[Path, ...] = (ROOT / "addons", ROOT / "odoo" / "addons")

EXCLUDED_PARTS = frozenset({"lib", "legacy", "__pycache__"})
SOURCE_SUFFIXES = frozenset({".js", ".xml"})

STATIC_TEMPLATE_RE = re.compile(r"""\bstatic\s+template\s*=\s*["']([\w.-]+)["']""")
T_NAME_RE = re.compile(r"""\bt-name=["']([\w.-]+)["']""")
T_INHERIT_RE = re.compile(r"""\bt-inherit=["']([\w.-]+)["']""")

BACKEND, PUBLIC, PORTAL = "backend", "public", "portal"

LAYER_BUNDLES: dict[str, frozenset[str]] = {
    "common": frozenset({BACKEND, PUBLIC, PORTAL}),
    "public_web": frozenset({BACKEND, PUBLIC}),
    "web_portal": frozenset({BACKEND, PORTAL}),
    "web": frozenset({BACKEND}),
    "public": frozenset({PUBLIC}),
}


@dataclass(frozen=True)
class Known:
    module: str
    imports: str
    reason: str


KNOWN_VIOLATIONS: tuple[Known, ...] = ()


@dataclass(frozen=True)
class Violation:
    module: str
    module_layer: str
    imports: str
    imports_layer: str
    path: str
    lineno: int
    missing: tuple[str, ...]


def layer_of(rel: str) -> str | None:

    for part in rel.split("/"):
        if part in LAYER_BUNDLES:
            return part
    return None


def addon_src_dirs() -> dict[str, Path]:
    dirs: dict[str, Path] = {}
    for root in ADDON_ROOTS:
        if not root.is_dir():
            continue
        for addon in sorted(root.iterdir()):
            src = addon / "static" / "src"
            if src.is_dir() and addon.name not in dirs:
                dirs[addon.name] = src
    return dirs


def iter_source_files() -> list[tuple[str, Path, Path]]:
    out: list[tuple[str, Path, Path]] = []
    for addon, src in addon_src_dirs().items():
        for path in sorted(p for p in src.rglob("*") if p.suffix in SOURCE_SUFFIXES):
            rel_parts = path.relative_to(src).parts
            if EXCLUDED_PARTS.intersection(rel_parts):
                continue
            if layer_of(path.relative_to(src).as_posix()) is None:
                continue
            out.append((addon, src, path))
    return out


NON_ADDON_SCOPES = frozenset({"odoo"})


def resolve(
    spec: str, addon: str, rel: str, addons: frozenset[str] | None = None
) -> str | None:

    if spec.startswith("."):
        target = posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec))
        if target.startswith(".."):
            return None
        return f"{addon}/{target.removesuffix('.js')}"
    if spec.startswith("@"):
        other, _, target = spec[1:].partition("/")
        if not target or target.startswith("../"):
            return None
        if other in NON_ADDON_SCOPES:
            return None
        if addons is not None and other not in addons:
            return None
        return f"{other}/{target.removesuffix('.js')}"
    return None


def _is_known(module: str, target: str) -> bool:
    return any(k.module == module and k.imports == target for k in KNOWN_VIOLATIONS)


def _lineno(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover
        print(f"warning: could not read {path}: {exc}", file=sys.stderr)
        return None


def index_templates(files: list[tuple[str, Path, Path]]) -> dict[str, str]:

    defined: dict[str, str] = {}
    for addon, src, path in files:
        if path.suffix != ".xml":
            continue
        text = _read(path)
        if text is None:
            continue
        rel = path.relative_to(src).as_posix()
        for match in T_NAME_RE.finditer(text):
            defined.setdefault(match.group(1), f"{addon}/{rel}")
    return defined


def template_references(path: Path, text: str) -> list[tuple[str, int]]:
    pattern = STATIC_TEMPLATE_RE if path.suffix == ".js" else T_INHERIT_RE
    return [(m.group(1), _lineno(text, m.start())) for m in pattern.finditer(text)]


def check(
    files: list[tuple[str, Path, Path]] | None = None,
) -> tuple[list[Violation], list[Violation]]:

    new: list[Violation] = []
    known: list[Violation] = []
    selected = files if files is not None else iter_source_files()
    addons = frozenset(a for a, _, _ in selected)
    templates = index_templates(selected)
    for addon, src, path in selected:
        rel = path.relative_to(src).as_posix()
        src_layer = layer_of(rel)
        src_bundles = LAYER_BUNDLES[src_layer]
        module = f"{addon}/{rel.removesuffix('.js')}"
        text = _read(path)
        if text is None:
            continue
        edges: list[tuple[str, int]] = []
        if path.suffix == ".js":
            for spec, lineno in collect_imports(text):
                target = resolve(spec, addon, rel, addons)
                if target is not None:
                    edges.append((target, lineno))
        for name, lineno in template_references(path, text):
            defining_file = templates.get(name)
            if defining_file is not None:
                edges.append((f"{defining_file}#{name}", lineno))
        for target, lineno in edges:
            target_layer = layer_of(target.partition("/")[2])
            if target_layer is None:
                continue
            missing = src_bundles - LAYER_BUNDLES[target_layer]
            if not missing:
                continue
            v = Violation(
                module=module,
                module_layer=src_layer,
                imports=target,
                imports_layer=target_layer,
                path=str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
                lineno=lineno,
                missing=tuple(sorted(missing)),
            )
            (known if _is_known(module, target) else new).append(v)
    return new, known


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any NEW violation"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    files = iter_source_files()
    scanned = len(files)
    if not scanned:
        parser.error(
            "no layered JS sources under "
            f"{', '.join(str(r) for r in ADDON_ROOTS)} — the scan reached nothing"
        )

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
                sort_keys=True,
            )
        )
        return 1 if (args.check and new) else 0

    print("JS deployment-layer check (drift-zero)")
    print("=" * 64)
    print()
    if not new:
        print("No cross-layer import reaches a layer that ships less. ✓")
    else:
        print(f"{len(new)} NEW violation(s):")
        for v in new:
            print(f"\n  {v.path}:{v.lineno}")
            print(f"    {v.module_layer}/ imports {v.imports_layer}/ — {v.imports}")
            print(
                f"    {v.imports_layer}/ is absent from: {', '.join(v.missing)}; "
                f"the import resolves to undefined there."
            )
    if known:
        print(f"\n{len(known)} known violation(s) tolerated (tracked debt):")
        for v in known:
            print(f"  {v.module} -> {v.imports}")
    print(f"\nLayered files scanned (JS and XML): {scanned}")
    print(f"New: {len(new)}   Known/tolerated: {len(known)}")
    return 1 if (args.check and new) else 0


if __name__ == "__main__":
    raise SystemExit(main())
