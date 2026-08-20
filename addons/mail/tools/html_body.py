import itertools
from collections.abc import Iterator

import lxml.html
from lxml import etree
from markupsafe import Markup, escape


def parse_body_fragments(body: str) -> list:
    """Top-level nodes of ``body``, without inventing a root element.

    ``lxml.html.fromstring`` needs a single root and makes one up when the body
    has none. Which element it invents depends on the libxml2 build -- 2.14
    wraps bare text in ``<span>`` where older builds used ``<p>`` -- so a body
    round-tripped through it comes back a different shape on different systems.
    Fragments have no such root, so serialising them preserves the body.
    """
    try:
        return lxml.html.fragments_fromstring(body)
    except ValueError:
        return lxml.html.fragments_fromstring(body.encode("utf-8"))


def iter_fragment_elements(fragments: list, tag: str | None = None) -> Iterator:
    """Every element under ``fragments``, skipping the bare text ones."""
    nodes = (f for f in fragments if not isinstance(f, str))
    if tag is None:
        return itertools.chain.from_iterable(node.iter() for node in nodes)
    return itertools.chain.from_iterable(node.iter(tag) for node in nodes)


def render_body_fragments(fragments: list) -> Markup:
    """Serialise ``fragments`` back to the shape they were parsed from.

    Text between top-level nodes lives in a fragment's ``tail``, so it is
    serialised with the element it trails; only the single leading string lxml
    returns separately needs escaping of its own.
    """
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
