"""Tests for the signing/verification primitives of certificate.key."""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


def _rsa_pems_b64():
    """Return (private_pem_b64, public_pem_b64) for a fresh RSA key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(private_pem), base64.b64encode(public_pem)


@tagged("post_install", "-at_install")
class TestKeySigning(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Key = cls.env["certificate.key"]
        cls.pem_b64, _pub = _rsa_pems_b64()

    def test_unsupported_hash_rejected(self):
        """Only sha1/sha256 are accepted as hashing algorithms (negative)."""
        with self.assertRaises(UserError):
            self.Key._sign_with_key("x", self.pem_b64, hashing_algorithm="md5")

    def test_unloadable_key_rejected(self):
        """Garbage PEM content raises a UserError (negative)."""
        with self.assertRaises(UserError):
            self.Key._sign_with_key("x", base64.b64encode(b"not a pem"))

    def test_formatting_variants(self):
        """encodebytes wraps lines while base64 stays single-line (boundary)."""
        wrapped = self.Key._sign_with_key("m", self.pem_b64)
        raw = self.Key._sign_with_key("m", self.pem_b64, formatting="base64")
        self.assertIn(b"\n", wrapped)
        self.assertNotIn(b"\n", raw)
