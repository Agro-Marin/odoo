import io
import unittest
from typing import Any
from unittest import mock

from odoo.tools import file_open
from odoo.tools.pdf import signature as pdf_signature
from odoo.tools.pdf.signature import PdfSigner


def _sample_pdf() -> io.BytesIO:
    with file_open("base/tests/minimal.pdf", "rb") as stream:
        return io.BytesIO(stream.read())


# PdfSigner only tests `self.company` for truthiness before deciding it cannot
# sign; a stand-in keeps these cases free of a database.
_ANY_COMPANY: Any = object()


class _WriterWithoutClone:
    """A pypdf whose PdfWriter predates clone_document_from_reader."""


class TestSignPdfKeepsItsContract(unittest.TestCase):
    def test_an_unusable_pypdf_yields_none_rather_than_raising(self):
        with mock.patch.object(pdf_signature, "PdfWriter", _WriterWithoutClone):
            signer = PdfSigner(_sample_pdf(), company=_ANY_COMPANY)
            self.assertFalse(signer.usable)
            self.assertIsNone(signer.sign_pdf())

    def test_the_object_is_never_left_half_built(self):
        with mock.patch.object(pdf_signature, "PdfWriter", _WriterWithoutClone):
            signer = PdfSigner(_sample_pdf(), company=_ANY_COMPANY)
        for attribute in ("writer", "usable", "company", "signing_time"):
            with self.subTest(attribute=attribute):
                self.assertTrue(hasattr(signer, attribute))

    def test_no_company_yields_none(self):
        self.assertIsNone(PdfSigner(_sample_pdf()).sign_pdf())

    def test_absent_cryptography_yields_none(self):
        with mock.patch.object(pdf_signature, "HAS_CRYPTOGRAPHY", False):
            signer = PdfSigner(_sample_pdf(), company=_ANY_COMPANY)
            self.assertIsNone(signer.sign_pdf())

    def test_availability_is_one_flag_not_ten_names(self):
        self.assertIsInstance(pdf_signature.HAS_CRYPTOGRAPHY, bool)
        if pdf_signature.HAS_CRYPTOGRAPHY:
            for name in (
                "hashes",
                "ec",
                "ed25519",
                "padding",
                "rsa",
                "Encoding",
                "Certificate",
                "PrivateKeyTypes",
                "load_pem_private_key",
                "load_pem_x509_certificate",
            ):
                with self.subTest(name=name):
                    self.assertIsNotNone(getattr(pdf_signature, name, None))


if __name__ == "__main__":
    unittest.main()


class TestSetIdentifier(unittest.TestCase):
    """`_set_id` had a branch that could only ever crash.

    It chose on `hasattr(type(self), "_ID")` and, when true, assigned
    `self.trailers["/ID"]`. `_ID` is an instance attribute on every pypdf that
    has it, never a class one, so the branch was unreachable -- and `trailers`
    is not an attribute of PdfWriter, so reaching it would have raised
    AttributeError rather than setting anything.
    """

    def test_the_identifier_is_stored_on_the_instance(self):
        from odoo.tools.pdf import OdooPdfFileWriter

        writer = OdooPdfFileWriter()
        writer._set_id("some-id")
        self.assertEqual(writer._ID, "some-id")

    def test_a_falsy_identifier_is_ignored(self):
        from odoo.tools.pdf import OdooPdfFileWriter

        writer = OdooPdfFileWriter()
        writer._set_id(None)
        self.assertFalse(writer._ID)

    def test_id_is_an_instance_attribute_not_a_class_one(self):
        # The premise of the branch that was removed.
        from pypdf import PdfWriter

        self.assertFalse(hasattr(PdfWriter, "_ID"))
        self.assertTrue(hasattr(PdfWriter(), "_ID"))


class TestRotatePdf(unittest.TestCase):
    def test_every_page_is_rotated(self):
        from odoo.tools.pdf import PdfReader, rotate_pdf

        rotated = PdfReader(io.BytesIO(rotate_pdf(_sample_pdf().getvalue())))
        self.assertTrue(len(rotated.pages))
        for index, page in enumerate(rotated.pages):
            with self.subTest(page=index):
                self.assertEqual(page.get("/Rotate"), 90)
