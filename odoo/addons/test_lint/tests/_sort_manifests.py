import argparse
import ast
import json
import sys
from pathlib import Path

MANIFEST_KEY_ORDER: list[str] = [
    "name",
    "version",
    "category",
    "sequence",
    "summary",
    "description",
    "author",
    "contributors",
    "website",
    "icon",
    "images",
    "license",
    "depends",
    "external_dependencies",
    "countries",
    "data",
    "demo",
    "assets",
    "installable",
    "application",
    "auto_install",
    "post_load",
    "pre_init_hook",
    "post_init_hook",
    "uninstall_hook",
]

_KEY_RANK: dict[str, int] = {k: i for i, k in enumerate(MANIFEST_KEY_ORDER)}

_INDENT = "    "


def expected_key_order(present_keys: list[str]) -> list[str]:
    known = [k for k in MANIFEST_KEY_ORDER if k in present_keys]
    unknown = sorted(k for k in present_keys if k not in _KEY_RANK)
    return known + unknown


def _fmt_str(s: str) -> str:
    if "\n" in s:
        inner = s.replace("\\", "\\\\").replace('"""', r"\"\"\"")
        return f'"""{inner}"""'
    return json.dumps(s)


def _fmt_value(value: object, depth: int) -> str:
    pad = _INDENT * depth
    inner = _INDENT * (depth + 1)

    match value:
        case bool():
            return "True" if value else "False"
        case int():
            return str(value)
        case str():
            return _fmt_str(value)
        case None:
            return "None"
        case list():
            if not value:
                return "[]"
            items = "\n".join(f"{inner}{_fmt_value(v, depth + 1)}," for v in value)
            return f"[\n{items}\n{pad}]"
        case tuple():
            if not value:
                return "()"
            items = "\n".join(f"{inner}{_fmt_value(v, depth + 1)}," for v in value)
            return f"(\n{items}\n{pad})"
        case dict():
            if not value:
                return "{}"
            lines = "\n".join(
                f"{inner}{_fmt_str(k)}: {_fmt_value(v, depth + 1)},"
                for k, v in value.items()
            )
            return f"{{\n{lines}\n{pad}}}"
        case _:
            return repr(value)


def render_manifest(data: dict) -> str:
    ordered_keys = expected_key_order(list(data.keys()))
    body = "\n".join(f'{_INDENT}"{k}": {_fmt_value(data[k], 1)},' for k in ordered_keys)
    return f"{{\n{body}\n}}\n"


def sort_manifest(path: Path, *, dry_run: bool = False) -> bool | None:
    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        print(f"  SKIP  {path}: syntax error — {exc}", file=sys.stderr)
        return None

    dict_node: ast.Dict | None = None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Dict):
            dict_node = node.value
            break

    if dict_node is None:
        print(f"  SKIP  {path}: no top-level dict literal found", file=sys.stderr)
        return None

    try:
        data: dict = ast.literal_eval(dict_node)
    except (ValueError, TypeError) as exc:
        print(f"  SKIP  {path}: cannot evaluate dict — {exc}", file=sys.stderr)
        return None

    if not isinstance(data, dict):
        print(f"  SKIP  {path}: top-level literal is not a dict", file=sys.stderr)
        return None

    source_lines = source.splitlines(keepends=True)
    prefix = "".join(source_lines[: dict_node.lineno - 1])

    new_source = prefix + render_manifest(data)

    if new_source == source:
        return False

    if not dry_run:
        path.write_text(new_source, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Sort Odoo __manifest__.py keys into canonical order.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "roots",
        nargs="*",
        metavar="DIR",
        default=["."],
        help="Directories to search recursively (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Print which files would change without modifying them",
    )
    parser.add_argument(
        "--exclude",
        metavar="DIR",
        action="append",
        default=["_vendor"],
        help="Directory names to skip (default: _vendor); repeatable",
    )
    args = parser.parse_args(argv)

    excluded: set[str] = set(args.exclude)
    changed = unchanged = skipped = 0

    for root_str in args.roots:
        for manifest in sorted(Path(root_str).rglob("__manifest__.py")):
            if excluded.intersection(manifest.parts):
                continue
            result = sort_manifest(manifest, dry_run=args.dry_run)
            if result is None:
                skipped += 1
            elif result:
                label = "would sort" if args.dry_run else "sorted   "
                print(f"  {label}  {manifest}")
                changed += 1
            else:
                unchanged += 1

    verb = "would change" if args.dry_run else "sorted"
    print(f"\nDone: {changed} {verb}, {unchanged} unchanged, {skipped} skipped")


if __name__ == "__main__":
    main()
