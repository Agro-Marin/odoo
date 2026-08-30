import gzip
import threading

import pytest
from lxml import etree, objectify

from odoo.libs.xml.parsers import fromstring, strict_parser

_EXTERNAL_ENTITY = (
    b'<?xml version="1.0"?>'
    b'<!DOCTYPE r [ <!ENTITY x SYSTEM "file:///etc/hostname"> ]>'
    b"<r>&x;</r>"
)
_INTERNAL_ENTITY = (
    b'<?xml version="1.0"?><!DOCTYPE r [ <!ENTITY e "EXPANDED"> ]><r>&e;</r>'
)


def _in_thread(fn):
    box: dict[str, object] = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    t = threading.Thread(target=run)
    t.start()
    t.join()
    return box.get("error", box.get("value"))


def _text(parse, document):
    try:
        return parse(document).text
    except etree.XMLSyntaxError:
        return "__refused__"


# --- what the hardening is worth ------------------------------------------
#
# lxml's own default is `resolve_entities='internal'`: it refuses an EXTERNAL
# entity already, but still expands an internal one. `resolve_entities=False`
# is the only setting in parsers.py that changes anything -- `no_network=True`
# and `decompress=False` are both lxml defaults, and the latter does not stop
# `etree.parse` decompressing a gzipped file in any case.


def test_the_stock_default_would_expand_an_internal_entity():
    """Without this, every assertion below would hold vacuously."""
    stock = etree.XMLParser()
    assert etree.fromstring(_INTERNAL_ENTITY, parser=stock).text == "EXPANDED"
    assert _text(lambda d: etree.fromstring(d, parser=stock), _EXTERNAL_ENTITY) == (
        "__refused__"
    )


@pytest.mark.parametrize("document", [_EXTERNAL_ENTITY, _INTERNAL_ENTITY])
def test_no_entity_is_expanded_in_either_thread(document):
    assert _text(etree.fromstring, document) in (None, "", "__refused__")
    assert _in_thread(lambda: _text(etree.fromstring, document)) in (
        None,
        "",
        "__refused__",
    )


def test_objectify_default_is_hardened_in_both_threads():
    def parse():
        return str(objectify.fromstring(_EXTERNAL_ENTITY))

    assert parse() in ("", "None")
    assert _in_thread(parse) in ("", "None")


def test_a_per_thread_parser_object_is_not_per_thread_behaviour():
    """`get_default_parser()` hands back a different object per thread.

    A test here used to read that as proof the hardening was thread-local and
    did not reach a worker -- and a sibling's failure message said so outright.
    It does reach it: `set_default_parser` configures the default for every
    thread, including ones that already exist. Identity is not behaviour, and
    asserting on it alone is what made the wrong reading look verified.
    """
    assert id(etree.get_default_parser()) != _in_thread(
        lambda: id(etree.get_default_parser())
    )
    assert _text(etree.fromstring, _INTERNAL_ENTITY) == _in_thread(
        lambda: _text(etree.fromstring, _INTERNAL_ENTITY)
    )


def test_a_thread_that_predates_the_hardening_is_covered_too():
    parser = etree.XMLParser(resolve_entities=False)
    started, go = threading.Event(), threading.Event()
    box: dict[str, object] = {}

    def early():
        started.set()
        go.wait(5)
        box["text"] = _text(etree.fromstring, _INTERNAL_ENTITY)

    thread = threading.Thread(target=early)
    thread.start()
    started.wait(5)
    previous = etree.get_default_parser()
    etree.set_default_parser(parser)
    try:
        go.set()
        thread.join(5)
    finally:
        etree.set_default_parser(previous)
    assert box["text"] in (None, "", "__refused__")


# --- why the explicit helpers exist ---------------------------------------


def test_the_default_parser_is_global_state_anything_can_reset():
    """`fromstring` here does not read that global, so it cannot be undone.

    The default is a process-wide setting with no owner: any library, in any
    thread, may call `set_default_parser` and silently re-enable expansion for
    every bare `etree.fromstring` after it. That -- not thread-locality -- is
    the reason a parser is passed explicitly on paths that take third-party
    documents, `dsig.resolve_reference` among them.
    """
    previous = etree.get_default_parser()
    etree.set_default_parser(etree.XMLParser())
    try:
        assert etree.fromstring(_INTERNAL_ENTITY).text == "EXPANDED"
        assert _text(fromstring, _INTERNAL_ENTITY) in (None, "", "__refused__")
        assert _text(fromstring, _EXTERNAL_ENTITY) in (None, "", "__refused__")
    finally:
        etree.set_default_parser(previous)


def test_the_strict_parser_is_safe_to_share_across_threads():
    document = (
        b"<root>"
        + b"".join(b"<a n='%d'><b/></a>" % i for i in range(200))
        + (b"</root>")
    )
    problems: list[object] = []

    def hammer():
        try:
            lengths = {len(fromstring(document)) for _ in range(200)}
        except BaseException as exc:
            problems.append(exc)
        else:
            problems.extend(n for n in lengths if n != 200)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert problems == []


def test_gzip_decompression_is_not_something_this_parser_prevents(tmp_path):
    """`decompress=False` was passed here as hardening; it is lxml's default.

    It also does not do what its presence suggested: libxml2 decompresses a
    gzipped *file* whatever the flag says -- 1.2 KB on disk became 300 000
    elements when this was measured. Kept as a live note rather than a comment,
    so that if a future lxml makes the flag bite, this fails and the claim can
    be made honestly again.
    """
    path = tmp_path / "doc.xml.gz"
    path.write_bytes(gzip.compress(b"<r>" + b"<a/>" * 1000 + b"</r>"))
    assert path.stat().st_size < 1000  # far smaller than what it expands to
    assert len(etree.parse(str(path), parser=strict_parser).getroot()) == 1000


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
