import base64
import os
from unittest.mock import patch

from cryptography.fernet import Fernet

from odoo.tests import TransactionCase, tagged
from odoo.tools import file_open

from odoo.addons.base_credential_manager.models.mixins import (
    credential_encryption_mixin as mixin_mod,
)

PKCS12_PASSWORD = "example"


@tagged("post_install", "-at_install")
class TestCertificateEncryption(TransactionCase):
    """The point of the module: key material must not be readable at rest."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_key = Fernet.generate_key().decode()
        cls.env_patcher = patch.dict(
            os.environ,
            {"ODOO_API_ENCRYPTION_KEY": cls.test_key},
        )
        cls.env_patcher.start()
        cls.addClassCleanup(cls.env_patcher.stop)
        mixin_mod.CredentialEncryptionMixin._invalidate_key_version_cache()
        cls.addClassCleanup(
            mixin_mod.CredentialEncryptionMixin._invalidate_key_version_cache
        )

        # action_migrate_encryption_keys is admin-gated.
        cls.env.user.group_ids |= cls.env.ref(
            "base_credential_manager.group_credential_admin",
        )

        cls.company = cls.env.ref("base.main_company")
        with file_open(
            "certificate/tests/data/cert.pfx", "rb", filter_ext=(".pfx",)
        ) as fh:
            cls.pkcs12 = base64.b64encode(fh.read())

    def _attachments(self, model, field):
        return self.env["ir.attachment"].search_count(
            [("res_model", "=", model), ("res_field", "=", field)],
        )

    # ------------------------------------------------------------------
    # Encryption at rest
    # ------------------------------------------------------------------

    def test_key_material_never_lands_in_the_clear(self):
        """No column, attachment or filestore entry holds the key or password."""
        secret = "correct-horse-battery-staple"
        key = self.env["certificate.key"]._generate_rsa_private_key(
            self.company,
            name="at_rest",
            password=secret,
        )
        self.env.cr.flush()

        self.env.cr.execute(
            "SELECT password, content_encrypted, password_encrypted "
            "FROM certificate_key WHERE id = %s",
            (key.id,),
        )
        password_column, content_enc, password_enc = self.env.cr.fetchone()

        self.assertIsNone(
            password_column,
            "the legacy plaintext password column must stay empty",
        )
        for label, blob in (("content", content_enc), ("password", password_enc)):
            self.assertTrue(
                bytes(blob).startswith(b"gAAAAA"),
                f"{label} must be stored as a Fernet token",
            )
        self.assertNotIn(
            secret.encode(),
            bytes(password_enc),
            "the password must not be recoverable from its own ciphertext",
        )
        self.assertNotIn(
            b"BEGIN",
            bytes(content_enc),
            "no PEM armour may survive into the stored ciphertext",
        )
        self.assertFalse(
            self._attachments("certificate.key", "content"),
            "the uploaded key file must not be kept as an attachment",
        )
        self.assertFalse(
            self._attachments("certificate.key", "pem_key"),
            "the normalized private-key PEM must not be persisted at all",
        )

    def test_certificate_content_encrypted_but_pem_stays_public(self):
        """A PKCS12 bundle carries a private key; the parsed cert does not."""
        certificate = self.env["certificate.certificate"].create(
            {
                "name": "pkcs12",
                "content": self.pkcs12,
                "pkcs12_password": PKCS12_PASSWORD,
                "company_id": self.company.id,
            }
        )
        self.env.cr.flush()

        self.env.cr.execute(
            "SELECT pkcs12_password, content_encrypted, pkcs12_password_encrypted "
            "FROM certificate_certificate WHERE id = %s",
            (certificate.id,),
        )
        password_column, content_enc, password_enc = self.env.cr.fetchone()
        self.assertIsNone(password_column)
        self.assertTrue(bytes(content_enc).startswith(b"gAAAAA"))
        self.assertTrue(bytes(password_enc).startswith(b"gAAAAA"))
        self.assertFalse(self._attachments("certificate.certificate", "content"))

        # pem_certificate is deliberately still stored in the clear: a
        # certificate is public, and _search_is_valid searches on it.
        self.assertTrue(
            self._attachments("certificate.certificate", "pem_certificate"),
            "pem_certificate must remain stored — _search_is_valid needs it",
        )

        # The key auto-extracted from the bundle is itself encrypted.
        self.assertTrue(certificate.private_key_id)
        self.env.cr.execute(
            "SELECT content_encrypted FROM certificate_key WHERE id = %s",
            (certificate.private_key_id.id,),
        )
        self.assertTrue(bytes(self.env.cr.fetchone()[0]).startswith(b"gAAAAA"))

    # ------------------------------------------------------------------
    # Behaviour preserved
    # ------------------------------------------------------------------

    def test_roundtrip_through_encrypted_storage(self):
        """Everything the consumers read still reads back identical."""
        secret = "roundtrip-pw"
        key = self.env["certificate.key"]._generate_rsa_private_key(
            self.company,
            name="roundtrip",
            password=secret,
        )
        key.invalidate_recordset()

        self.assertEqual(key.password, secret)
        self.assertFalse(key.public)
        self.assertEqual(key.loading_error, "")
        self.assertTrue(
            base64.b64decode(key.with_context(bin_size=False).pem_key).startswith(
                b"-----BEGIN",
            ),
        )
        self.assertTrue(key.with_context(bin_size=False).content)
        self.assertTrue(key._sign(b"payload"))

    def test_public_key_verification_still_works(self):
        """The public/private split is stored metadata and must survive."""
        private = self.env["certificate.key"]._generate_rsa_private_key(
            self.company,
            name="signer",
        )
        public = self.env["certificate.key"].create(
            {
                "name": "verifier",
                "content": private._get_public_key_bytes(
                    encoding="pem",
                    formatting="base64",
                ),
                "company_id": self.company.id,
            }
        )
        public.invalidate_recordset()

        self.assertTrue(public.public, "a public key must still be flagged public")
        signature = private._sign(b"message", formatting="raw")
        self.assertTrue(public._verify(b"message", signature))
        self.assertFalse(public._verify(b"tampered", signature))

    def test_is_valid_search_survives(self):
        """_search_is_valid reads pem_certificate, which stays stored."""
        certificate = self.env["certificate.certificate"].create(
            {
                "name": "searchable",
                "content": self.pkcs12,
                "pkcs12_password": PKCS12_PASSWORD,
                "company_id": self.company.id,
            }
        )
        self.env.cr.flush()
        self.assertIn(
            certificate,
            self.env["certificate.certificate"].search([("is_valid", "=", True)]),
        )

    def test_duplicate_keeps_the_key_material(self):
        """The form's Duplicate action must not yield an empty key.

        ``content`` and ``password`` were copyable columns in the base module;
        ``copy()`` now sees the encrypted columns in their place, so those have
        to stay copyable too or duplication silently loses the material.
        """
        key = self.env["certificate.key"]._generate_rsa_private_key(
            self.company, name="original", password="dup-pw",
        )
        duplicate = key.copy()
        duplicate.invalidate_recordset()

        self.assertEqual(duplicate.password, "dup-pw")
        self.assertEqual(duplicate.loading_error, "")
        # Not the PEM bytes: BestAvailableEncryption re-salts on every
        # serialization, so the same key encodes differently each time. The
        # public key is the stable identity of the pair.
        self.assertEqual(
            duplicate._get_public_key_bytes(),
            key._get_public_key_bytes(),
        )

    def test_wrong_password_reports_loading_error(self):
        """A bad password must still surface as loading_error, not a traceback."""
        key = self.env["certificate.key"].create(
            {
                "name": "bad password",
                "content": self.pkcs12,
                "password": "not-the-password",
                "company_id": self.company.id,
            }
        )
        key.invalidate_recordset()
        self.assertTrue(key.loading_error)
        self.assertFalse(key.pem_key)

    # ------------------------------------------------------------------
    # Key rotation
    # ------------------------------------------------------------------

    def test_models_are_registered_for_rotation(self):
        """Unregistered ciphertext becomes undecryptable once old keys retire."""
        discovered = self.env[
            "credential.credential"
        ]._get_encryption_migration_models()
        self.assertIn("certificate.key", discovered)
        self.assertIn("certificate.certificate", discovered)

    def test_key_version_is_stamped_on_write(self):
        key = self.env["certificate.key"]._generate_rsa_private_key(
            self.company,
            name="stamped",
        )
        self.assertEqual(key.encryption_key_version, 1)

        # A write that carries no encrypted payload must not restamp.
        key.encryption_key_version = 0
        key.write({"name": "renamed"})
        self.assertEqual(key.encryption_key_version, 0)

        key.write({"password": "now-encrypted"})
        self.assertEqual(key.encryption_key_version, 1)

    def test_rotation_reencrypts_certificate_material(self):
        """A rotated key must leave every certificate secret readable."""
        key = self.env["certificate.key"]._generate_rsa_private_key(
            self.company,
            name="rotating",
            password="rotate-me",
        )
        certificate = self.env["certificate.certificate"].create(
            {
                "name": "rotating cert",
                "content": self.pkcs12,
                "pkcs12_password": PKCS12_PASSWORD,
                "company_id": self.company.id,
            }
        )
        self.env.cr.flush()
        signature_before = certificate._sign(b"canary")

        self.env.cr.execute(
            "SELECT content_encrypted FROM certificate_key WHERE id = %s",
            (key.id,),
        )
        ciphertext_before = bytes(self.env.cr.fetchone()[0])

        new_key = Fernet.generate_key().decode()
        with patch.dict(
            os.environ,
            {
                "ODOO_API_ENCRYPTION_KEY": new_key,
                "ODOO_API_ENCRYPTION_KEY_V1": self.test_key,
            },
            clear=True,
        ):
            mixin_mod.CredentialEncryptionMixin._invalidate_key_version_cache()
            result = self.env["credential.credential"].action_migrate_encryption_keys()

            self.assertEqual(result["failed"], 0, result["errors"])
            self.assertIn("certificate.key", result["models"])
            self.assertIn("certificate.certificate", result["models"])

            self.env.cr.execute(
                "SELECT content_encrypted FROM certificate_key WHERE id = %s",
                (key.id,),
            )
            self.assertNotEqual(
                bytes(self.env.cr.fetchone()[0]),
                ciphertext_before,
                "the ciphertext must actually have been rewritten",
            )

            key.invalidate_recordset()
            certificate.invalidate_recordset()
            self.assertEqual(key.password, "rotate-me")
            self.assertTrue(key._sign(b"payload"))
            self.assertEqual(certificate.pkcs12_password, PKCS12_PASSWORD)
            self.assertEqual(
                certificate._sign(b"canary"),
                signature_before,
                "rotation must not disturb the private key itself",
            )

        mixin_mod.CredentialEncryptionMixin._invalidate_key_version_cache()
