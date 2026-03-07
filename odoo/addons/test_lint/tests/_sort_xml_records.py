#!/usr/bin/env python3
"""XML record field and element-attribute sorter for Odoo data files.

Two canonical orderings are enforced:

1. **Field order** — ``<field>`` children within ``<record>`` elements are
   sorted to the canonical order defined in :data:`FIELD_ORDER`.

2. **Attribute order** — attributes on data-layer elements (``<record>``,
   ``<field>`` inside records, ``<menuitem>``, ``<template>``, ``<delete>``,
   ``<function>``) are sorted to the canonical order in :data:`ATTRIB_ORDER`.
   Elements inside ``<arch>`` / QWeb template bodies are **not** touched.

Standalone usage::

    python _sort_xml_records.py [DIR ...]            # rewrite in-place
    python _sort_xml_records.py --dry-run [DIR ...]  # preview only

From the project root::

    ./venv/odoo/bin/python core/odoo/addons/test_lint/tests/_sort_xml_records.py addons_custom core
"""

import argparse
import sys
from io import BytesIO
from pathlib import Path

from lxml import etree

# ---------------------------------------------------------------------------
# Canonical <field> child ordering per record model
# ---------------------------------------------------------------------------

#: Maps Odoo model names to their canonical ``<field>`` child ordering.
#: Known fields appear in this order; unknown fields are appended alphabetically.
FIELD_ORDER: dict[str, list[str]] = {
    # Views ──────────────────────────────────────────────────────────────────
    "ir.ui.view": [
        "name",          # view identifier string (e.g. "sale.order.form")
        "model",         # target model
        "inherit_id",    # parent view (when inheriting)
        "mode",          # "primary" / "extension"
        "priority",      # numeric resolution priority
        "groups_id",     # access groups
        "active",        # whether the view is enabled
        "arch",          # view XML architecture — MUST be last
    ],
    # Window actions ─────────────────────────────────────────────────────────
    "ir.actions.act_window": [
        "name",
        "res_model",
        "path",              # URL slug
        "view_mode",         # "list,form" etc.
        "view_id",           # default view override
        "search_view_id",
        "target",            # "current" / "new" / "inline" / "fullscreen"
        "domain",
        "context",
        "filter",
        "limit",
        "mobile_view_filter",
        "binding_model_id",  # smart-button / action binding
        "binding_view_types",
        "help",              # empty-state HTML — last (often multiline)
    ],
    # Window action / view linking table ─────────────────────────────────────
    "ir.actions.act_window.view": [
        "sequence",
        "view_mode",
        "view_id",
        "act_window_id",
    ],
    # Server actions ─────────────────────────────────────────────────────────
    "ir.actions.server": [
        "name",
        "model_id",
        "binding_model_id",
        "binding_view_types",
        "groups_id",
        "state",         # "code" / "object_create" / "object_write" / "multi"
        "child_ids",     # sub-actions for "multi" state
        "code",          # Python code — last when present (often multiline)
    ],
    # Reports ────────────────────────────────────────────────────────────────
    "ir.actions.report": [
        "name",
        "model",
        "report_type",
        "report_name",
        "report_file",
        "print_wizard",
        "multi",
        "paperformat_id",
        "attachment",
        "attachment_use",
        "binding_model_id",
        "binding_type",
        "groups_id",
    ],
    # Client actions ─────────────────────────────────────────────────────────
    "ir.actions.client": [
        "name",
        "res_model",
        "tag",
        "target",
        "context",
        "params",
    ],
}

# ---------------------------------------------------------------------------
# Canonical attribute ordering per element tag
# ---------------------------------------------------------------------------

#: Maps XML element tag names to their canonical attribute ordering.
#: Only data-layer elements are listed; view-arch elements are never touched.
#: Unknown attributes are appended alphabetically after the known ones.
ATTRIB_ORDER: dict[str, list[str]] = {
    # <record id="..." model="...">
    "record": [
        "id",
        "model",
    ],
    # <field name="..." eval/ref/type/file>  (data-layer only; inside <record>)
    # eval and ref specify HOW the value is set; type specifies the encoding.
    "field": [
        "name",
        "eval",
        "ref",
        "type",
        "file",
    ],
    # <menuitem id="..." name="..." parent="..." action="..." sequence="..." ...>
    "menuitem": [
        "id",
        "name",
        "parent",
        "action",
        "sequence",
        "groups",
        "web_icon",
        "active",
    ],
    # <template id="..." name="..." inherit_id="..." ...>
    "template": [
        "id",
        "name",
        "inherit_id",
        "mode",
        "priority",
        "groups",
        "active",
    ],
    # <delete id="..." model="..." search="...">
    "delete": [
        "id",
        "model",
        "search",
    ],
    # <function model="..." name="..." eval="...">
    "function": [
        "model",
        "name",
        "eval",
        "context",
    ],
}

# XML declaration written to rewritten files.
_XML_DECL = b'<?xml version="1.0" encoding="utf-8"?>'

_PARSER = etree.XMLParser(remove_comments=False, strip_cdata=False)

# Tags whose elements are processed for attribute ordering at any nesting depth.
# <field> is excluded here because it is handled separately (only inside <record>).
_TOP_LEVEL_TAGS = frozenset(ATTRIB_ORDER) - {"record", "field"}


# ---------------------------------------------------------------------------
# Public ordering helpers
# ---------------------------------------------------------------------------

def expected_field_order(present_fields: list[str], model: str) -> list[str]:
    """Return canonical ``<field>`` child ordering for *present_fields* given *model*.

    Known fields appear in the position defined by ``FIELD_ORDER[model]``.
    Unknown fields are appended alphabetically. If *model* is not in
    ``FIELD_ORDER``, the original order is returned unchanged.
    """
    canonical = FIELD_ORDER.get(model)
    if canonical is None:
        return present_fields
    known = [k for k in canonical if k in present_fields]
    unknown = sorted(k for k in present_fields if k not in set(canonical))
    return known + unknown


def expected_attrib_order(tag: str, present_attribs: list[str]) -> list[str]:
    """Return canonical attribute ordering for *tag* given *present_attribs*.

    Known attributes appear in the position defined by ``ATTRIB_ORDER[tag]``.
    Unknown attributes are appended alphabetically. If *tag* is not in
    ``ATTRIB_ORDER``, the original order is returned unchanged.
    """
    canonical = ATTRIB_ORDER.get(tag)
    if canonical is None:
        return present_attribs
    known = [k for k in canonical if k in present_attribs]
    unknown = sorted(k for k in present_attribs if k not in set(canonical))
    return known + unknown


def expected_record_attrib_order(present_attribs: list[str]) -> list[str]:
    """Convenience alias: canonical ``<record>`` attribute ordering."""
    return expected_attrib_order("record", present_attribs)


# ---------------------------------------------------------------------------
# XML manipulation helpers
# ---------------------------------------------------------------------------

def _normalize_attribs(element: etree._Element) -> bool:
    """Normalize *element*'s attribute order per :data:`ATTRIB_ORDER`.

    Returns ``True`` if the order changed.
    """
    tag = element.tag
    if callable(tag):  # lxml comment / PI nodes
        return False
    attribs = dict(element.attrib)
    current = list(attribs.keys())
    canonical = expected_attrib_order(tag, current)
    if current == canonical:
        return False
    element.attrib.clear()
    for k in canonical:
        element.set(k, attribs[k])
    return True


def _sort_record_fields(record: etree._Element, model: str) -> bool:
    """Reorder ``<field>`` children of *record* to canonical order.

    Records containing comment/PI nodes between their fields are skipped to
    avoid disrupting intentional grouping comments.

    The ``.tail`` whitespace (indentation between closing tags) is preserved
    by mapping original positional tails to the new positions — since all
    non-last tails share the same indent string, each slot keeps the spacing
    of its position in the result, not the spacing that came with the element.

    Returns ``True`` if the record was modified.
    """
    children = list(record)

    # Skip records that contain comment or PI nodes (callable .tag in lxml).
    if any(callable(c.tag) for c in children):
        return False

    fields = [c for c in children if c.tag == "field"]
    if len(fields) <= 1:
        return False

    actual_names = [f.get("name") for f in fields]
    expected_names = expected_field_order(actual_names, model)

    if actual_names == expected_names:
        return False

    # Save per-position tails before removal.
    # The N-th tail in the original order belongs to the N-th slot in the
    # new order (all non-last tails are identical indent; only the last differs).
    original_tails = [f.tail for f in fields]

    # Build name → element map (first occurrence wins for any duplicates).
    field_map: dict[str, etree._Element] = {}
    for f in fields:
        name = f.get("name")
        if name is not None and name not in field_map:
            field_map[name] = f

    for f in fields:
        record.remove(f)

    ordered = [field_map[n] for n in expected_names if n in field_map]
    for i, f in enumerate(ordered):
        f.tail = original_tails[i]
        record.append(f)

    return True


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

def sort_xml_file(
    path: Path,
    *,
    models: set[str] | None = None,
    dry_run: bool = False,
) -> bool | None:
    """Sort ``<record>`` fields and normalize element attributes in *path*.

    Processing scope:

    - ``<record>`` attribute order (id → model → rest).
    - ``<field>`` child order within each ``<record>`` (per :data:`FIELD_ORDER`).
    - ``<field>`` attribute order for data-layer fields (direct children of records).
    - Attribute order for ``<menuitem>``, ``<template>``, ``<delete>``, ``<function>``.

    Elements inside ``<arch>`` / QWeb template bodies are never modified.

    Returns:
        ``True``  — file was changed (or would change in dry-run mode)
        ``False`` — file already canonical; no change made
        ``None``  — file was skipped due to a parse error (warning on stderr)
    """
    source = path.read_bytes()
    try:
        tree = etree.parse(BytesIO(source), _PARSER)
    except etree.XMLSyntaxError as exc:
        print(f"  SKIP  {path}: {exc}", file=sys.stderr)
        return None

    root = tree.getroot()
    was_modified = False

    # ── Records: field order + record/field attribute order ─────────────────
    for record in root.iter("record"):
        model = record.get("model")
        if model is None:
            continue
        if models is not None and model not in models:
            continue

        if _normalize_attribs(record):
            was_modified = True

        # Normalize data-layer <field> attributes (direct children only;
        # arch content is never recursed into).
        for field in record:
            if not callable(field.tag) and field.tag == "field":
                if _normalize_attribs(field):
                    was_modified = True

        if model in FIELD_ORDER and _sort_record_fields(record, model):
            was_modified = True

    # ── Top-level shorthand elements: menuitem, template, delete, function ──
    for tag in _TOP_LEVEL_TAGS:
        for elem in root.iter(tag):
            if _normalize_attribs(elem):
                was_modified = True

    if not was_modified:
        return False

    if not dry_run:
        buf = BytesIO()
        # pretty_print=False preserves original text/tail whitespace.
        tree.write(buf, xml_declaration=False, encoding="utf-8", pretty_print=False)
        body = buf.getvalue()

        # Prepend a clean double-quoted XML declaration when the original had one.
        had_decl = source.lstrip().startswith(b"<?xml")
        new_content = (_XML_DECL + b"\n" + body) if had_decl else body

        # Preserve original trailing newline.
        if source.endswith(b"\n") and not new_content.endswith(b"\n"):
            new_content += b"\n"

        path.write_bytes(new_content)

    return True


# ---------------------------------------------------------------------------
# CLI (standalone use)
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """Entry point for standalone use."""
    parser = argparse.ArgumentParser(
        description=(
            "Sort Odoo XML <record> <field> children and normalize element "
            "attribute order."
        ),
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
        "--model",
        metavar="MODEL",
        action="append",
        dest="models",
        help=(
            "Only process records of this model (repeatable); "
            "default: all known models"
        ),
    )
    parser.add_argument(
        "--exclude",
        metavar="DIR",
        action="append",
        default=["_vendor", "enterprise", "static"],
        help=(
            "Directory names to skip "
            "(default: _vendor, enterprise, static); repeatable"
        ),
    )
    args = parser.parse_args(argv)

    model_filter: set[str] | None = set(args.models) if args.models else None
    excluded: set[str] = set(args.exclude)
    changed = unchanged = skipped = 0

    for root_str in args.roots:
        for xml_file in sorted(Path(root_str).rglob("*.xml")):
            if excluded.intersection(xml_file.parts):
                continue
            result = sort_xml_file(xml_file, models=model_filter, dry_run=args.dry_run)
            if result is None:
                skipped += 1
            elif result:
                label = "would sort" if args.dry_run else "sorted   "
                print(f"  {label}  {xml_file}")
                changed += 1
            else:
                unchanged += 1

    verb = "would change" if args.dry_run else "sorted"
    print(f"\nDone: {changed} {verb}, {unchanged} unchanged, {skipped} skipped")


if __name__ == "__main__":
    main()
