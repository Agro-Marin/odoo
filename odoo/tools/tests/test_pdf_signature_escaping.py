"""The signature appearance stream must escape PDF literal-string syntax.

``PdfSigner._setup_form`` builds the visible signature's content stream by
f-string interpolation::

    content = create_string_object(f"{content} by {signer.name} <{signer.email}>")
    stream._data = f"q ... ({content}) Tj ET Q".encode()

``create_string_object`` returns a ``TextStringObject``, which is a ``str``
subclass -- so the f-string inserts the *raw* text, not a PDF-escaped literal.
``(``, ``)`` and ``\\`` are the delimiters of a PDF literal string; a
``res.users.name`` containing ``)`` closes the string early and everything after
it is parsed as content-stream operators.

Consequence: a user who controls their own display name or email controls what
the visible signature appearance draws -- including drawing a different name
than the one that actually signed. The signature's cryptographic validity is
untouched; what breaks is the correspondence between the signature a human
reads and the identity it attests.

These are pure string-level tests: they exercise the escaping contract without
constructing a PDF or needing a certificate.
"""

import pytest

from odoo.tools.pdf.signature import _escape_pdf_literal


def _appearance_stream(signer_name: str, signer_email: str) -> str:
    """Reproduce the appearance stream built by PdfSigner._setup_form."""
    content = f"Digitally signed by {signer_name} <{signer_email}>"
    return (
        f"q 0.5 0 0 0.5 0 0 cm BT /F1 12 Tf 0 TL 0 10 Td "
        f"({_escape_pdf_literal(content)}) Tj ET Q"
    )


def _read_pdf_literal(stream: str) -> tuple[str, str]:
    """Lex the first literal string the way a PDF reader does.

    Per PDF 32000-1 §7.3.4.2 the scan starts after ``(``, tracks *balanced*
    parentheses, honours backslash escapes, and ends at the ``)`` that returns
    the depth to zero.  Returns ``(decoded_text, rest_of_stream)`` -- the rest
    is what the reader would then interpret as operators, which is where an
    injection shows up.  Raises if the literal is never closed.
    """
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
        "Bob) Tj 1 0 0 RG (PWNED",  # close the literal, emit operators, reopen
        "Carol\\",  # trailing backslash escapes the closing paren
        "Dave (nested",  # unbalanced open paren
    ],
    ids=["operator-injection", "backslash-escape", "unbalanced-paren"],
)
def test_delimiters_in_signer_name_are_escaped(name):
    # Two properties, both of which escaping provides and neither of which
    # holds today: the reader must decode exactly the text we meant to draw,
    # and nothing from the signer's fields may survive as operators.
    intended = f"Digitally signed by {name} <x@example.com>"
    text, rest = _read_pdf_literal(_appearance_stream(name, "x@example.com"))
    assert text == intended
    assert rest == " Tj ET Q"
