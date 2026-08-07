import argparse
import re
import sys
from io import BytesIO
from pathlib import Path

from lxml import etree

_PARSER = etree.XMLParser(remove_comments=False, strip_cdata=False)
_XML_DECL = b'<?xml version="1.0" encoding="utf-8"?>'

_INDENT = "    "

_MAX_LINE = 88

_BLANK_SEP_CONTAINERS: frozenset[str] = frozenset({"odoo", "openerp"})

_OPAQUE_TAGS: frozenset[str] = frozenset({"template"})

#: Directory names this formatter must not enter.
#:
#: ``static`` holds OWL component templates, not data files. They are full of
#: mixed content (``<span><t t-out="n"/> are not shown in the preview</span>``)
#: and none of the data-layer conventions here -- record field order, blank
#: lines between top-level elements -- mean anything in one. The CLI has always
#: skipped them; the lint test did not, and flagged 2 634 files the documented
#: fixer then refused to touch. Stating the set once is what keeps the two
#: honest: see :func:`is_formattable`.
EXCLUDED_DIRS: frozenset[str] = frozenset({"_vendor", "static", "node_modules"})


def is_formattable(path: Path) -> bool:
    """Whether *path* is a data file this formatter owns.

    The single answer used by both the CLI and the lint test, so a file can
    never be reported as needing formatting by a tool that would decline to
    format it.
    """
    return not EXCLUDED_DIRS.intersection(path.parts)


def _is_opaque_field(elem: etree._Element) -> bool:
    return elem.tag == "field" and (
        elem.get("name") == "arch" or elem.get("type") in ("xml", "html")
    )


def _has_mixed_content(elem: etree._Element) -> bool:
    """Whether *elem* interleaves text with child elements.

    The data-layer formatter emits an open tag, its children, and a close tag.
    It never emitted ``elem.text`` or any child's ``.tail``, so text sitting
    between children was **deleted** -- silently, and only where an element had
    both. Every affected file happened to live under ``static/``, which the CLI
    excludes, so the loss was never observed; a single ``format_xml_file`` call
    on one of them is enough to lose the string.

    Rather than teach the data-layer path to reflow mixed content -- which is
    guesswork about where a line may be broken without changing what renders --
    such an element is handed to the opaque path, which re-indents and preserves
    it verbatim.
    """
    if not len(elem):
        return False
    if (elem.text or "").strip():
        return True
    return any((child.tail or "").strip() for child in elem)


def _esc_attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _esc_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_SELF_CLOSE_RE = re.compile(r"(?<! )/>")


def _normalize_self_close(s: str) -> str:
    return _SELF_CLOSE_RE.sub(" />", s)


def _orig_depth_from_text(text: str | None) -> int:
    if not text:
        return 0
    parts = text.split("\n")
    return len(parts[-1]) if len(parts) > 1 else 0


def _convert_arch_indent(content: str, orig_base: int, new_base: int) -> str:
    """Convert arch content from its original indentation step to 4-space.

    The *orig_base* is the absolute number of leading spaces before the arch
    root element (e.g. ``<form>``); *new_base* is the target.  The original
    indentation step size (typically 4) is auto-detected from the content.

    Algorithm:
    - Detect *step* = smallest indentation above *orig_base*.
    - For each line: ``level = (spaces - orig_base) // step``.
    - New spaces: ``new_base + level * len(_INDENT)``.

    This converts arch content to the canonical 4-space step while adjusting
    the absolute position to the correct depth in the formatted file.
    """
    lines = content.split("\n")

    above = sorted(
        _indent_width(line)
        for line in lines
        if line.strip() and _indent_width(line) > orig_base
    )
    step = above[0] - orig_base if above else 0

    result: list[str] = []
    for line in lines:
        if not line.strip():
            result.append("")
            continue
        spaces = _indent_width(line)
        if step > 0:
            rel = spaces - orig_base
            level, remainder = divmod(rel, step)
            new_spaces = new_base + level * len(_INDENT) + remainder
        else:
            new_spaces = new_base + (spaces - orig_base)
        result.append(" " * max(0, new_spaces) + line.lstrip(" \t"))
    return "\n".join(result)


def _indent_width(line: str) -> int:
    """Leading whitespace of *line*, counting a tab as one column.

    Measuring with ``lstrip(" ")`` alone made the formatter **oscillate** rather
    than converge: a tab-indented line reported an indent of zero, was re-emitted
    as spaces *plus the surviving tab*, and measured differently on the next
    pass. One real file (``website_profile``'s badge view) cycled 19 -> 9 -> 15
    -> 9 columns forever, so the lint test built on this could never go green on
    it however many times the fixer ran.

    Stripping tabs as well as spaces normalises leading whitespace to the
    canonical indent on the first pass, which is what a formatter is for.
    """
    return len(line) - len(line.lstrip(" \t"))


def _inner_content(elem: etree._Element) -> str:
    s = etree.tostring(elem, pretty_print=False, encoding="unicode", with_tail=False)
    start = s.index(">") + 1
    end = len(s) - len(f"</{elem.tag}>")
    return s[start:end]


def _open_tag_lines(tag: str, attrib: dict, pad: str, suffix: str) -> list[str]:
    attr_parts = [f'{k}="{_esc_attr(v)}"' for k, v in attrib.items()]
    if attr_parts:
        single = f"{pad}<{tag} {' '.join(attr_parts)}{suffix}"
    else:
        single = f"{pad}<{tag}{suffix}"
    if len(single) <= _MAX_LINE:
        return [single]
    attr_pad = pad + _INDENT
    lines = [f"{pad}<{tag}"]
    for i, part in enumerate(attr_parts):
        end = suffix if i == len(attr_parts) - 1 else ""
        lines.append(f"{attr_pad}{part}{end}")
    return lines


_SERIALIZED_ATTR_RE = re.compile(r'[\w:.\-]+\s*=\s*"[^"]*"')


def _is_lone_tag_line(stripped: str) -> bool:
    if not stripped.startswith("<"):
        return False
    if stripped.startswith(("</", "<!--", "<?", "<![")):
        return False
    return stripped.endswith(">") and stripped.count("<") == 1


def _wrap_serialized_tag(line: str) -> list[str]:
    if len(line) <= _MAX_LINE:
        return [line]
    stripped = line.lstrip(" ")
    if not _is_lone_tag_line(stripped):
        return [line]
    pad = line[: len(line) - len(stripped)]
    if stripped.endswith("/>"):
        suffix, body = " />", stripped[1:-2]
    else:
        suffix, body = ">", stripped[1:-1]
    match = re.match(r"([\w:.\-]+)\s*(.*)$", body.strip(), re.DOTALL)
    if not match:
        return [line]
    tag, attr_str = match.group(1), match.group(2)
    attrs = _SERIALIZED_ATTR_RE.findall(attr_str)
    if not attrs:
        return [line]
    rebuilt = f"<{tag} {' '.join(attrs)}{suffix}"
    if rebuilt.split() != stripped.split():
        return [line]
    attr_pad = pad + _INDENT
    out = [f"{pad}<{tag}"]
    for i, part in enumerate(attrs):
        end = suffix if i == len(attrs) - 1 else ""
        out.append(f"{attr_pad}{part}{end}")
    return out


def _wrap_opaque_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        out.extend(_wrap_serialized_tag(line))
    return out


def _format_comment(node: etree._Comment, depth: int) -> list[str]:
    pad = _INDENT * depth
    text = node.text or ""
    lines = text.split("\n")
    if len(lines) == 1:
        return [f"{pad}<!--{text}-->"]
    if lines and lines[0] == "":
        lines = lines[1:]
    if lines and not lines[-1].strip():
        lines = lines[:-1]
    inner_lines = [
        f"{_INDENT * (depth + 1)}{line.strip()}" if line.strip() else ""
        for line in lines
    ]
    return [f"{pad}<!--"] + inner_lines + [f"{pad}-->"]


def _format_opaque(elem: etree._Element, depth: int) -> list[str]:
    pad = _INDENT * depth

    if len(elem) == 0 and not (elem.text and elem.text.strip()):
        return _open_tag_lines(elem.tag, elem.attrib, pad, " />")

    inner = _inner_content(elem)

    if elem.text and elem.text.strip():
        inner_lines = inner.split("\n")
        while inner_lines and not inner_lines[0].strip():
            inner_lines.pop(0)
        while inner_lines and not inner_lines[-1].strip():
            inner_lines.pop()
        if not inner_lines:
            return _open_tag_lines(elem.tag, elem.attrib, pad, " />")
        inner_lines = _wrap_opaque_lines(
            [_normalize_self_close(line) for line in inner_lines]
        )
        return (
            _open_tag_lines(elem.tag, elem.attrib, pad, ">")
            + inner_lines
            + [f"{pad}</{elem.tag}>"]
        )

    orig_depth = _orig_depth_from_text(elem.text)
    target_depth = (depth + 1) * len(_INDENT)

    shifted = _convert_arch_indent(inner, orig_depth, target_depth)

    shifted_lines = shifted.split("\n")
    if shifted_lines and not shifted_lines[0].strip():
        shifted_lines = shifted_lines[1:]
    while shifted_lines and not shifted_lines[-1].strip():
        shifted_lines.pop()

    if not shifted_lines:
        return _open_tag_lines(elem.tag, elem.attrib, pad, " />")

    shifted_lines = _wrap_opaque_lines(
        [_normalize_self_close(line) for line in shifted_lines]
    )

    return (
        _open_tag_lines(elem.tag, elem.attrib, pad, ">")
        + shifted_lines
        + [f"{pad}</{elem.tag}>"]
    )


def _format_mixed(elem: etree._Element, depth: int) -> list[str]:
    """Format an element that interleaves text with children, byte for byte.

    Only the opening and closing tags are positioned; the inner content is
    emitted exactly as parsed. Re-indenting it is not safe here the way it is
    for an arch field: in mixed content a newline *is* a space, so moving the
    text onto its own line inserts whitespace between an inline element and the
    words around it -- ``<span>a</span> <span>b</span>`` and the same pair split
    across lines do not render alike.

    Not reflowed to :data:`_MAX_LINE` either, for the same reason: there is no
    line break available that is guaranteed not to change the rendering.
    """
    pad = _INDENT * depth
    lines = _open_tag_lines(elem.tag, elem.attrib, pad, ">")
    lines[-1] += f"{_inner_content(elem)}</{elem.tag}>"
    return lines


def _format_element(elem: etree._Element, depth: int) -> list[str]:
    if callable(elem.tag):
        return _format_comment(elem, depth)

    if _is_opaque_field(elem) or elem.tag in _OPAQUE_TAGS:
        return _format_opaque(elem, depth)

    if _has_mixed_content(elem):
        return _format_mixed(elem, depth)

    pad = _INDENT * depth
    text = (elem.text or "").strip()
    children = list(elem)

    if elem.tag in _BLANK_SEP_CONTAINERS:
        inner = _format_children(children, depth + 1, blank_sep=True)
        lines = _open_tag_lines(elem.tag, elem.attrib, pad, ">")
        lines.append("")
        lines.extend(inner)
        lines.extend(["", f"{pad}</{elem.tag}>"])
        return lines

    if not children and not text:
        return _open_tag_lines(elem.tag, elem.attrib, pad, " />")

    if not children:
        # A single-line value is emitted exactly as written, trailing space
        # included. `.strip()` is what canonicalises a value that was *wrapped*
        # for readability across several lines; applied to a one-line value it
        # silently edits shipped data -- `l10n_se`'s tax report ships
        # "...enligt huvudregeln " with a trailing space, and a formatter run
        # would have changed the string stored in `account.report.line.name`.
        raw = elem.text or ""
        value = text if "\n" in raw else raw
        return _open_tag_lines(
            elem.tag, elem.attrib, pad, f">{_esc_text(value)}</{elem.tag}>"
        )

    lines = _open_tag_lines(elem.tag, elem.attrib, pad, ">")
    for child in children:
        lines.extend(_format_element(child, depth + 1))
    lines.append(f"{pad}</{elem.tag}>")
    return lines


def _group_children(
    children: list[etree._Element],
) -> list[list[etree._Element]]:
    groups: list[list[etree._Element]] = []
    i = 0
    while i < len(children):
        group: list[etree._Element] = []
        while i < len(children) and callable(children[i].tag):
            group.append(children[i])
            i += 1
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


def format_xml_file(
    path: Path,
    *,
    dry_run: bool = False,
) -> bool | None:
    source = path.read_bytes()
    try:
        tree = etree.parse(BytesIO(source), _PARSER)
    except etree.XMLSyntaxError as exc:
        print(f"  SKIP  {path}: {exc}", file=sys.stderr)
        return None

    root = tree.getroot()
    had_decl = source.lstrip().startswith(b"<?xml")

    pre_root: list[str] = []
    node = root.getprevious()
    while node is not None:
        if callable(node.tag):
            pre_root.insert(0, etree.tostring(node, encoding="unicode"))
        node = node.getprevious()

    out: list[str] = []
    if had_decl:
        out.append('<?xml version="1.0" encoding="utf-8"?>')
    out.extend(pre_root)

    out.extend(_format_element(root, depth=0))

    new_content = "\n".join(out) + "\n"
    new_bytes = new_content.encode("utf-8")

    if new_bytes == source:
        return False

    if not dry_run:
        path.write_bytes(new_bytes)

    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=("Format Odoo XML data files with canonical 4-space indentation."),
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
        default=[],
        help=(
            "Extra directory names to skip, on top of the always-excluded "
            f"{', '.join(sorted(EXCLUDED_DIRS))}; repeatable"
        ),
    )
    args = parser.parse_args(argv)
    # `action="append"` appends to its default, so a default list here could
    # never be narrowed by the caller -- only grown. The permanent exclusions
    # live in EXCLUDED_DIRS, which `is_formattable` answers for, and this option
    # adds to them.
    excluded: set[str] = set(args.exclude)
    changed = unchanged = skipped = 0

    for root_str in args.roots:
        for xml_file in sorted(Path(root_str).rglob("*.xml")):
            if not is_formattable(xml_file) or excluded.intersection(xml_file.parts):
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
