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
    """Escape a string for use inside double-quoted XML attribute values.

    The whitespace characters are written as character references, not emitted
    raw. A parser applies attribute-value normalisation, turning any literal
    newline or tab in an attribute into a single space -- so writing one back
    verbatim silently rewrites the value. ``eval="{&#10;'k': 1&#10;}"`` came
    back out of a formatting pass as ``{ 'k': 1 }``: a different string, on a
    round trip that is supposed to be meaning-preserving.
    """
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
    """A qualified name this formatter cannot write back faithfully."""


def _qname(name: str, nsmap: dict, *, attribute: bool = False) -> str:
    """Render a possibly namespaced *name* as source, given the in-scope *nsmap*.

    lxml stores a namespaced name in Clark notation -- ``{uri}local`` -- and
    this formatter used to write that straight into the output:

        <{urn:un:unece:uncefact:...:100}CrossIndustryInvoice>

    which is not well-formed XML. 268 files in this repository parsed before a
    formatting pass and did not parse after it, three of them shipped data
    (``l10n_hu_edi``'s two templates, ``l10n_tr_nilvera_edispatch``'s). The
    namespace *declarations* were lost as well, since lxml keeps them in
    ``nsmap`` rather than in ``attrib``, so even a correctly spelled prefix
    would have had nothing to bind it.

    An attribute in the default namespace has no faithful spelling -- an
    unprefixed attribute name is in *no* namespace, not in the default one --
    so that case refuses rather than guesses.
    """
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
    """The rendered tag name and attribute strings of *elem*.

    Namespace declarations come first, and only the ones *this* element
    introduces: ``nsmap`` reports every prefix in scope, so emitting all of them
    on every element would restate the root's declarations at every depth.
    """
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
    """The indentation the inner content of an opaque element is written at.

    Normally that is what follows the last newline of ``elem.text`` -- the
    whitespace between the open tag and the first child.

    When the content *starts on the open tag's line* there is no such
    whitespace, and answering 0 puts the first line a level above everything
    after it, shifting the whole block down by one. The file then needed a
    second pass to settle, which the tree-wide fixed-point test rejects:
    ``l10n_es_edi_tbai``'s LROE template opens
    ``<template id="…"> <!-- To be used for both 140 and 240 -->``. The
    remaining lines say where the content really sits, so the base is read off
    the shallowest of them.
    """
    if text and "\n" in text:
        return len(text.split("\n")[-1])
    widths = [_indent_width(line) for line in inner.split("\n")[1:] if line.strip()]
    return min(widths) if widths else 0


def _convert_arch_indent(content: str, orig_base: int, new_base: int) -> str:
    """Re-indent arch content to the canonical 4-space step.

    Nesting is read off the *shape* of the original indentation rather than
    computed from it: a stack of enclosing widths, one level per entry. A line
    indented further than the line above opens a level, a line indented less
    closes as many as it has to, and a line at the same width stays put.

    That replaces a ``level = (spaces - orig_base) // step`` arithmetic, whose
    ``step`` was the *smallest* indent above the base. One line sitting a single
    column deeper than its parent -- a wrapped attribute, a continuation --
    made ``step`` 1, and then every real level of nesting multiplied by four.
    ``l10n_es_edi_tbai``'s LROE template grew its indentation without bound,
    one pass to the next, so the gate built on this formatter could not go
    green on that file however often it was run.

    Reading the shape is also what makes the conversion idempotent by
    construction: run over its own output the widths are ``new_base + 4k``, and
    a stack yields exactly the levels that produced them.
    """
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
    """Return the raw inner content of *elem* (between its opening and closing tags).

    Uses lxml's serialisation (``pretty_print=False``, ``with_tail=False``) which
    preserves the original ``.text`` / ``.tail`` whitespace stored during parsing
    — safe for mixed-text content.  ``with_tail=False`` prevents the element's
    own ``.tail`` (sibling-separator whitespace) from being included and
    corrupting the slice.

    The closing tag is located by the string lxml actually wrote, not by
    ``elem.tag``: those differ for a namespaced element, where ``elem.tag`` is
    Clark notation and the serialisation carries a prefix.
    """
    s = etree.tostring(elem, pretty_print=False, encoding="unicode", with_tail=False)
    start = s.index(">") + 1
    close = f"</{_qname(elem.tag, elem.nsmap)}>"
    end = len(s) - len(close) if s.endswith(close) else s.rindex("</")
    return s[start:end] if end >= start else ""


def _open_tag_lines(
    tag: str, attr_parts: list[str], pad: str, suffix: str
) -> list[str]:
    """Return lines for a tag opening (or self-closing tag).

    *suffix* is appended after the last attribute (or after the tag name when
    there are no attributes).  Typical values: ``">"``, ``" />"``,
    ``">text</tag>"``.

    If the single-line form fits within ``_MAX_LINE`` characters, one line is
    returned.  Otherwise each attribute is placed on its own line indented by
    one extra level, with *suffix* on the last attribute line.

    **An element with no attributes is never split.** The wrapping loop is
    driven by the attribute list, so with an empty one it ran zero times and
    the suffix -- which for a text-only element carries *the content and the
    closing tag* -- was never emitted at all:

        >>> _open_tag_lines("path", [], " " * 8, ">web/static/…/file.scss</path>")
        ['        <path']

    Three shipped data files lost the ``<path>`` of an ``<asset>`` record that
    way and stopped being well-formed XML. There is nothing to wrap in a tag
    with no attributes, so the long line is simply kept.
    """
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
    """Normalise and wrap the tags of opaque content, leaving comments alone.

    Both rewrites here -- a space before ``/>``, and one attribute per line --
    are style rules about *markup*. A commented-out ``<field .../>`` is not
    markup, it is text that happens to look like it, and rewriting it edits
    what the file says. Ten files in this repository carry one, including a
    conditional-comment block in ``mass_mailing``'s templates
    (``<!--[if mso]> … <o:AllowPNG/> …``), where the payload is markup for a
    *different* consumer and none of this formatter's business.

    Any line from ``<!--`` to ``-->`` is therefore passed through untouched,
    which is conservative: a line that merely mentions a comment opener keeps
    its own formatting too.
    """
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
    """A form of *source* that ignores everything this formatter may change.

    Indentation, the position of a line break and the amount of whitespace
    inside a text run are the formatter's to decide; a tag, an attribute, a
    comment and a *word* are not. So whitespace runs collapse to a single
    space and everything else is compared exactly, attributes sorted because
    their order carries no meaning.

    Built by hand rather than through ``etree.tostring(method="c14n")``:
    canonicalisation refuses some perfectly valid documents in this tree
    outright (``C14NError``), and a self-check that raises on the files it
    cannot judge is worse than no self-check at all.
    """

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

    walk(etree.fromstring(source), 0)
    return out


def _is_faithful(source: bytes, formatted: bytes) -> bool:
    """Whether *formatted* still says what *source* said.

    The formatter rewrites every data file in the repository from a tree it
    reassembles by hand, and a hand-written serialiser has a long tail of ways
    to be wrong about one: a namespaced tag, an element with no attributes and
    a long text, a character reference in an attribute. Each of those was a
    real defect here, each one silent, and each one found only by comparing a
    before and an after -- never by the formatter itself, which reported
    success every time.

    So it now checks its own work, and a file it cannot reproduce faithfully is
    skipped rather than written. That turns the whole class of defect from
    "corrupts the tree" into "declines the file", which is a failure mode a
    ratcheted gate can carry safely.
    """
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
