"""Manifest key sorter — formatter and standalone fixer for ``__manifest__.py`` files.

This module serves two roles:

1. **Library** — ``MANIFEST_KEY_ORDER`` and ``_KEY_RANK`` are imported by
   ``test_manifests.py`` to enforce canonical ordering as a lint check.

2. **Standalone fixer** — run directly to rewrite manifests in-place::

       python _sort_manifests.py [DIR ...]       # rewrite in-place
       python _sort_manifests.py --dry-run [DIR ...]  # preview only

   Or via the venv from the project root::

       ./venv/odoo/bin/python core/odoo/addons/test_lint/tests/_sort_manifests.py addons_custom core

No Odoo imports; operates on raw ``__manifest__.py`` files via ``ast``.
"""

import argparse
import ast
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Canonical key order
# Grouped: identity/description → attribution → requirements → content → flags → hooks
# ---------------------------------------------------------------------------

MANIFEST_KEY_ORDER: list[str] = [
    # Identity / description
    "name",
    "version",
    "category",
    "sequence",
    "summary",
    "description",
    # Attribution
    "author",
    "contributors",
    "website",
    "icon",
    "images",
    # Technical requirements
    "license",
    "depends",
    "external_dependencies",
    "countries",
    # Content
    "data",
    "demo",
    "assets",
    # Behaviour flags
    "installable",
    "application",
    "auto_install",
    # Lifecycle hooks
    "post_load",
    "pre_init_hook",
    "post_init_hook",
    "uninstall_hook",
]

_KEY_RANK: dict[str, int] = {k: i for i, k in enumerate(MANIFEST_KEY_ORDER)}

_INDENT = "    "


def expected_key_order(present_keys: list[str]) -> list[str]:
    """Return the canonical ordering for the given list of manifest keys.

    Known keys are sorted by their position in ``MANIFEST_KEY_ORDER``.
    Unknown keys (not in the canonical list) are appended alphabetically.
    """
    known = [k for k in MANIFEST_KEY_ORDER if k in present_keys]
    unknown = sorted(k for k in present_keys if k not in _KEY_RANK)
    return known + unknown


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

def _fmt_str(s: str) -> str:
    """Render a string value as Python source, preferring double quotes."""
    if "\n" in s:
        # Triple-quoted block string — escape any embedded triple-double-quotes.
        inner = s.replace("\\", "\\\\").replace('"""', r'\"\"\"')
        return f'"""{inner}"""'
    # json.dumps always produces a double-quoted, properly escaped string.
    return json.dumps(s)


def _fmt_value(value: object, depth: int) -> str:
    """Recursively format a manifest value as Python source."""
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
    """Render a manifest dict as a complete ``__manifest__.py`` source string."""
    ordered_keys = expected_key_order(list(data.keys()))
    body = "\n".join(
        f'{_INDENT}"{k}": {_fmt_value(data[k], 1)},' for k in ordered_keys
    )
    return f"{{\n{body}\n}}\n"


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

def sort_manifest(path: Path, *, dry_run: bool = False) -> bool | None:
    """Rewrite *path* with manifest keys in canonical order.

    Any comment/copyright header preceding the dict literal is preserved.

    Returns:
        ``True``  — file was changed (or would change in dry-run mode)
        ``False`` — file was already canonical; no change needed
        ``None``  — file was skipped due to a parse error (warning on stderr)
    """
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

    # Preserve any comment/copyright header that precedes the dict literal.
    # dict_node.lineno is 1-based; slice is 0-based.
    source_lines = source.splitlines(keepends=True)
    prefix = "".join(source_lines[: dict_node.lineno - 1])

    new_source = prefix + render_manifest(data)

    if new_source == source:
        return False

    if not dry_run:
        path.write_text(new_source, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# CLI (standalone use)
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """Entry point for standalone use."""
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
        "--dry-run", "-n",
        action="store_true",
        help="Print which files would change without modifying them",
    )
    parser.add_argument(
        "--exclude",
        metavar="DIR",
        action="append",
        default=["_vendor", "enterprise"],
        help="Directory names to skip (default: _vendor, enterprise); repeatable",
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
