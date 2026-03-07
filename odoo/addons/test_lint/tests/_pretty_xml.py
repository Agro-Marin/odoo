#!/usr/bin/env python3
"""Canonical XML formatter for Odoo data files.

Enforces the coding-guidelines XML style:

- 4-space indentation
- ``<?xml version="1.0" encoding="utf-8"?>`` declaration (double-quoted, no
  space before ``?>``)
- Blank line after ``<odoo>`` opening, between top-level elements, and before
  ``</odoo>`` closing
- Self-closing empty elements (``<field name="active"/>`` instead of
  ``<field name="active"></field>``)
- Double-quoted attribute values

**Opaque content** (arch fields, template bodies) is *re-indented* to the
correct depth but never re-formatted — its internal whitespace and mixed text
content are preserved verbatim.

Standalone usage::

    python _pretty_xml.py [DIR ...]            # rewrite in-place
    python _pretty_xml.py --dry-run [DIR ...]  # preview only

From the project root::

    ./venv/odoo/bin/python core/odoo/addons/test_lint/tests/_pretty_xml.py addons_custom core
"""

import argparse
import re
import sys
from io import BytesIO
from pathlib import Path

from lxml import etree

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PARSER = etree.XMLParser(remove_comments=False, strip_cdata=False)
_XML_DECL = b'<?xml version="1.0" encoding="utf-8"?>'

#: 4-space indent string.
_INDENT = "    "

#: Maximum line length — tags exceeding this are wrapped one-attribute-per-line.
_MAX_LINE = 88

#: Direct children of these container elements are separated by blank lines.
_BLANK_SEP_CONTAINERS: frozenset[str] = frozenset({"odoo", "openerp"})

#: Elements whose inner content is opaque (re-indented but not reformatted).
#: Field elements with ``type="xml"`` or ``name="arch"`` are handled separately
#: by :func:`_is_opaque_field`.
_OPAQUE_TAGS: frozenset[str] = frozenset({"template"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_opaque_field(elem: etree._Element) -> bool:
    """Return ``True`` if this ``<field>`` element contains opaque inner content."""
    return elem.tag == "field" and (
        elem.get("name") == "arch"
        or elem.get("type") in ("xml", "html")
    )


def _esc_attr(value: str) -> str:
    """Escape a string for use inside double-quoted XML attribute values."""
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _esc_text(value: str) -> str:
    """Escape a string for use as XML text content."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Matches '/>' not already preceded by a space — used to normalise lxml output.
_SELF_CLOSE_RE = re.compile(r"(?<! )/>")


def _normalize_self_close(s: str) -> str:
    """Replace every ``/>`` not already preceded by a space with `` />``."""
    return _SELF_CLOSE_RE.sub(" />", s)


def _orig_depth_from_text(text: str | None) -> int:
    """Return the number of leading spaces before the first content line.

    Given the ``.text`` property of an element (e.g. ``"\\n    "`` before an
    arch child), returns the indentation depth of the inner content.
    """
    if not text:
        return 0
    parts = text.split("\n")
    return len(parts[-1]) if len(parts) > 1 else 0


def _convert_arch_indent(content: str, orig_base: int, new_base: int) -> str:
    """Convert arch content from its original indentation step to 2-space.

    The *orig_base* is the absolute number of leading spaces before the arch
    root element (e.g. ``<form>``); *new_base* is the target.  The original
    indentation step size (typically 4) is auto-detected from the content.

    Algorithm:
    - Detect *step* = smallest indentation above *orig_base*.
    - For each line: ``level = (spaces - orig_base) // step``.
    - New spaces: ``new_base + level * 2``.

    This converts 4-space-per-level arch content to 2-space while adjusting
    the absolute position to the correct depth in the formatted file.
    """
    if orig_base == new_base:
        # Fast path: no base shift needed.  Still convert internal step if needed.
        pass

    lines = content.split("\n")

    # Detect original step size: minimum indentation above orig_base.
    above = sorted(
        len(line) - len(line.lstrip(" "))
        for line in lines
        if line.strip() and (len(line) - len(line.lstrip(" "))) > orig_base
    )
    if above:
        step = above[0] - orig_base
    else:
        # No children — plain shift suffices.
        step = 0

    result: list[str] = []
    for line in lines:
        if not line.strip():
            result.append("")
            continue
        spaces = len(line) - len(line.lstrip(" "))
        if step > 0:
            rel = spaces - orig_base
            level, remainder = divmod(rel, step)
            new_spaces = new_base + level * len(_INDENT) + remainder
        else:
            # Flat content: just shift.
            new_spaces = new_base + (spaces - orig_base)
        result.append(" " * max(0, new_spaces) + line.lstrip(" "))
    return "\n".join(result)


def _inner_content(elem: etree._Element) -> str:
    """Return the raw inner content of *elem* (between its opening and closing tags).

    Uses lxml's serialisation (``pretty_print=False``, ``with_tail=False``) which
    preserves the original ``.text`` / ``.tail`` whitespace stored during parsing
    — safe for mixed-text content.  ``with_tail=False`` prevents the element's
    own ``.tail`` (sibling-separator whitespace) from being included and
    corrupting the slice.
    """
    s = etree.tostring(elem, pretty_print=False, encoding="unicode", with_tail=False)
    # Find the end of the opening tag.  Attribute values are escaped by lxml
    # (&amp;, &quot;, &lt;), so the first bare '>' is always the tag end.
    start = s.index(">") + 1
    # Remove the closing tag from the end.
    end = len(s) - len(f"</{elem.tag}>")
    return s[start:end]


def _open_tag_lines(tag: str, attrib: dict, pad: str, suffix: str) -> list[str]:
    """Return lines for a tag opening (or self-closing tag).

    *suffix* is appended after the last attribute (or after the tag name when
    there are no attributes).  Typical values: ``">"``, ``" />"``,
    ``">text</tag>"``.

    If the single-line form fits within ``_MAX_LINE`` characters, one line is
    returned.  Otherwise each attribute is placed on its own line indented by
    one extra level, with *suffix* on the last attribute line.
    """
    attr_parts = [f'{k}="{_esc_attr(v)}"' for k, v in attrib.items()]
    if attr_parts:
        single = f"{pad}<{tag} {' '.join(attr_parts)}{suffix}"
    else:
        single = f"{pad}<{tag}{suffix}"
    if len(single) <= _MAX_LINE:
        return [single]
    # Multi-line: one attribute per line, suffix appended to the last.
    attr_pad = pad + _INDENT
    lines = [f"{pad}<{tag}"]
    for i, part in enumerate(attr_parts):
        end = suffix if i == len(attr_parts) - 1 else ""
        lines.append(f"{attr_pad}{part}{end}")
    return lines


# ---------------------------------------------------------------------------
# Per-element formatters
# ---------------------------------------------------------------------------


def _format_comment(node: etree._Comment, depth: int) -> list[str]:
    """Format a comment node, re-indenting multi-line comments.

    lxml stores a multi-line comment ``<!-- \\n content \\n indent -->`` as
    ``node.text = "\\n content \\n indent"``.  The leading ``\\n`` (separator
    between ``<!--`` and the first content line) and the trailing
    whitespace-only chunk (indentation before ``-->``) are artefacts of the
    serialised form, not real content.  Stripping them prevents an extra blank
    line from accumulating on every formatting pass.
    """
    pad = _INDENT * depth
    text = node.text or ""
    lines = text.split("\n")
    if len(lines) == 1:
        return [f"{pad}<!--{text}-->"]
    # Strip the leading empty string from the '\n' after <!--
    if lines and lines[0] == "":
        lines = lines[1:]
    # Strip the trailing whitespace-only element (indent before -->)
    if lines and not lines[-1].strip():
        lines = lines[:-1]
    # Re-indent each content line to depth+1; preserve blank lines as-is.
    inner_lines = [
        f"{_INDENT * (depth + 1)}{line.strip()}" if line.strip() else ""
        for line in lines
    ]
    return [f"{pad}<!--"] + inner_lines + [f"{pad}-->"]


def _format_opaque(elem: etree._Element, depth: int) -> list[str]:
    """Format an opaque element (arch field, template) at *depth*.

    For elements whose ``.text`` is purely whitespace (the common case: view
    XML, QWeb templates with structured content), the inner content is
    re-indented to the correct absolute depth while preserving relative
    indentation and internal structure.

    For elements with *mixed* text content (e.g. ``web.layout`` whose body
    begins directly with ``<!DOCTYPE html>``), the inner content is preserved
    completely verbatim — re-indentation would corrupt inline text.  Only the
    opening/closing tags are formatted.
    """
    pad = _INDENT * depth

    # Empty opaque element (no children, no text).
    if len(elem) == 0 and not (elem.text and elem.text.strip()):
        return _open_tag_lines(elem.tag, elem.attrib, pad, " />")

    # Collect inner content via lxml's text/tail serialisation (with_tail=False
    # excludes the element's own sibling-separator whitespace).
    inner = _inner_content(elem)

    # If .text has actual (non-whitespace) content the element has mixed
    # text/element content — preserve verbatim to avoid corrupting inline text.
    if elem.text and elem.text.strip():
        inner_lines = inner.split("\n")
        # Strip leading/trailing whitespace-only lines so the '\n' inserted by
        # "\n".join() between the opening tag and first inner line does not
        # accumulate into an extra blank line on each formatting pass.
        while inner_lines and not inner_lines[0].strip():
            inner_lines.pop(0)
        while inner_lines and not inner_lines[-1].strip():
            inner_lines.pop()
        if not inner_lines:
            return _open_tag_lines(elem.tag, elem.attrib, pad, " />")
        inner_lines = [_normalize_self_close(line) for line in inner_lines]
        return (
            _open_tag_lines(elem.tag, elem.attrib, pad, ">")
            + inner_lines
            + [f"{pad}</{elem.tag}>"]
        )

    # Pure-structural content: re-indent to the target depth.
    orig_depth = _orig_depth_from_text(elem.text)
    target_depth = (depth + 1) * len(_INDENT)

    shifted = _convert_arch_indent(inner, orig_depth, target_depth)

    # Strip the leading newline produced by "\n    " field.text patterns
    # and any trailing whitespace-only lines.
    shifted_lines = shifted.split("\n")
    if shifted_lines and not shifted_lines[0].strip():
        shifted_lines = shifted_lines[1:]
    while shifted_lines and not shifted_lines[-1].strip():
        shifted_lines.pop()

    if not shifted_lines:
        return _open_tag_lines(elem.tag, elem.attrib, pad, " />")

    # Normalise lxml-serialised self-closing tags inside arch/template content.
    shifted_lines = [_normalize_self_close(line) for line in shifted_lines]

    return (
        _open_tag_lines(elem.tag, elem.attrib, pad, ">")
        + shifted_lines
        + [f"{pad}</{elem.tag}>"]
    )


def _format_element(elem: etree._Element, depth: int) -> list[str]:
    """Format a single element and its descendants.

    Returns a list of lines (no trailing newline on each).

    - Opaque elements (arch fields, templates) delegate to :func:`_format_opaque`.
    - Container elements (``<odoo>``, ``<data>``) use blank-line-separated
      children via :func:`_format_children`.
    - Elements with children: multi-line.
    - Text-only elements: single line.
    - Empty elements: self-closing.
    """
    if callable(elem.tag):  # lxml Comment / PI node
        return _format_comment(elem, depth)

    if _is_opaque_field(elem) or elem.tag in _OPAQUE_TAGS:
        return _format_opaque(elem, depth)

    pad = _INDENT * depth
    text = (elem.text or "").strip()
    children = list(elem)

    if elem.tag in _BLANK_SEP_CONTAINERS:
        # Container: children separated by blank lines, wrapped with blank lines.
        inner = _format_children(children, depth + 1, blank_sep=True)
        lines = _open_tag_lines(elem.tag, elem.attrib, pad, ">")
        lines.append("")
        lines.extend(inner)
        lines.extend(["", f"{pad}</{elem.tag}>"])
        return lines

    if not children and not text:
        return _open_tag_lines(elem.tag, elem.attrib, pad, " />")

    if not children:
        return _open_tag_lines(
            elem.tag, elem.attrib, pad, f">{_esc_text(text)}</{elem.tag}>"
        )

    # Has children — multi-line, no blank lines between them.
    lines = _open_tag_lines(elem.tag, elem.attrib, pad, ">")
    for child in children:
        lines.extend(_format_element(child, depth + 1))
    lines.append(f"{pad}</{elem.tag}>")
    return lines


# ---------------------------------------------------------------------------
# Child grouping (comments attached to the element they precede)
# ---------------------------------------------------------------------------


def _group_children(
    children: list[etree._Element],
) -> list[list[etree._Element]]:
    """Group children into logical units for blank-line insertion.

    All consecutive comment nodes immediately preceding a non-comment element
    are bundled with that element.  Trailing comment-only runs form their own
    group.
    """
    groups: list[list[etree._Element]] = []
    i = 0
    while i < len(children):
        group: list[etree._Element] = []
        # Collect leading comments.
        while i < len(children) and callable(children[i].tag):
            group.append(children[i])
            i += 1
        # Then one non-comment element (if any).
        if i < len(children):
            group.append(children[i])
            i += 1
        groups.append(group)
    return groups


def _format_children(
    children: list[etree._Element],
    depth: int,
    *,
    blank_sep: bool = False,
) -> list[str]:
    """Format *children* at *depth*, optionally inserting blank lines between groups."""
    if not blank_sep:
        lines: list[str] = []
        for child in children:
            lines.extend(_format_element(child, depth))
        return lines

    groups = _group_children(children)
    lines = []
    for gi, group in enumerate(groups):
        for elem in group:
            lines.extend(_format_element(elem, depth))
        if gi < len(groups) - 1:
            lines.append("")
    return lines


# ---------------------------------------------------------------------------
# File-level formatting
# ---------------------------------------------------------------------------


def format_xml_file(
    path: Path,
    *,
    dry_run: bool = False,
) -> bool | None:
    """Format an Odoo XML data file with canonical 2-space indentation.

    Processing rules:

    - XML declaration normalised to ``<?xml version="1.0" encoding="utf-8"?>``.
    - Root element (``<odoo>``) formatted with blank lines around and between
      its direct children.
    - All data-layer elements use 4-space indentation.
    - Arch fields and ``<template>`` inner content are re-indented but
      otherwise preserved verbatim.
    - Pre-root comment nodes (copyright headers) are preserved.

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
    had_decl = source.lstrip().startswith(b"<?xml")

    # ── Collect pre-root comment nodes (copyright headers, etc.) ────────────
    pre_root: list[str] = []
    node = root.getprevious()
    while node is not None:
        if callable(node.tag):
            pre_root.insert(0, etree.tostring(node, encoding="unicode"))
        node = node.getprevious()

    # ── Build output ─────────────────────────────────────────────────────────
    out: list[str] = []
    if had_decl:
        out.append('<?xml version="1.0" encoding="utf-8"?>')
    out.extend(pre_root)

    # The root element is formatted by _format_element (which handles
    # _BLANK_SEP_CONTAINERS internally for <odoo>/<openerp>).
    out.extend(_format_element(root, depth=0))

    new_content = "\n".join(out) + "\n"
    new_bytes = new_content.encode("utf-8")

    if new_bytes == source:
        return False

    if not dry_run:
        path.write_bytes(new_bytes)

    return True


# ---------------------------------------------------------------------------
# CLI (standalone use)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Entry point for standalone use."""
    parser = argparse.ArgumentParser(
        description=(
            "Format Odoo XML data files with canonical 2-space indentation."
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
    excluded: set[str] = set(args.exclude)
    changed = unchanged = skipped = 0

    for root_str in args.roots:
        for xml_file in sorted(Path(root_str).rglob("*.xml")):
            if excluded.intersection(xml_file.parts):
                continue
            result = format_xml_file(xml_file, dry_run=args.dry_run)
            if result is None:
                skipped += 1
            elif result:
                label = "would format" if args.dry_run else "formatted  "
                print(f"  {label}  {xml_file}")
                changed += 1
            else:
                unchanged += 1

    verb = "would change" if args.dry_run else "formatted"
    print(f"\nDone: {changed} {verb}, {unchanged} unchanged, {skipped} skipped")


if __name__ == "__main__":
    main()
