import itertools
from collections.abc import Iterator

import lxml.html
from lxml import etree
from markupsafe import Markup, escape


def parse_body_fragments(body: str) -> list:
    try:
        return lxml.html.fragments_fromstring(body)
    except ValueError:
        return lxml.html.fragments_fromstring(body.encode("utf-8"))


def iter_fragment_elements(fragments: list, tag: str | None = None) -> Iterator:
    nodes = (f for f in fragments if not isinstance(f, str))
    if tag is None:
        return itertools.chain.from_iterable(node.iter() for node in nodes)
    return itertools.chain.from_iterable(node.iter(tag) for node in nodes)


def render_body_fragments(fragments: list) -> Markup:
    return Markup(
        "".join(
            str(escape(fragment))
            if isinstance(fragment, str)
            else etree.tostring(
                fragment, pretty_print=False, encoding="unicode", with_tail=True
            )
            for fragment in fragments
        )
    )
