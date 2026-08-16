import base64
import os
from unittest.mock import patch

from cryptography.fernet import Fernet

from odoo.tests import TransactionCase, tagged
from odoo.tools import file_open

from odoo.addons.base_encryption_mixin.models import (
    encryption_mixin as mixin_mod,
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
        mixin_mod.EncryptionMixin._invalidate_key_version_cache()
        cls.addClassCleanup(mixin_mod.EncryptionMixin._invalidate_key_version_cache)

        cls.company = cls.env.ref("base.main_company")
        with file_open(
            "certificate/tests/data/cert.pfx", "rb", filter_ext=(".pfx",)
        ) as fh:
            cls.pkcs12 = base64.b64encode(fh.read())

    def _attachments(self, model, field):
        return self.env["ir.attachment"].search_count(
            [("res_model", "=", model), ("res_field", "=", field)],
        )

    def _rotate(self, records):
        """Re-encrypt *records* exactly as a rotation driver's inner loop does.

        The driver that ships today is
        ``credential.credential.action_migrate_encryption_keys``, in a module
        this one does not depend on and must not: a deployment can take
        encrypted certificates without the credential vault. What this module
        owes any driver is the mixin contract below — discovery, the
        decrypt/encrypt seam, the stamp — and that is what these tests pin. The
        driver's own eligibility filter, admin gate and per-row error handling
        are covered in ``credential``.
        """
        version = records._get_current_encryption_key_version()
        for record in records:
            if record._reencrypt_with_current_key():
                record._stamp_encryption_key_version(version)
        self.env.cr.flush()

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
            "SELECT password_plain, content_encrypted, password_encrypted "
            "FROM certificate_key WHERE id = %s",
            (key.id,),
        )
        password_column, content_enc, password_enc = self.env.cr.fetchone()

        self.assertIsNone(
            password_column,
            "the cleartext password column must stay empty once a key exists",
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
            self._attachments("certificate.key", "content_plain"),
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
            "SELECT pkcs12_password_plain, content_encrypted, "
            "pkcs12_password_encrypted "
            "FROM certificate_certificate WHERE id = %s",
            (certificate.id,),
        )
        password_column, content_enc, password_enc = self.env.cr.fetchone()
        self.assertIsNone(password_column)
        self.assertTrue(bytes(content_enc).startswith(b"gAAAAA"))
        self.assertTrue(bytes(password_enc).startswith(b"gAAAAA"))
        self.assertFalse(self._attachments("certificate.certificate", "content_plain"))

        self.assertTrue(
            self._attachments("certificate.certificate", "pem_certificate"),
            "pem_certificate must remain stored — _search_is_valid needs it",
        )

        self.assertTrue(certificate.private_key_id)
        self.env.cr.execute(
            "SELECT content_encrypted FROM certificate_key WHERE id = %s",
            (certificate.private_key_id.id,),
        )
        self.assertTrue(bytes(self.env.cr.fetchone()[0]).startswith(b"gAAAAA"))

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
            self.company,
            name="original",
            password="dup-pw",
        )
        duplicate = key.copy()
        duplicate.invalidate_recordset()

        self.assertEqual(duplicate.password, "dup-pw")
        self.assertEqual(duplicate.loading_error, "")
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

    def test_models_are_registered_for_rotation(self):
        """Unregistered ciphertext becomes undecryptable once old keys retire."""
        discovered = self.env["certificate.key"]._get_encryption_migration_models()
        self.assertIn("certificate.key", discovered)
        self.assertIn("certificate.certificate", discovered)

    def test_one_private_key_is_shared_by_identical_bundles(self):
        """The dedup in _compute_private_key must see through the storage.

        It used to read the ``ir.attachment`` that backed ``certificate.key.content``,
        which no longer exists once the bytes are encrypted; matching now goes
        through the field, so the lookup keeps working in either mode.
        """
        certificates = self.env["certificate.certificate"].create(
            [
                {
                    "name": f"shared bundle {index}",
                    "content": self.pkcs12,
                    "pkcs12_password": PKCS12_PASSWORD,
                    "company_id": self.company.id,
                }
                for index in range(2)
            ]
        )
        self.env.cr.flush()

        self.assertTrue(certificates[0].private_key_id)
        self.assertEqual(
            certificates[0].private_key_id,
            certificates[1].private_key_id,
            "the same bundle must not mint a second certificate.key",
        )
        self.assertTrue(certificates[1]._sign(b"canary"))

    def test_key_version_is_stamped_on_write(self):
        key = self.env["certificate.key"]._generate_rsa_private_key(
            self.company,
            name="stamped",
        )
        self.assertEqual(key.encryption_key_version, 1)

        key.encryption_key_version = 0
        key.write({"name": "renamed"})
        self.assertEqual(key.encryption_key_version, 0)

        key.write({"password": "now-encrypted"})
        self.assertEqual(key.encryption_key_version, 1)

    def test_legacy_wire_format_still_decrypts(self):
        """Rows written before 19.0.1.0.2 hold base64(token), not a raw token.

        Moved here from credential: after the certificate fields
        were dropped from credential.credential, certificate.key.content is the
        binary encrypted column in the suite, so this is where the legacy shape
        has to keep being exercised.
        """
        plaintext = b"legacy-upgrade-bytes-" + b"A" * 100
        legacy_stored = base64.b64encode(Fernet(self.test_key).encrypt(plaintext))

        key = self.env["certificate.key"].create(
            {
                "name": "legacy shape",
                "content": base64.b64encode(b"placeholder"),
                "company_id": self.company.id,
            }
        )
        self.env.cr.execute(
            "UPDATE certificate_key SET content_encrypted = %s WHERE id = %s",
            [legacy_stored, key.id],
        )
        key.invalidate_recordset()

        self.assertEqual(
            base64.b64decode(key.with_context(bin_size=False).content),
            plaintext,
        )

    def test_rotation_promotes_legacy_binary_to_canonical(self):
        """The binary half of _ENCRYPTED_FIELD_PAIRS must survive a rotation.

        Also moved from credential, and the reason it matters:
        rotation runs _decrypt_binary_value -> _encrypt_binary_value, a seam
        where a mistake corrupts silently rather than raising.
        """
        plaintext = b"pkcs12-like-bytes-" + b"B" * 200
        legacy_stored = base64.b64encode(Fernet(self.test_key).encrypt(plaintext))

        key = self.env["certificate.key"].create(
            {
                "name": "legacy rotation",
                "content": base64.b64encode(b"placeholder"),
                "company_id": self.company.id,
            }
        )
        self.env.cr.execute(
            "UPDATE certificate_key SET content_encrypted = %s, "
            "encryption_key_version = 0 WHERE id = %s",
            [legacy_stored, key.id],
        )
        key.invalidate_recordset()

        self._rotate(key)

        self.assertEqual(
            key.encryption_key_version,
            key._get_current_encryption_key_version(),
            "a rotated row must be stamped so the next rotation skips it",
        )
        key.invalidate_recordset()
        self.env.cr.execute(
            "SELECT content_encrypted FROM certificate_key WHERE id = %s", (key.id,)
        )
        self.assertTrue(
            bytes(self.env.cr.fetchone()[0]).startswith(b"gAAAAA"),
            "post-rotation ciphertext must be the canonical raw-token shape",
        )
        self.assertEqual(
            base64.b64decode(key.with_context(bin_size=False).content),
            plaintext,
        )

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
            mixin_mod.EncryptionMixin._invalidate_key_version_cache()
            self._rotate(key | certificate.private_key_id)
            self._rotate(certificate)

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

        mixin_mod.EncryptionMixin._invalidate_key_version_cache()


@tagged("post_install", "-at_install")
class TestCertificateWithoutEncryptionKey(TransactionCase):
    """Without ODOO_API_ENCRYPTION_KEY the module behaves as it did before.

    This is what makes the encryption optional rather than a deployment
    precondition: an EDI, payroll or sign installation that never provisioned a
    Fernet key keeps uploading, signing and searching exactly as it always has,
    with the material in the cleartext columns.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env_patcher = patch.dict(os.environ, {}, clear=True)
        cls.env_patcher.start()
        cls.addClassCleanup(cls.env_patcher.stop)
        mixin_mod.EncryptionMixin._invalidate_key_version_cache()
        cls.addClassCleanup(mixin_mod.EncryptionMixin._invalidate_key_version_cache)

        cls.company = cls.env.ref("base.main_company")
        with file_open(
            "certificate/tests/data/cert.pfx", "rb", filter_ext=(".pfx",)
        ) as fh:
            cls.pkcs12 = base64.b64encode(fh.read())

    def test_upload_without_a_key_lands_in_the_cleartext_columns(self):
        secret = "no-fernet-key-here"
        key = self.env["certificate.key"]._generate_rsa_private_key(
            self.company,
            name="cleartext",
            password=secret,
        )
        self.env.cr.flush()

        self.env.cr.execute(
            "SELECT password_plain, content_encrypted, password_encrypted "
            "FROM certificate_key WHERE id = %s",
            (key.id,),
        )
        password_plain, content_enc, password_enc = self.env.cr.fetchone()

        self.assertEqual(password_plain, secret)
        self.assertIsNone(content_enc, "nothing may be encrypted without a key")
        self.assertIsNone(password_enc, "nothing may be encrypted without a key")

        key.invalidate_recordset()
        self.assertEqual(key.password, secret)
        self.assertTrue(key.with_context(bin_size=False).content)
        self.assertFalse(key.loading_error)
        self.assertTrue(key._sign(b"payload"))

    def test_certificate_signing_works_without_a_key(self):
        certificate = self.env["certificate.certificate"].create(
            {
                "name": "cleartext cert",
                "content": self.pkcs12,
                "pkcs12_password": PKCS12_PASSWORD,
                "company_id": self.company.id,
            }
        )
        self.env.cr.flush()

        self.assertFalse(certificate.loading_error)
        self.assertTrue(certificate.is_valid)
        self.assertTrue(certificate._sign(b"canary"))
        self.assertEqual(certificate.pkcs12_password, PKCS12_PASSWORD)

        self.env.cr.execute(
            "SELECT pkcs12_password_plain, pkcs12_password_encrypted "
            "FROM certificate_certificate WHERE id = %s",
            (certificate.id,),
        )
        cleartext, encrypted = self.env.cr.fetchone()
        self.assertEqual(cleartext, PKCS12_PASSWORD)
        self.assertIsNone(encrypted)

    def test_pem_key_filters_still_search(self):
        key = self.env["certificate.key"]._generate_rsa_private_key(
            self.company,
            name="searchable",
        )
        self.env.cr.flush()

        self.assertIn(
            key, self.env["certificate.key"].search([("pem_key", "!=", False)])
        )
        self.assertNotIn(
            key, self.env["certificate.key"].search([("pem_key", "=", False)])
        )

    def test_a_later_key_promotes_the_cleartext_rows(self):
        secret = "promote-me"
        key = self.env["certificate.key"]._generate_rsa_private_key(
            self.company,
            name="promotable",
            password=secret,
        )
        self.env.cr.flush()

        new_key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"ODOO_API_ENCRYPTION_KEY": new_key}, clear=True):
            mixin_mod.EncryptionMixin._invalidate_key_version_cache()
            self.assertTrue(key._reencrypt_with_current_key())
            self.env.cr.flush()

            self.env.cr.execute(
                "SELECT password_plain, content_encrypted, password_encrypted "
                "FROM certificate_key WHERE id = %s",
                (key.id,),
            )
            password_plain, content_enc, password_enc = self.env.cr.fetchone()
            self.assertIsNone(password_plain, "the cleartext column must be emptied")
            for label, blob in (("content", content_enc), ("password", password_enc)):
                self.assertTrue(
                    bytes(blob).startswith(b"gAAAAA"),
                    f"{label} must have been promoted to a Fernet token",
                )

            key.invalidate_recordset()
            self.assertEqual(key.password, secret)
            self.assertTrue(key._sign(b"payload"))

        mixin_mod.EncryptionMixin._invalidate_key_version_cache()
