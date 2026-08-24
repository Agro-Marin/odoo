import re
from collections.abc import Iterable

from lxml import etree, html

#: ``label`` is part of a tracker's unique key, so this cap is not a display
#: concern: two anchors to the same URL whose labels differ only past it collapse
#: into one tracker and their clicks stop being distinguishable. It was 40. It
#: stays bounded because the key is digested into a fixed-width column and an
#: unbounded label would be an unbounded row.
MAX_LABEL_LENGTH = 512


def url_is_blacklisted(url: str, patterns: Iterable[str] | None) -> bool:
    """Whether ``url`` matches one of ``patterns`` up to a path boundary.

    The one implementation both the html and the text shortener call. They used
    to carry one each, matching against different things -- the whole absolute
    URL here, the path only there -- so a blacklist entry naming a host was
    honoured in an html body and silently ignored in an SMS one.

    ``patterns`` are literals, not expressions: they were interpolated raw, so
    ``a.c`` matched ``/abc``, ``a+`` matched ``/aaa``, and a lone ``(`` raised
    ``re.PatternError`` out of a public helper.
    """
    if not patterns:
        return False
    return any(re.search(re.escape(item) + r'([#?/]|$)', url) for item in patterns)


def find_links_with_urls_and_labels(root_nodes, base_url, skip_regex=None, skip_prefix=None, skip_list=None):
    """Return lxml link nodes and respective matching urls (made absolute) and labels found in `root_nodes`.

    :param root_nodes: the root node, or an iterable of them, to process
    :param str base_url: base url to prefix relative hrefs
    :param str skip_regex: URL pattern to skip
    :param str skip_prefix: URL prefix to skip
    :param Iterable[str] skip_list: URL literals to skip, matched up to a path boundary

    :rtype: tuple[list[lxml.etree._Element], list[dict]]
    """
    link_nodes, urls_and_labels = [], []
    if isinstance(root_nodes, etree._Element):
        root_nodes = [root_nodes]

    for root_node in root_nodes:
        if isinstance(root_node, str):  # leading text of a fragment list
            continue
        for link_node in root_node.iter(tag="a"):
            original_url = link_node.get("href")
            if not original_url:
                continue
            absolute_url = base_url + original_url if original_url.startswith(('/', '?', '#')) else original_url
            if (
                (skip_regex and re.search(skip_regex, absolute_url))
                or (skip_prefix and absolute_url.startswith(skip_prefix))
                or url_is_blacklisted(absolute_url, skip_list)
            ):
                continue

            if link_node.text and (stripped_text := link_node.text.strip()):
                label = stripped_text[:MAX_LABEL_LENGTH]
            else:
                children = list(link_node)
                label = _get_label_from_elements(children)[:MAX_LABEL_LENGTH]

            link_nodes.append(link_node)
            urls_and_labels.append({'url': absolute_url, 'label': label})

    return link_nodes, urls_and_labels


def _get_label_from_elements(elements: Iterable[etree._Element], image_prefix: str = "[media] ") -> str:
    """Return the first label that can be extracted from a collection of elements"""
    for element in elements:
        if element.tag == "img":
            if img_alt := element.get("alt"):
                return f"{image_prefix}{img_alt}"
            if img_src := element.get("src"):
                img_src_tail = img_src.split("/")[-1]
                return f"{image_prefix}{img_src_tail}"
            return ""
        if isinstance(element, html.HtmlComment):  # A known "hack"
            continue
        if element.tag == "p" and element.get("class") == "o_outlook_hack":
            children = list(element)
            if label := _get_label_from_elements(children):
                return label
    return ""
