"""Tests for the signing/verification primitives of certificate.key."""

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

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


@tagged("post_install", "-at_install")
class TestKeyCryptoOperations(TransactionCase):
    """Record-level sign/verify guards, Ed25519 round-trip and RSA decrypt.

    The RSA/EC verification branches stay untested on purpose: they call the
    zero-argument nested checker with one argument (t24129) and cannot go
    green until that bug is fixed.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Key = cls.env["certificate.key"]

        ed_key = ed25519.Ed25519PrivateKey.generate()
        cls.ed_private = cls.Key.create(
            {
                "name": "Ed25519 private",
                "content": base64.b64encode(
                    ed_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                ),
            },
        )
        cls.ed_public = cls.Key.create(
            {
                "name": "Ed25519 public",
                "content": base64.b64encode(
                    ed_key.public_key().public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                ),
            },
        )

        cls.rsa_crypto_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        cls.rsa_private = cls.Key.create(
            {
                "name": "RSA private",
                "content": base64.b64encode(
                    cls.rsa_crypto_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                ),
            },
        )

    def test_sign_requires_private_key(self):
        """Signing with a public key must fail loudly (negative)."""
        with self.assertRaises(UserError):
            self.ed_public._sign("payload")

    def test_verify_requires_public_key(self):
        """Verifying with a private key must fail loudly (negative)."""
        with self.assertRaises(UserError):
            self.ed_private._verify("payload", b"whatever")

    def test_ed25519_sign_verify_round_trip(self):
        """An Ed25519 signature verifies against its public counterpart."""
        signature = base64.b64decode(
            self.ed_private._sign("payload", formatting="base64")
        )
        self.assertTrue(self.ed_public._verify("payload", signature))
        self.assertFalse(self.ed_public._verify("tampered", signature))

    def test_rsa_decrypt_round_trip(self):
        """An OAEP ciphertext for the key's public half decrypts back."""
        ciphertext = self.rsa_crypto_key.public_key().encrypt(
            b"secreto",
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        self.assertEqual(self.rsa_private._decrypt(ciphertext), "secreto")

    def test_decrypt_guards(self):
        """Decrypt rejects public keys, bad digests and non-RSA keys."""
        with self.assertRaises(UserError):
            self.ed_public._decrypt(b"x")
        with self.assertRaises(UserError):
            self.rsa_private._decrypt(b"x", hashing_algorithm="md5")
        with self.assertRaises(UserError):
            self.ed_private._decrypt(b"x")
