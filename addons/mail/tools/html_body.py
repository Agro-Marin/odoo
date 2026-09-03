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


REPLY_CONTAINER_CLASS = "o_mail_reply_container"


def remove_quoted_reply(body: str) -> Markup | None:
    """Drop the quoted conversation the chatter prefills a reply with.

    The chatter's Reply and Forward actions build the composer body around a
    `o_mail_reply_container` block holding the message being answered. That
    block belongs to that one conversation, so anything that ARCHIVES a composed
    body -- saving it as a mail template -- must leave it behind.

    Returns None when there was nothing to drop, so the caller keeps the body it
    already had instead of one round-tripped through lxml.
    """
    fragments = parse_body_fragments(body)
    to_remove = [
        node
        for node in iter_fragment_elements(fragments)
        if REPLY_CONTAINER_CLASS in (node.get("class") or "").split()
    ]
    if not to_remove:
        return None
    # A top-level fragment must go from the list itself: it is what gets
    # re-serialized, and lxml reports a parent for it that the list does not
    # follow, so detaching it from that parent alone changes nothing.
    top_level = {id(node) for node in fragments if not isinstance(node, str)}
    for node in to_remove:
        if id(node) in top_level:
            index = next(i for i, f in enumerate(fragments) if f is node)
            # Text the user typed after the quote, if any, must survive.
            if tail := (node.tail or "").strip():
                fragments[index] = tail
            else:
                fragments.pop(index)
        elif (parent := node.getparent()) is not None:
            parent.remove(node)
    return render_body_fragments(fragments)
