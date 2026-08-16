#!/usr/bin/env python3


from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ODOO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="generate_service_types")
WEB_SRC_ROOT = ODOO_ROOT / "addons/web/static/src"
DEFAULT_OUTPUT = WEB_SRC_ROOT / "@types/services.d.ts"

_DIRECT_CHAIN = r'registry\s*\.\s*category\s*\(\s*"services"\s*\)'

_ALIAS_DECL_RE = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*" + _DIRECT_CHAIN,
)

_JSDOC_CAST_RE = re.compile(
    r"/\*\*[^*]*(?:\*(?!/)[^*]*)*\*/\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
)

_EXPORT_CONST_RE = re.compile(
    r"^\s*export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
    re.MULTILINE,
)

_SKIP_FRAGMENTS = ("/tests/", "/legacy/")


def _rel(path: Path) -> Path:
    try:
        return path.resolve().relative_to(ODOO_ROOT)
    except ValueError:
        return path


_CATEGORY_ORDER: list[tuple[str, str]] = [
    ("core", "Core infrastructure services"),
    ("public", "Public services"),
    ("services", "Domain services"),
    ("fields", "Domain services"),
    ("components", "Domain services"),
    ("ui", "UI overlay services"),
    ("views", "View services"),
    ("webclient", "Webclient services"),
]


@dataclass(frozen=True, order=True)
class Registration:
    key: str
    factory_var: str
    import_path: str
    source_file: Path
    top_level_dir: str


def _js_to_import_path(file: Path) -> str:

    rel = file.relative_to(WEB_SRC_ROOT)
    return "@web/" + rel.with_suffix("").as_posix()


def _top_level_dir(file: Path) -> str:
    rel = file.relative_to(WEB_SRC_ROOT)
    return rel.parts[0] if rel.parts else ""


def _find_export(text: str, var_name: str) -> bool:
    return any(match.group(1) == var_name for match in _EXPORT_CONST_RE.finditer(text))


def _strip_jsdoc_casts(text: str) -> str:

    return _JSDOC_CAST_RE.sub(r"\1", text)


def _build_registration_re(aliases: set[str]) -> re.Pattern[str]:

    alts = [_DIRECT_CHAIN]
    alts.extend(rf"\b{re.escape(alias)}\b" for alias in sorted(aliases))
    chain = "(?:" + "|".join(alts) + ")"
    return re.compile(
        chain
        + r"\s*\.\s*add\s*\("
        + r'\s*"([^"]+)"\s*,'
        + r"\s*([A-Za-z_][A-Za-z0-9_]*)"
        + r"\s*[,)]",
        re.DOTALL,
    )


def discover(src_root: Path = WEB_SRC_ROOT) -> list[Registration]:

    found: list[Registration] = []
    for js_file in sorted(src_root.rglob("*.js")):
        rel_str = "/" + js_file.relative_to(src_root).as_posix()
        if any(frag in rel_str for frag in _SKIP_FRAGMENTS):
            continue
        try:
            raw_text = js_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(
                f"  ✗ {js_file}: not UTF-8, skipping",
                file=sys.stderr,
            )
            continue
        text = _strip_jsdoc_casts(raw_text)
        aliases = {m.group(1) for m in _ALIAS_DECL_RE.finditer(text)}
        registration_re = _build_registration_re(aliases)
        for match in registration_re.finditer(text):
            key, factory_var = match.group(1), match.group(2)
            if not _find_export(text, factory_var):
                print(
                    f"  ⚠ {js_file.name}: registers {key!r} as "
                    f"{factory_var!r} but no `export const {factory_var}` "
                    f"in same file — skipped",
                    file=sys.stderr,
                )
                continue
            found.append(
                Registration(
                    key=key,
                    factory_var=factory_var,
                    import_path=_js_to_import_path(js_file),
                    source_file=js_file,
                    top_level_dir=_top_level_dir(js_file),
                )
            )
    return sorted(found)


def _quote_if_needed(key: str) -> str:

    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return key
    return f'"{key}"'


def render(registrations: list[Registration]) -> str:

    out: list[str] = []
    out.append('declare module "services" {\n')
    out.append('    import { ServicesRegistryShape } from "registries";\n')

    by_dir: dict[str, list[Registration]] = {}
    for reg in registrations:
        by_dir.setdefault(reg.top_level_dir, []).append(reg)

    last_label: str | None = None
    for dirname, label in _CATEGORY_ORDER:
        items = by_dir.get(dirname, [])
        if not items:
            continue
        if label != last_label:
            out.append("\n")
            out.append(f"    // {label}\n")
            last_label = label
        out.extend(
            f'    import {{ {reg.factory_var} }} from "{reg.import_path}";\n'
            for reg in sorted(items, key=lambda r: r.factory_var)
        )

    handled = {d for d, _ in _CATEGORY_ORDER}
    other: list[Registration] = []
    for dirname, items in by_dir.items():
        if dirname not in handled:
            other.extend(items)
    if other:
        out.append("\n    // Other services\n")
        out.extend(
            f'    import {{ {reg.factory_var} }} from "{reg.import_path}";\n'
            for reg in sorted(other, key=lambda r: r.factory_var)
        )

    out.append("\n")
    out.append(
        "    type ExtractServiceFactory<T extends ServicesRegistryShape>"
        ' = Awaited<ReturnType<T["start"]>>;\n'
    )
    out.append("    export type ServiceFactories = {\n")
    out.append("        [P in keyof Services]: ExtractServiceFactory<Services[P]>;\n")
    out.append("    };\n")
    out.append("\n")
    out.append("    export interface Services {\n")
    out.extend(
        f"        {_quote_if_needed(reg.key)}: typeof {reg.factory_var};\n"
        for reg in registrations
    )
    out.append("    }\n")
    out.append("}\n")
    return "".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate addons/odoo/addons/web/static/src/@types/services.d.ts",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Output file (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "CI mode: exit non-zero if the committed file disagrees "
            "with the regenerated one. Does not write."
        ),
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    registrations = discover()
    new_content = render(registrations)
    output_path = Path(args.output)

    if args.check:
        try:
            current = output_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(
                f"✗ {_rel(output_path)} does not exist. "
                f"Run without --check to generate.",
                file=sys.stderr,
            )
            return 1
        if current != new_content:
            print(
                f"✗ {_rel(output_path)} is out of date.\n"
                f"  Run: python {_rel(Path(__file__).resolve())}",
                file=sys.stderr,
            )
            return 1
        if not args.quiet:
            print(f"✓ {_rel(output_path)} is up to date.")
        return 0

    output_path.write_text(new_content, encoding="utf-8")
    if not args.quiet:
        print(f"✓ Wrote {len(registrations)} services to {_rel(output_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
