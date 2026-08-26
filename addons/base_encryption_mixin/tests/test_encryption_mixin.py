"""The mixin's contract, asserted without a credential in sight.

This module exists because four of the five models that encrypt fields through
it are not credentials -- a company, a user, an X.509 certificate and its key --
and every one of them used to install a credential vault, a rate limiter, an
inbound gate and a session cache to get a Fernet round-trip. These tests
therefore use no consumer at all: what they can reach on a bare install is
exactly what the module promises on its own.
"""

import base64
import os
from unittest.mock import patch

from cryptography.fernet import Fernet

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

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

    def test_the_walker_reports_consumers_never_the_mixin(self):
        discovered = self.mixin._get_encryption_migration_models()
        self.assertNotIn("mixin.encryption", discovered)
        for name in discovered:
            self.assertFalse(
                self.env[name]._abstract,
                f"{name} is abstract and cannot hold rows to re-encrypt",
            )

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
