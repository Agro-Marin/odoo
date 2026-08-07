import threading

import pytest
from lxml import etree, objectify

import odoo.libs.xml.parsers  # noqa: F401  imported for its import-time hardening

# `odoo/libs/xml/parsers.py` hardens the *default* parsers at import time:
#
#     etree.set_default_parser(etree.XMLParser(resolve_entities=False, decompress=False))
#     objectify.set_default_parser(default_parser)
#
# `etree.set_default_parser` is documented as **thread-local**, so the hardening
# only reaches the importing thread. Measured, the worker thread really does get
# a different parser object.
#
# What that costs is NOT what it looks like. On lxml 6.0.2 the *stock* default
# parser already refuses external entities -- it raises XMLSyntaxError rather
# than resolving them -- so an unhardened worker thread is not an XXE hole. It
# was one on older lxml, where the stock default resolved them, which is why the
# hardening exists; upstream has since caught up.
#
# What remains is a real but narrower defect: the SAME document parsed with the
# implicit default parser produces different outcomes depending on which thread
# runs it (silently empty in the main thread, XMLSyntaxError in a worker). There
# are 31 implicit-parser call sites in the core.
#
# These tests pin the property that actually matters and would catch a real
# regression: **no thread resolves an external entity**, whichever parser it
# ends up with. If lxml ever relaxes its default again, or the hardening is
# removed, this fails in the worker thread -- which is the case nothing else
# covers.

_EXTERNAL_ENTITY = (
    b'<?xml version="1.0"?>'
    b'<!DOCTYPE r [ <!ENTITY x SYSTEM "file:///etc/hostname"> ]>'
    b"<r>&x;</r>"
)
_INTERNAL_ENTITY = (
    b'<?xml version="1.0"?>'
    b'<!DOCTYPE r [ <!ENTITY e "EXPANDED"> ]>'
    b"<r>&e;</r>"
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
    if "error" in box:
        return box["error"]
    return box["value"]


def _parse_external_with_default_parser():
    try:
        return etree.fromstring(_EXTERNAL_ENTITY).text
    except etree.XMLSyntaxError:
        return "__refused__"


def test_external_entity_is_not_resolved_in_the_main_thread():
    result = _parse_external_with_default_parser()
    assert result in (None, "", "__refused__"), (
        f"the default parser resolved an external entity to {result!r} — this "
        f"is XXE: a document could read arbitrary server files."
    )


def test_external_entity_is_not_resolved_in_a_worker_thread():
    # THE point of this file. etree.set_default_parser is thread-local, so a
    # worker never sees odoo/libs/xml/parsers.py's hardening and falls back to
    # lxml's stock default. That fallback is safe on lxml >= 6; this asserts it
    # stays safe, because nothing else in the tree checks the worker case.
    result = _in_thread(_parse_external_with_default_parser)
    assert result in (None, "", "__refused__"), (
        f"a worker thread resolved an external entity to {result!r}. The "
        f"import-time etree.set_default_parser() hardening is thread-local and "
        f"does not reach this thread, so it is relying on lxml's own default — "
        f"which has evidently changed. Pass a parser explicitly at the call "
        f"site, or re-harden per worker thread."
    )


def test_objectify_default_is_hardened_in_both_threads():
    def parse():
        return str(objectify.fromstring(_EXTERNAL_ENTITY))

    assert parse() in ("", "None")
    assert _in_thread(parse) in ("", "None")


def test_the_hardening_is_demonstrably_thread_local():
    # Not a requirement, a *record*: if lxml ever makes set_default_parser
    # process-wide this flips, and the reasoning in this file (and the 31
    # implicit call sites it is about) should be revisited.
    main_id = id(etree.get_default_parser())
    worker_id = _in_thread(lambda: id(etree.get_default_parser()))
    assert main_id != worker_id, (
        "etree.get_default_parser() now returns the same object across threads; "
        "set_default_parser may no longer be thread-local. If so, the "
        "import-time hardening reaches every thread and these tests can be "
        "simplified."
    )


def test_internal_entities_behave_the_same_in_both_threads():
    # Pinned so a future divergence here is visible: internal entities are the
    # case where main and worker currently agree.
    def parse():
        try:
            return etree.fromstring(_INTERNAL_ENTITY).text
        except etree.XMLSyntaxError:
            return "__refused__"

    assert parse() == _in_thread(parse)


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
