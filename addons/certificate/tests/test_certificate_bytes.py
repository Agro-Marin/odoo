"""Certificate byte getters, content lifecycle and is_valid search."""

import base64
import hashlib
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCertificateBytesAndLifecycle(TransactionCase):
    """Byte getters and compute lifecycle of certificate.certificate."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name(
            [x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "cert-bytes-test")],
        )
        now = datetime.now(UTC)
        cls.crypto_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(cls.private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30))
            .sign(cls.private_key, hashes.SHA256())
        )
        cls.certificate = cls.env["certificate.certificate"].create(
            {
                "name": "Bytes test certificate",
                "content": base64.b64encode(
                    cls.crypto_cert.public_bytes(serialization.Encoding.PEM)
                ),
            },
        )

    def test_der_and_fingerprint_bytes_round_trip(self):
        """DER bytes reload as the same cert; fingerprint hashes that DER."""
        der_raw = self.certificate._get_der_certificate_bytes(formatting="raw")
        reloaded = x509.load_der_x509_certificate(der_raw)
        common_names = reloaded.subject.get_attributes_for_oid(
            x509.oid.NameOID.COMMON_NAME
        )
        self.assertEqual(common_names[0].value, "cert-bytes-test")

        fingerprint = self.certificate._get_fingerprint_bytes(formatting="raw")
        self.assertEqual(fingerprint, hashlib.sha256(der_raw).digest())

    def test_signature_and_public_numbers_bytes(self):
        """Signature bytes match the cert; public exponent decodes to 65537."""
        signature = base64.b64decode(
            self.certificate._get_signature_bytes(formatting="base64")
        )
        self.assertEqual(signature, self.crypto_cert.signature)

        e_bytes, _n_bytes = self.certificate._get_public_key_numbers_bytes(
            formatting="base64"
        )
        self.assertEqual(int.from_bytes(base64.b64decode(e_bytes)), 65537)

    def test_cleared_content_resets_computed_fields(self):
        """Blanking the content clears the parsed state without an error."""
        certificate = self.env["certificate.certificate"].create(
            {
                "name": "To clear",
                "content": base64.b64encode(
                    self.crypto_cert.public_bytes(serialization.Encoding.PEM)
                ),
            },
        )
        self.assertTrue(certificate.pem_certificate)

        certificate.content = False

        self.assertFalse(certificate.pem_certificate)
        self.assertFalse(certificate.serial_number)
        self.assertFalse(certificate.is_valid)
        self.assertFalse(certificate.loading_error)

    def test_garbage_content_sets_loading_error(self):
        """Unparseable content surfaces loading_error and invalidates."""
        certificate = self.env["certificate.certificate"].create(
            {
                "name": "Garbage",
                "content": base64.b64encode(b"this is not a certificate"),
            },
        )
        self.assertTrue(certificate.loading_error)
        self.assertFalse(certificate.pem_certificate)
        self.assertFalse(certificate.is_valid)

    def test_search_is_valid_domain(self):
        """is_valid is searchable: valid certs match, broken ones do not."""
        garbage = self.env["certificate.certificate"].create(
            {
                "name": "Search garbage",
                "content": base64.b64encode(b"still not a certificate"),
            },
        )
        found = self.env["certificate.certificate"].search([("is_valid", "=", True)])
        self.assertIn(self.certificate, found)
        self.assertNotIn(garbage, found)

    def test_search_is_valid_unsupported_operator(self):
        """Any operator other than 'in' is delegated back as NotImplemented."""
        result = self.env["certificate.certificate"]._search_is_valid("child_of", True)
        self.assertIs(result, NotImplemented)
