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
    with caplog.at_level(logging.ERROR):
        html_translate(_identity, value)
    assert "using source value instead" not in caplog.text
