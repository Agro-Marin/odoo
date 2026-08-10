import threading

import pytest
from lxml import etree, objectify

import odoo.libs.xml.parsers  # noqa: F401  imported for its import-time hardening

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
    main_id = id(etree.get_default_parser())
    worker_id = _in_thread(lambda: id(etree.get_default_parser()))
    assert main_id != worker_id, (
        "etree.get_default_parser() now returns the same object across threads; "
        "set_default_parser may no longer be thread-local. If so, the "
        "import-time hardening reaches every thread and these tests can be "
        "simplified."
    )


def test_internal_entities_behave_the_same_in_both_threads():
    def parse():
        try:
            return etree.fromstring(_INTERNAL_ENTITY).text
        except etree.XMLSyntaxError:
            return "__refused__"

    assert parse() == _in_thread(parse)


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
