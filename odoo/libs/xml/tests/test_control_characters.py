"""Regression tests for ``odoo.libs.xml.utils.remove_control_characters``.

The contract that matters: whatever comes out must parse as XML, since the
whole point of the call site (``odoo.tools.xml_utils``) is to feed the result
straight to ``etree.fromstring``.
"""

import pytest
from lxml import etree

from odoo.libs.xml.utils import remove_control_characters

# (label, char) pairs that XML forbids and lxml rejects with
# "PCDATA invalid Char value ..."
FORBIDDEN = [
    ("NUL", "\x00"),
    ("ETX", "\x03"),
    ("VT", "\x0b"),
    ("FF", "\x0c"),
    ("ESC", "\x1b"),
    ("U+FFFE", "￾"),
    ("U+FFFF", "￿"),
]

# legal XML characters that must survive
PRESERVED = ["\t", "\n", "\r", " ", "\x7f", "é", "→", "😀", "�"]


@pytest.mark.parametrize(("label", "char"), FORBIDDEN, ids=[p[0] for p in FORBIDDEN])
def test_forbidden_char_is_removed(label, char):
    assert remove_control_characters(f"x{char}y".encode()) == b"xy"


@pytest.mark.parametrize(("label", "char"), FORBIDDEN, ids=[p[0] for p in FORBIDDEN])
def test_output_parses_as_xml(label, char):
    payload = f"<a>x{char}y</a>".encode()
    with pytest.raises(etree.XMLSyntaxError):
        etree.fromstring(payload)  # sanity: lxml really does reject it
    assert etree.fromstring(remove_control_characters(payload)).text == "xy"


@pytest.mark.parametrize("char", PRESERVED, ids=[hex(ord(c)) for c in PRESERVED])
def test_legal_char_is_preserved(char):
    payload = f"x{char}y".encode()
    assert remove_control_characters(payload) == payload


def test_encoded_surrogate_is_removed():
    # WTF-8 / CESU-8 encoded lone surrogate (U+D800), which valid UTF-8 forbids
    assert remove_control_characters(b"x\xed\xa0\x80y") == b"xy"


def test_invalid_utf8_lead_byte_is_removed():
    assert remove_control_characters(b"x\xffy") == b"xy"
