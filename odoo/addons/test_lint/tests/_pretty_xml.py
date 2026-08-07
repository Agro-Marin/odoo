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


def _is_opaque_field(elem: etree._Element) -> bool:
    return elem.tag == "field" and (
        elem.get("name") == "arch" or elem.get("type") in ("xml", "html")
    )


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

    lines = content.split("\n")

    above = sorted(
        len(line) - len(line.lstrip(" "))
        for line in lines
        if line.strip() and (len(line) - len(line.lstrip(" "))) > orig_base
    )
    if above:
        step = above[0] - orig_base
    else:
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
            new_spaces = new_base + (spaces - orig_base)
        result.append(" " * max(0, new_spaces) + line.lstrip(" "))
    return "\n".join(result)


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


def _format_element(elem: etree._Element, depth: int) -> list[str]:
    if callable(elem.tag):
        return _format_comment(elem, depth)

    if _is_opaque_field(elem) or elem.tag in _OPAQUE_TAGS:
        return _format_opaque(elem, depth)

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
        return _open_tag_lines(
            elem.tag, elem.attrib, pad, f">{_esc_text(text)}</{elem.tag}>"
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
        default=["_vendor", "enterprise", "static"],
        help=(
            "Directory names to skip (default: _vendor, enterprise, static); repeatable"
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
