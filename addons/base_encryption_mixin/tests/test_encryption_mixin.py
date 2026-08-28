"""The mixin's contract, asserted without a credential in sight.

This module exists because two of the three models that encrypt fields through
it are not credentials -- an X.509 certificate and its key -- and every one of
them used to install a credential vault, a rate limiter, an inbound gate and a
session cache to get a Fernet round-trip. These tests therefore use no consumer
at all: what they can reach on a bare install is exactly what the module
promises on its own.
"""

import base64
import os
from unittest.mock import patch

from cryptography.fernet import Fernet

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.base_encryption_mixin.models.mixin_encryption import MixinEncryption

_KEY = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="


class TestEncryptionMixin(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env_patcher = patch.dict(os.environ, {"ODOO_API_ENCRYPTION_KEY": _KEY})
        cls.env_patcher.start()
        cls.addClassCleanup(cls.env_patcher.stop)
        cls.mixin = cls.env["mixin.encryption"]

    def test_the_mixin_is_abstract_and_owns_no_table(self):
        self.assertTrue(self.mixin._abstract)
        self.env.cr.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            [self.mixin._name.replace(".", "_")],
        )
        self.assertEqual(self.env.cr.fetchone()[0], 0)

    def test_a_value_round_trips(self):
        token = self.mixin._encrypt_value("a value worth hiding")
        self.assertTrue(token.startswith(b"gAAAAA"), "not a Fernet token")
        self.assertEqual(self.mixin._decrypt_value(token), "a value worth hiding")

    def test_binary_round_trips_in_the_base64_form_a_binary_field_holds(self):
        raw = bytes(range(256))
        stored = base64.b64encode(raw)

        token = self.mixin._encrypt_binary_value(stored)

        self.assertTrue(token.startswith(b"gAAAAA"), "not a Fernet token")
        self.assertEqual(self.mixin._decrypt_binary_value(token), stored)
        self.assertEqual(base64.b64decode(self.mixin._decrypt_binary_value(token)), raw)

    def test_an_empty_value_is_not_encrypted(self):
        self.assertFalse(self.mixin._encrypt_value(""))
        self.assertFalse(self.mixin._decrypt_value(b""))

    @mute_logger("odoo.addons.base_encryption_mixin.models.mixin_encryption")
    def test_a_malformed_token_reports_itself(self):
        with self.assertRaises(ValidationError) as caught:
            self.mixin._coerce_fernet_token(b"not base64 at all!!")
        self.assertIn("Invalid encrypted binary data", str(caught.exception))

    def test_a_foreign_key_cannot_read_the_token(self):
        token = self.mixin._encrypt_value("mine")
        with patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": Fernet.generate_key().decode()}
        ):
            self.mixin._invalidate_key_version_cache()
            self.assertFalse(self.mixin._decrypt_value_safe(token))
        self.mixin._invalidate_key_version_cache()

    def test_the_key_version_resolves_on_a_bare_install(self):
        self.assertIsInstance(self.mixin._get_current_encryption_key_version(), int)

    @mute_logger("odoo.addons.base_encryption_mixin.models.mixin_encryption")
    def test_a_malformed_current_key_still_falls_back_to_an_old_one(self):
        old_key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"ODOO_API_ENCRYPTION_KEY": old_key}):
            self.mixin._invalidate_key_version_cache()
            token = self.mixin._encrypt_value("rotated-secret")

        with patch.dict(
            os.environ,
            {
                "ODOO_API_ENCRYPTION_KEY": "not-a-valid-fernet-key",
                "ODOO_API_ENCRYPTION_KEY_V1": old_key,
            },
        ):
            self.mixin._invalidate_key_version_cache()
            # A malformed *current* key says nothing about old keys, so the
            # fallback loop must still run and succeed.
            self.assertEqual(self.mixin._decrypt_value(token), "rotated-secret")
        self.mixin._invalidate_key_version_cache()

    @mute_logger("odoo.addons.base_encryption_mixin.models.mixin_encryption")
    def test_a_malformed_current_key_raises_when_no_old_key_works(self):
        token = self.mixin._encrypt_value("no-fallback-available")
        with patch.dict(os.environ, {"ODOO_API_ENCRYPTION_KEY": "still-not-valid"}):
            self.mixin._invalidate_key_version_cache()
            with self.assertRaises(ValidationError):
                self.mixin._decrypt_value(token)
        self.mixin._invalidate_key_version_cache()

    @mute_logger("odoo.addons.base_encryption_mixin.models.mixin_encryption")
    def test_a_malformed_current_key_honours_fallback_disabled(self):
        token = self.mixin._encrypt_value("fallback-disabled-secret")
        with (
            patch.object(type(self.mixin), "_allow_key_fallback", return_value=False),
            patch.dict(os.environ, {"ODOO_API_ENCRYPTION_KEY": "still-not-valid"}),
        ):
            self.mixin._invalidate_key_version_cache()
            with self.assertRaises(ValidationError) as caught:
                self.mixin._decrypt_value(token)
            self.assertIn("fallback disabled", str(caught.exception))
        self.mixin._invalidate_key_version_cache()

    def test_an_absent_current_key_still_returns_false_quietly(self):
        with patch.dict(os.environ, clear=False) as env:
            env.pop("ODOO_API_ENCRYPTION_KEY", None)
            self.mixin._invalidate_key_version_cache()
            self.assertFalse(self.mixin._decrypt_value(b"gAAAAA-anything"))
        self.mixin._invalidate_key_version_cache()

    def test_the_walker_reports_consumers_never_the_mixin(self):
        discovered = self.mixin._get_encryption_migration_models()
        self.assertNotIn("mixin.encryption", discovered)
        for name in discovered:
            self.assertFalse(
                self.env[name]._abstract,
                f"{name} is abstract and cannot hold rows to re-encrypt",
            )

    def test_reencrypt_with_current_key_stamps_the_version_itself(self):
        """A consumer that calls only `_reencrypt_with_current_key` (and never
        remembers the separate stamp call) must not end up with a stale
        `encryption_key_version` -- the method has to be self-contained."""

        class FakeRecord:
            _ENCRYPTED_FIELD_PAIRS = (("content", "content_encrypted", False),)
            _ENCRYPTED_FALLBACK_FIELDS: dict = {}

            def __init__(self):
                self._data = {"content_encrypted": b"cipher"}
                self.stamped_with = None

            def ensure_one(self):
                pass

            def with_context(self, **kwargs):
                return self

            def __getitem__(self, key):
                return self._data.get(key)

            def __setitem__(self, key, value):
                self._data[key] = value

            def _decrypt_value(self, value):
                return "plaintext"

            def _encrypt_value(self, value):
                return b"reencrypted"

            def _promote_cleartext_field(self, plain_field, encrypted_field, is_binary):
                return False

            def _get_current_encryption_key_version(self):
                return 3

            def _stamp_encryption_key_version(self, version):
                self.stamped_with = version

        fake = FakeRecord()
        touched = MixinEncryption._reencrypt_with_current_key(fake)

        self.assertTrue(touched)
        self.assertEqual(fake.stamped_with, 3)

    def test_reencrypt_with_current_key_does_not_stamp_when_untouched(self):
        class FakeRecord:
            _ENCRYPTED_FIELD_PAIRS = (("content", "content_encrypted", False),)
            _ENCRYPTED_FALLBACK_FIELDS: dict = {}

            def __init__(self):
                self._data = {"content_encrypted": None}
                self.stamped_with = "untouched"

            def ensure_one(self):
                pass

            def with_context(self, **kwargs):
                return self

            def __getitem__(self, key):
                return self._data.get(key)

            def __setitem__(self, key, value):
                self._data[key] = value

            def _promote_cleartext_field(self, plain_field, encrypted_field, is_binary):
                return False

            def _stamp_encryption_key_version(self, version):
                self.stamped_with = version

        fake = FakeRecord()
        touched = MixinEncryption._reencrypt_with_current_key(fake)

        self.assertFalse(touched)
        self.assertEqual(fake.stamped_with, "untouched")

    def test_the_payload_stamp_is_reachable_without_importing_a_consumer(self):
        self.assertIsNone(self.mixin._stamp_encrypted_payload([{"content": b"x"}]))

    def test_stamping_nothing_never_reaches_the_cursor(self):
        with (
            patch.object(type(self.mixin), "_stamp_encryption_key_version") as stamp,
            patch.object(type(self.mixin), "_get_current_encryption_key_version"),
        ):
            self.mixin._stamp_encrypted_payload([])
            self.mixin._stamp_encrypted_payload([{"content": b"x"}])
        stamp.assert_not_called()

    def test_stamping_is_driven_by_the_declaration_not_by_the_write(self):
        self.assertFalse(self.mixin._ENCRYPTED_FIELD_PAIRS)
        with patch.object(type(self.mixin), "_stamp_encryption_key_version") as stamp:
            self.mixin.browse([1])._stamp_encrypted_payload([{"content": b"x"}])
        stamp.assert_not_called()

    def test_a_records_vals_length_mismatch_raises_instead_of_truncating(self):
        with self.assertRaises(ValueError):
            self.mixin.browse([1, 2])._stamp_encrypted_payload([{"content": b"x"}])
