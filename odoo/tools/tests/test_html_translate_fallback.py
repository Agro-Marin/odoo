"""``html_translate`` degrades to the source value instead of raising.

A translated HTML field holding content lxml cannot round-trip must not take
down the read that touched it, so ``html_translate`` wraps its
parse/translate/serialize attempt and falls back to the source on failure.

This suite exists because that handler is easy to misread. It catches
``ValueError`` while ``parse_html`` — passed into the same call — converts
lxml's ``ParserError`` into a ``UserError``, which is *not* a ``ValueError``.
That looks like a hole, and it is not one: ``parse_html`` is called here exactly
once, on ``"<div>%s</div>" % value``, and lxml's HTML parser accepts that
wrapper for every input tried (empty, whitespace-only, multi-element, comments).
The failure that actually reaches the handler comes from lxml's serializer —
``ValueError: All strings must be XML compatible`` on control characters — which
the existing clause catches correctly.

(``translate_xml_node`` takes a ``parse`` parameter, documented as "parse(text)
returns a node", which its body never invokes; ``html_translate`` passes
``parse_html`` into it for nothing. That dead parameter is what makes the
``UserError`` route look reachable from a reading of the source.)

So these tests pin the working behaviour rather than a fix. If someone later
makes ``translate_xml_node`` actually use its ``parse`` callback, the
``UserError`` route becomes live and ``test_control_characters_fall_back``
stays green while real failures start escaping — worth remembering.
"""

import logging

import pytest

from odoo.tools.translate import html_translate


def _identity(term):
    return term


@pytest.mark.parametrize(
    "value",
    ["\x00\x01", "\x0b\x0c\x00"],
    ids=["nul-soh", "control-chars"],
)
def test_control_characters_fall_back_to_the_source(value, caplog):
    """lxml's serializer rejects these, and the fallback absorbs it."""
    with caplog.at_level(logging.ERROR):
        assert html_translate(_identity, value) == value
    assert "using source value instead" in caplog.text


def test_wellformed_html_is_still_translated():
    assert html_translate(str.upper, "<p>hello</p>") == "<p>HELLO</p>"


def test_empty_value_short_circuits():
    for empty in ("", None, False):
        assert html_translate(_identity, empty) == empty


@pytest.mark.parametrize(
    "value",
    ["<div><p>unclosed", "<p>a</p><p>b</p>", "<!-- just a comment -->", "   "],
    ids=["unclosed", "multi-element", "comment-only", "whitespace"],
)
def test_lenient_parser_handles_sloppy_markup_without_the_fallback(value, caplog):
    """The wrapper makes these parse, which is why the UserError route is dead."""
    with caplog.at_level(logging.ERROR):
        html_translate(_identity, value)
    assert "using source value instead" not in caplog.text
