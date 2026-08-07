import pytest

from odoo.tools.pdf.signature import _escape_pdf_literal


def _appearance_stream(signer_name: str, signer_email: str) -> str:
    content = f"Digitally signed by {signer_name} <{signer_email}>"
    return (
        f"q 0.5 0 0 0.5 0 0 cm BT /F1 12 Tf 0 TL 0 10 Td "
        f"({_escape_pdf_literal(content)}) Tj ET Q"
    )


def _read_pdf_literal(stream: str) -> tuple[str, str]:
    specials = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
    i = stream.index("(") + 1
    depth, out = 1, []
    while i < len(stream):
        ch = stream[i]
        if ch == "\\" and i + 1 < len(stream):
            out.append(specials.get(stream[i + 1], stream[i + 1]))
            i += 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return "".join(out), stream[i + 1 :]
        out.append(ch)
        i += 1
    raise AssertionError("unterminated PDF literal string in appearance stream")


def test_ordinary_name_produces_one_literal():
    text, rest = _read_pdf_literal(
        _appearance_stream("Alice Smith", "alice@example.com")
    )
    assert text == "Digitally signed by Alice Smith <alice@example.com>"
    assert rest == " Tj ET Q"


@pytest.mark.parametrize(
    "name",
    [
        "Bob) Tj 1 0 0 RG (PWNED",
        "Carol\\",
        "Dave (nested",
    ],
    ids=["operator-injection", "backslash-escape", "unbalanced-paren"],
)
def test_delimiters_in_signer_name_are_escaped(name):
    intended = f"Digitally signed by {name} <x@example.com>"
    text, rest = _read_pdf_literal(_appearance_stream(name, "x@example.com"))
    assert text == intended
    assert rest == " Tj ET Q"
