import argparse
import re
import sys
from io import BytesIO
from pathlib import Path

from lxml import etree

_PARSER = etree.XMLParser(remove_comments=False, strip_cdata=False)

_INDENT = "    "

_MAX_LINE = 88

_BLANK_SEP_CONTAINERS: frozenset[str] = frozenset({"odoo", "openerp"})

_OPAQUE_TAGS: frozenset[str] = frozenset({"template"})

EXCLUDED_DIRS: frozenset[str] = frozenset({"_vendor", "static", "node_modules"})


def is_formattable(path: Path) -> bool:
    return not EXCLUDED_DIRS.intersection(path.parts)


def iter_target_files(roots, excluded=frozenset()):
    """The XML files a fixer CLI walks: one implementation, both fixers.

    Both `main()` functions used to inline this loop, and they disagreed --
    the record sorter carried `_vendor, enterprise, static` of its own while
    the formatter asked `is_formattable`. A gate can only be as trustworthy as
    the command its failure tells you to run, so the selection is named, shared
    and directly testable rather than written twice.
    """
    for root in roots:
        for path in sorted(Path(root).rglob("*.xml")):
            if is_formattable(path) and not set(excluded).intersection(path.parts):
                yield path


def _is_opaque_field(elem: etree._Element) -> bool:
    return elem.tag == "field" and (
        elem.get("name") == "arch" or elem.get("type") in ("xml", "html")
    )


def _has_mixed_content(elem: etree._Element) -> bool:
    if not len(elem):
        return False
    if (elem.text or "").strip():
        return True
    return any((child.tail or "").strip() for child in elem)


def _esc_attr(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace("\r", "&#13;")
        .replace("\n", "&#10;")
        .replace("\t", "&#9;")
    )


def _esc_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class UnrenderableName(Exception):
    pass


def _qname(name: str, nsmap: dict, *, attribute: bool = False) -> str:
    if not name.startswith("{"):
        return name
    uri, _, local = name[1:].partition("}")
    for prefix, candidate in nsmap.items():
        if candidate != uri:
            continue
        if prefix is None:
            if attribute:
                continue
            return local
        return f"{prefix}:{local}"
    raise UnrenderableName(name)


def _tag_and_attrs(elem: etree._Element) -> tuple[str, list[str]]:
    nsmap = elem.nsmap
    parent = elem.getparent()
    inherited = parent.nsmap if parent is not None else {}

    parts: list[str] = []
    for prefix, uri in nsmap.items():
        if inherited.get(prefix) == uri:
            continue
        name = f"xmlns:{prefix}" if prefix else "xmlns"
        parts.append(f'{name}="{_esc_attr(uri)}"')
    for key, value in elem.attrib.items():
        parts.append(f'{_qname(key, nsmap, attribute=True)}="{_esc_attr(value)}"')
    return _qname(elem.tag, nsmap), parts


_SELF_CLOSE_RE = re.compile(r"(?<! )/>")


def _normalize_self_close(s: str) -> str:
    return _SELF_CLOSE_RE.sub(" />", s)


def _orig_depth_from_text(text: str | None, inner: str = "") -> int:
    if text and "\n" in text:
        return len(text.split("\n")[-1])
    widths = [_indent_width(line) for line in inner.split("\n")[1:] if line.strip()]
    return min(widths) if widths else 0


def _convert_arch_indent(content: str, orig_base: int, new_base: int) -> str:
    lines = content.split("\n")
    result: list[str] = []
    stack: list[int] = [orig_base]

    for line in lines:
        if not line.strip():
            result.append("")
            continue
        width = _indent_width(line)
        while len(stack) > 1 and stack[-1] >= width:
            stack.pop()
        if width > stack[-1]:
            stack.append(width)
        level = len(stack) - 1
        result.append(" " * (new_base + level * len(_INDENT)) + line.lstrip(" \t"))
    return "\n".join(result)


def _indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _inner_content(elem: etree._Element) -> str:
    s = etree.tostring(elem, pretty_print=False, encoding="unicode", with_tail=False)
    start = s.index(">") + 1
    close = f"</{_qname(elem.tag, elem.nsmap)}>"
    end = len(s) - len(close) if s.endswith(close) else s.rindex("</")
    return s[start:end] if end >= start else ""


def _open_tag_lines(
    tag: str, attr_parts: list[str], pad: str, suffix: str
) -> list[str]:
    if attr_parts:
        single = f"{pad}<{tag} {' '.join(attr_parts)}{suffix}"
    else:
        single = f"{pad}<{tag}{suffix}"
    if len(single) <= _MAX_LINE or not attr_parts:
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


def _rewrite_opaque_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    in_comment = False
    for line in lines:
        opens, closes = "<!--" in line, "-->" in line
        if in_comment or opens:
            out.append(line)
            in_comment = (in_comment or opens) and not (
                closes and line.rfind("-->") > line.rfind("<!--")
            )
            continue
        out.extend(_wrap_serialized_tag(_normalize_self_close(line)))
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
    tag, attrs = _tag_and_attrs(elem)

    if len(elem) == 0 and not (elem.text and elem.text.strip()):
        return _open_tag_lines(tag, attrs, pad, " />")

    inner = _inner_content(elem)

    if elem.text and elem.text.strip():
        inner_lines = inner.split("\n")
        while inner_lines and not inner_lines[0].strip():
            inner_lines.pop(0)
        while inner_lines and not inner_lines[-1].strip():
            inner_lines.pop()
        if not inner_lines:
            return _open_tag_lines(tag, attrs, pad, " />")
        inner_lines = _rewrite_opaque_lines(inner_lines)
        return _open_tag_lines(tag, attrs, pad, ">") + inner_lines + [f"{pad}</{tag}>"]

    orig_depth = _orig_depth_from_text(elem.text, inner)
    target_depth = (depth + 1) * len(_INDENT)

    shifted = _convert_arch_indent(inner, orig_depth, target_depth)

    shifted_lines = shifted.split("\n")
    if shifted_lines and not shifted_lines[0].strip():
        shifted_lines = shifted_lines[1:]
    while shifted_lines and not shifted_lines[-1].strip():
        shifted_lines.pop()

    if not shifted_lines:
        return _open_tag_lines(tag, attrs, pad, " />")

    shifted_lines = _rewrite_opaque_lines(shifted_lines)

    return _open_tag_lines(tag, attrs, pad, ">") + shifted_lines + [f"{pad}</{tag}>"]


def _format_mixed(elem: etree._Element, depth: int) -> list[str]:
    pad = _INDENT * depth
    tag, attrs = _tag_and_attrs(elem)
    lines = _open_tag_lines(tag, attrs, pad, ">")
    lines[-1] += f"{_inner_content(elem)}</{tag}>"
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
    tag, attrs = _tag_and_attrs(elem)

    if elem.tag in _BLANK_SEP_CONTAINERS:
        inner = _format_children(children, depth + 1, blank_sep=True)
        lines = _open_tag_lines(tag, attrs, pad, ">")
        lines.append("")
        lines.extend(inner)
        lines.extend(["", f"{pad}</{tag}>"])
        return lines

    if not children and not text:
        return _open_tag_lines(tag, attrs, pad, " />")

    if not children:
        raw = elem.text or ""
        value = text if "\n" in raw else raw
        return _open_tag_lines(tag, attrs, pad, f">{_esc_text(value)}</{tag}>")

    lines = _open_tag_lines(tag, attrs, pad, ">")
    for child in children:
        lines.extend(_format_element(child, depth + 1))
    lines.append(f"{pad}</{tag}>")
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


def _comparable(source: bytes) -> list:
    def squeeze(value: str | None) -> str:
        return " ".join((value or "").split())

    out: list = []

    def walk(element, depth: int) -> None:
        if callable(element.tag):
            out.append((depth, "#text-node", squeeze(element.text)))
        else:
            out.append(
                (
                    depth,
                    element.tag,
                    tuple(sorted((k, squeeze(v)) for k, v in element.attrib.items())),
                    tuple(sorted(element.nsmap.items(), key=lambda kv: kv[0] or "")),
                    squeeze(element.text),
                )
            )
        for child in element:
            walk(child, depth + 1)
        out.append((depth, "#tail", squeeze(element.tail)))

    # The prologue, not just the tree. `_format_element` is handed the root, so
    # everything above it -- the XML declaration, the doctype, and the nodes
    # sitting before the root -- is reassembled separately by
    # `format_xml_file`, and the comparison used to start at the root and never
    # look at any of it. Losing the doctype, or the copyright comment above
    # `<odoo>`, was a change this self-check reported as faithful.
    #
    # (Pre-root processing instructions are *not* a gap: lxml gives a PI a
    # callable `.tag` exactly as it does a comment, so `format_xml_file`
    # already carries them. They are compared here so that stays true.)
    tree = etree.parse(BytesIO(source), _PARSER)
    root = tree.getroot()
    prologue: list = [
        source.lstrip().startswith(b"<?xml"),
        tree.docinfo.doctype,
    ]
    node = root.getprevious()
    while node is not None:
        prologue.append(("#comment" if callable(node.tag) else node.tag, node.text))
        node = node.getprevious()
    out.append(("#prologue", tuple(prologue)))

    walk(root, 0)
    return out


def _is_faithful(source: bytes, formatted: bytes) -> bool:
    try:
        return _comparable(source) == _comparable(formatted)
    except etree.LxmlError:
        return False


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
    if tree.docinfo.doctype:
        out.append(tree.docinfo.doctype)
    out.extend(pre_root)

    try:
        out.extend(_format_element(root, depth=0))
    except UnrenderableName as exc:
        print(f"  SKIP  {path}: cannot render the name {exc}", file=sys.stderr)
        return None

    new_content = "\n".join(out) + "\n"
    new_bytes = new_content.encode("utf-8")

    if new_bytes == source:
        return False

    if not _is_faithful(source, new_bytes):
        print(
            f"  SKIP  {path}: the formatted output would not say the same thing",
            file=sys.stderr,
        )
        return None

    if not dry_run:
        path.write_bytes(new_bytes)

    return True


def build_parser() -> argparse.ArgumentParser:
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
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    excluded: set[str] = set(args.exclude)
    changed = unchanged = skipped = 0

    for xml_file in iter_target_files(args.roots, excluded):
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
