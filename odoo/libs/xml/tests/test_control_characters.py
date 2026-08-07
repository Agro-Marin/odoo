import pytest
from lxml import etree

from odoo.libs.xml.utils import remove_control_characters

FORBIDDEN = [
    ("NUL", "\x00"),
    ("ETX", "\x03"),
    ("VT", "\x0b"),
    ("FF", "\x0c"),
    ("ESC", "\x1b"),
    ("U+FFFE", "￾"),
    ("U+FFFF", "￿"),
]

PRESERVED = ["\t", "\n", "\r", " ", "\x7f", "é", "→", "😀", "�"]


@pytest.mark.parametrize(("label", "char"), FORBIDDEN, ids=[p[0] for p in FORBIDDEN])
def test_forbidden_char_is_removed(label, char):
    assert remove_control_characters(f"x{char}y".encode()) == b"xy"


@pytest.mark.parametrize(("label", "char"), FORBIDDEN, ids=[p[0] for p in FORBIDDEN])
def test_output_parses_as_xml(label, char):
    payload = f"<a>x{char}y</a>".encode()
    with pytest.raises(etree.XMLSyntaxError):
        etree.fromstring(payload)
    assert etree.fromstring(remove_control_characters(payload)).text == "xy"


@pytest.mark.parametrize("char", PRESERVED, ids=[hex(ord(c)) for c in PRESERVED])
def test_legal_char_is_preserved(char):
    payload = f"x{char}y".encode()
    assert remove_control_characters(payload) == payload


def test_encoded_surrogate_is_removed():
    assert remove_control_characters(b"x\xed\xa0\x80y") == b"xy"


def test_invalid_utf8_lead_byte_is_removed():
    assert remove_control_characters(b"x\xffy") == b"xy"
