import argparse
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path

from lxml import etree

FIELD_ORDER: dict[str, list[str]] = {
    "ir.ui.view": [
        "name",
        "model",
        "inherit_id",
        "mode",
        "priority",
        "groups_id",
        "active",
        "arch",
    ],
    "ir.actions.act_window": [
        "name",
        "res_model",
        "path",
        "view_mode",
        "view_id",
        "search_view_id",
        "target",
        "domain",
        "context",
        "filter",
        "limit",
        "mobile_view_filter",
        "binding_model_id",
        "binding_view_types",
        "help",
    ],
    "ir.actions.act_window.view": [
        "sequence",
        "view_mode",
        "view_id",
        "act_window_id",
    ],
    "ir.actions.server": [
        "name",
        "model_id",
        "binding_model_id",
        "binding_view_types",
        "groups_id",
        "state",
        "child_ids",
        "code",
    ],
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
    "ir.actions.client": [
        "name",
        "res_model",
        "tag",
        "target",
        "context",
        "params",
    ],
}


ATTRIB_ORDER: dict[str, list[str]] = {
    "record": [
        "id",
        "model",
    ],
    "field": [
        "name",
        "eval",
        "ref",
        "type",
        "file",
    ],
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
    "template": [
        "id",
        "name",
        "inherit_id",
        "mode",
        "priority",
        "groups",
        "active",
    ],
    "delete": [
        "id",
        "model",
        "search",
    ],
    "function": [
        "model",
        "name",
        "eval",
        "context",
    ],
}

_XML_DECL = b'<?xml version="1.0" encoding="utf-8"?>'

_PARSER = etree.XMLParser(remove_comments=False, strip_cdata=False)

_TOP_LEVEL_TAGS = frozenset(ATTRIB_ORDER) - {"record", "field"}


def expected_field_order(present_fields: list[str], model: str) -> list[str]:
    """Return canonical ``<field>`` child ordering for *present_fields* given *model*.

    Known fields appear in the position defined by ``FIELD_ORDER[model]``.
    Unknown fields are appended alphabetically. If *model* is not in
    ``FIELD_ORDER``, the original order is returned unchanged.

    A name present twice comes back twice. ``[k for k in canonical if k in
    present]`` silently collapsed it to one, which made the expected order
    *shorter* than the actual one -- and the sorter, rebuilding the record from
    that list, dropped the extra element. It is also what made the lint test
    report the record as out of order in the first place: a list of six names
    cannot equal a list of five, so the record could never be made to pass.
    """
    canonical = FIELD_ORDER.get(model)
    if canonical is None:
        return present_fields
    counts = Counter(present_fields)
    known = [name for name in canonical for _ in range(counts[name])]
    unknown = sorted(name for name in present_fields if name not in set(canonical))
    return known + unknown


def expected_attrib_order(tag: str, present_attribs: list[str]) -> list[str]:
    canonical = ATTRIB_ORDER.get(tag)
    if canonical is None:
        return present_attribs
    known = [k for k in canonical if k in present_attribs]
    unknown = sorted(k for k in present_attribs if k not in set(canonical))
    return known + unknown


def _normalize_attribs(element: etree._Element) -> bool:
    tag = element.tag
    if callable(tag):
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
    avoid disrupting intentional grouping comments. So are records carrying a
    child that is not a ``<field>``: the reordering appends every field after
    whatever else is there, which moves that element rather than leaving it
    alone. Nothing in any of the four checkouts is shaped that way today, and
    a fixer that rewrites the whole tree should not be the thing that finds out
    what happens when something is.

    Every field element is kept, duplicate names included. The previous version
    reordered through a ``{name: element}`` map, which holds one element per
    name -- so a record naming the same field twice came back with one of them
    **deleted**. ``hr_holidays``' ``hr_leave_view_kanban_my`` declares ``mode``
    twice and went from six fields to five on a single run of this script, the
    one the lint gate prints as its remediation.

    The ``.tail`` whitespace (indentation between closing tags) is preserved
    by mapping original positional tails to the new positions — since all
    non-last tails share the same indent string, each slot keeps the spacing
    of its position in the result, not the spacing that came with the element.
    That is only true while the count is unchanged, which is now guaranteed.

    Returns ``True`` if the record was modified.
    """
    children = list(record)

    if any(callable(c.tag) for c in children):
        return False

    fields = [c for c in children if c.tag == "field"]
    if len(fields) <= 1 or len(fields) != len(children):
        return False

    actual_names = [f.get("name") for f in fields]
    expected_names = expected_field_order(actual_names, model)

    if actual_names == expected_names:
        return False

    original_tails = [f.tail for f in fields]

    # One queue per name, so repeated names keep every element and stay in
    # their original relative order.
    queues: dict[str | None, list[etree._Element]] = {}
    for field in fields:
        queues.setdefault(field.get("name"), []).append(field)

    ordered = [queues[name].pop(0) for name in expected_names]
    if len(ordered) != len(fields):  # a name `expected_field_order` invented
        return False

    for field in fields:
        record.remove(field)
    for index, field in enumerate(ordered):
        field.tail = original_tails[index]
        record.append(field)

    return True


def sort_xml_file(
    path: Path,
    *,
    models: set[str] | None = None,
    dry_run: bool = False,
) -> bool | None:
    source = path.read_bytes()
    try:
        tree = etree.parse(BytesIO(source), _PARSER)
    except etree.XMLSyntaxError as exc:
        print(f"  SKIP  {path}: {exc}", file=sys.stderr)
        return None

    root = tree.getroot()
    was_modified = False

    for record in root.iter("record"):
        model = record.get("model")
        if model is None:
            continue
        if models is not None and model not in models:
            continue

        if _normalize_attribs(record):
            was_modified = True

        for field in record:
            if not callable(field.tag) and field.tag == "field":
                if _normalize_attribs(field):
                    was_modified = True

        if model in FIELD_ORDER and _sort_record_fields(record, model):
            was_modified = True

    for tag in _TOP_LEVEL_TAGS:
        for elem in root.iter(tag):
            if _normalize_attribs(elem):
                was_modified = True

    if not was_modified:
        return False

    if not dry_run:
        buf = BytesIO()
        tree.write(buf, xml_declaration=False, encoding="utf-8", pretty_print=False)
        body = buf.getvalue()

        had_decl = source.lstrip().startswith(b"<?xml")
        new_content = (_XML_DECL + b"\n" + body) if had_decl else body

        if source.endswith(b"\n") and not new_content.endswith(b"\n"):
            new_content += b"\n"

        path.write_bytes(new_content)

    return True


def main(argv: list[str] | None = None) -> None:
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
        "--dry-run",
        "-n",
        action="store_true",
        help="Print which files would change without modifying them",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        action="append",
        dest="models",
        help=(
            "Only process records of this model (repeatable); default: all known models"
        ),
    )
    parser.add_argument(
        "--exclude",
        metavar="DIR",
        action="append",
        default=["_vendor", "enterprise", "static"],
        help=(
            "Directory names to skip (default: _vendor, enterprise, static); repeatable"
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
