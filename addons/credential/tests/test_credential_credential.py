import base64
import os
from unittest.mock import patch

from cryptography.fernet import Fernet
from psycopg.errors import UniqueViolation

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.base_encryption_mixin.models import (
    mixin_encryption as mixin_mod,
)


class TestCredentialCredential(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()

        cls.category_api_key = cls.env.ref("credential.credential_category_api_key")

        cls.credential = cls.env["credential.credential"].create(
            {
                "name": "Test Credential",
                "category_id": cls.category_api_key.id,
                "credential_value": "test_api_key_12345",
            }
        )

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_create_credential(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Test API Key",
                "category_id": self.category_api_key.id,
                "credential_value": "my_secret_key",
            }
        )

        self.assertEqual(credential.name, "Test API Key")
        self.assertEqual(credential.category_code, "api_key")
        self.assertTrue(credential.active)

    def test_credential_encryption(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Encrypted Test",
                "category_id": self.category_api_key.id,
                "credential_value": "my_bearer_token",
            }
        )

        self.assertTrue(credential.credential_value_encrypted)

        self.assertEqual(credential.credential_value, "my_bearer_token")

    def test_credential_decryption(self):
        original_value = "test_secret_value"

        credential = self.env["credential.credential"].create(
            {
                "name": "Decrypt Test",
                "category_id": self.category_api_key.id,
                "credential_value": original_value,
            }
        )

        credential.invalidate_recordset()
        credential_read = self.env["credential.credential"].browse(credential.id)

        self.assertEqual(credential_read.credential_value, original_value)

    def test_missing_encryption_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValidationError) as cm:
                self.env["credential.credential"]._get_encryption_key()

            self.assertIn("Encryption key not configured", str(cm.exception))

    def test_basic_auth_json_storage_missing_password_rejected(self):
        category_basic_auth = self.env.ref("credential.credential_category_basic_auth")
        with self.assertRaises(ValidationError) as cm:
            self.env["credential.credential"].create(
                {
                    "name": "basic auth missing password",
                    "category_id": category_basic_auth.id,
                    "username": "luis",
                },
            )
        self.assertIn("password", str(cm.exception))

    def test_basic_auth_json_storage_complete_accepted(self):
        category_basic_auth = self.env.ref("credential.credential_category_basic_auth")
        credential = self.env["credential.credential"].create(
            {
                "name": "basic auth complete",
                "category_id": category_basic_auth.id,
                "username": "luis",
                "password": "correct-horse",
            },
        )
        self.assertTrue(credential.id)
        self.assertEqual(credential.username, "luis")
        self.assertEqual(credential.password, "correct-horse")

    def test_migration_skips_rows_already_at_current_version(self):
        self.env.user.group_ids = [
            (
                4,
                self.env.ref("credential.group_credential_admin").id,
            )
        ]

        current_version = self.env[
            "credential.credential"
        ]._get_current_encryption_key_version()

        already_current = self.env["credential.credential"].create(
            {
                "name": "N8 already-current",
                "category_id": self.category_api_key.id,
                "credential_value": "sk-already-current",
            }
        )
        self.assertEqual(already_current.encryption_key_version, current_version)

        legacy = self.env["credential.credential"].create(
            {
                "name": "N8 legacy",
                "category_id": self.category_api_key.id,
                "credential_value": "sk-legacy",
            }
        )
        self.env.cr.execute(
            "UPDATE credential_credential SET encryption_key_version = 0 WHERE id = %s",
            [legacy.id],
        )
        legacy.invalidate_recordset(["encryption_key_version"])

        ciphertext_current_before = bytes(
            already_current.with_context(bin_size=False).credential_value_encrypted
        )
        ciphertext_legacy_before = bytes(
            legacy.with_context(bin_size=False).credential_value_encrypted
        )

        result = self.env["credential.credential"].action_migrate_encryption_keys()

        already_current.invalidate_recordset()
        self.assertEqual(
            bytes(
                already_current.with_context(bin_size=False).credential_value_encrypted
            ),
            ciphertext_current_before,
            "Already-current credential must not be re-encrypted",
        )

        legacy.invalidate_recordset()
        self.assertNotEqual(
            bytes(legacy.with_context(bin_size=False).credential_value_encrypted),
            ciphertext_legacy_before,
            "Legacy credential must be re-encrypted with the current key",
        )
        self.assertEqual(
            legacy.encryption_key_version,
            current_version,
            "Legacy credential must be stamped with the current key version",
        )

        self.assertGreaterEqual(result["skipped"], 1)
        self.assertGreaterEqual(result["migrated"], 1)
        self.assertEqual(result["failed"], 0)

    def test_form_open_emits_one_audit_log_entry(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "S2 audit log test",
                "category_id": self.category_api_key.id,
                "credential_value": "sk-s2-audit",
            }
        )
        baseline = self.env["credential.access.log"].search_count(
            [("credential_id", "=", credential.id)],
        )

        credential.invalidate_recordset()

        _ = credential.credential_value
        _ = credential.credential_data
        _ = credential.storage_method
        _ = credential.api_key
        _ = credential.api_secret
        _ = credential.bearer_token
        _ = credential.username
        _ = credential.password
        _ = credential.oauth_access_token
        _ = credential.oauth_refresh_token

        after = self.env["credential.access.log"].search_count(
            [("credential_id", "=", credential.id)],
        )
        self.assertEqual(
            after - baseline,
            1,
            f"Expected exactly 1 audit log entry for the form open, got "
            f"{after - baseline}",
        )

        credential.invalidate_recordset()
        _ = credential.credential_value
        after2 = self.env["credential.access.log"].search_count(
            [("credential_id", "=", credential.id)],
        )
        self.assertEqual(
            after2 - after,
            1,
            "A second (post-invalidation) read must emit a second entry",
        )

    def test_list_view_does_not_emit_audit_entries(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "S2 list view test",
                "category_id": self.category_api_key.id,
                "credential_value": "sk-listview",
            }
        )
        credential.invalidate_recordset()
        baseline = self.env["credential.access.log"].search_count(
            [("credential_id", "=", credential.id)],
        )
        _ = credential.name
        _ = credential.category_id
        _ = credential.health_status
        _ = credential.usage_count
        _ = credential.last_used_at
        after = self.env["credential.access.log"].search_count(
            [("credential_id", "=", credential.id)],
        )
        self.assertEqual(
            after - baseline,
            0,
            "List-view reads must not produce audit log entries",
        )

    def test_single_decrypt_per_form_open(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "M1 decrypt counter",
                "category_id": self.category_api_key.id,
                "credential_value": "sk-m1-regression-value",
            }
        )
        credential.invalidate_recordset()

        credential_cls = type(self.env["credential.credential"])
        real_decrypt_safe = credential_cls._decrypt_value_safe
        call_count = {"n": 0}

        def counting_decrypt_safe(self_, encrypted_value, default=False):
            call_count["n"] += 1
            return real_decrypt_safe(self_, encrypted_value, default=default)

        with patch.object(credential_cls, "_decrypt_value_safe", counting_decrypt_safe):
            value = credential.credential_value
            data = credential.credential_data
            method = credential.storage_method

        self.assertEqual(value, "sk-m1-regression-value")
        self.assertEqual(data, "{}")
        self.assertEqual(method, "simple")
        self.assertEqual(
            call_count["n"],
            1,
            f"Expected exactly 1 decrypt across the three reads, got {call_count['n']}",
        )

    def test_validation_errors_preserve_cause(self):
        with patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": "not-a-valid-fernet-key"}
        ):
            with self.assertRaises(ValidationError) as cm:
                self.env["credential.credential"]._get_encryption_key()
            self.assertIsNotNone(
                cm.exception.__cause__,
                "ValidationError from _get_encryption_key must chain the "
                "underlying cryptography exception via `from e`",
            )

    def test_missing_key_warning_rate_limit(self):
        credential_model = self.env["credential.credential"]

        mixin_mod._KEY_STATE["missing_warning_last_at"] = float("-inf")

        with patch.dict(os.environ, {}, clear=True):
            with self.assertLogs(
                "odoo.addons.base_encryption_mixin.models.mixin_encryption",
                level="WARNING",
            ) as first:
                result = credential_model._decrypt_value(b"gAAAAA-not-a-real-token")
            self.assertFalse(result)
            self.assertTrue(
                any("encryption key not configured" in m for m in first.output),
                f"First call must emit the warning, got: {first.output}",
            )

            latched_at = mixin_mod._KEY_STATE["missing_warning_last_at"]
            self.assertGreater(latched_at, 0.0)
            credential_model._decrypt_value(b"gAAAAA-not-a-real-token")
            self.assertEqual(
                mixin_mod._KEY_STATE["missing_warning_last_at"],
                latched_at,
                "Warning fired again inside cooldown window",
            )

            mixin_mod._KEY_STATE["missing_warning_last_at"] = latched_at - 10_000
            with self.assertLogs(
                "odoo.addons.base_encryption_mixin.models.mixin_encryption",
                level="WARNING",
            ) as second:
                credential_model._decrypt_value(b"gAAAAA-not-a-real-token")
            self.assertTrue(
                any("encryption key not configured" in m for m in second.output),
                "Warning must re-fire after cooldown expiry",
            )

    def test_unique_constraint(self):
        self.env["credential.credential"].create(
            {
                "name": "Unique Test",
                "category_id": self.category_api_key.id,
                "credential_value": "test",
            }
        )

        with mute_logger("odoo.db.cursor"):
            with self.assertRaises(UniqueViolation):
                self.env["credential.credential"].create(
                    {
                        "name": "Unique Test",
                        "category_id": self.category_api_key.id,
                        "credential_value": "test2",
                    }
                )

    def test_display_name(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Display Test",
                "category_id": self.category_api_key.id,
                "credential_value": "test",
            }
        )

        self.assertIn("Display Test", credential.display_name)
        self.assertIn("API Key", credential.display_name)

    def test_mark_as_used(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Usage Test",
                "category_id": self.category_api_key.id,
                "credential_value": "test",
            }
        )

        self.assertFalse(credential.last_used_at)

        credential.mark_as_used()

        self.assertTrue(credential.last_used_at)

    def test_multi_company_isolation(self):
        company2 = self.env["res.company"].create({"name": "Test Company 2"})
        company1 = self.env.company

        credential_company2 = (
            self.env["credential.credential"]
            .with_company(company2)
            .create(
                {
                    "name": "Company 2 Credential",
                    "category_id": self.category_api_key.id,
                    "credential_value": "test",
                    "company_id": company2.id,
                }
            )
        )

        company1_user = self.env["res.users"].create(
            {
                "name": "Company 1 Only",
                "login": "test_company1_only",
                "company_id": company1.id,
                "company_ids": [Command.set([company1.id])],
                "group_ids": [
                    Command.link(
                        self.env.ref("credential.group_credential_user").id,
                    ),
                ],
            }
        )

        credentials = (
            self.env["credential.credential"]
            .with_user(company1_user)
            .search([("name", "=", "Company 2 Credential")])
        )

        self.assertNotIn(credential_company2, credentials)

    def test_category_code_stored(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Category Code Test",
                "category_id": self.category_api_key.id,
                "credential_value": "test",
            }
        )

        self.assertEqual(credential.category_code, "api_key")


class TestCredentialCategory(TransactionCase):
    def test_default_categories_exist(self):
        api_key = self.env.ref("credential.credential_category_api_key")
        oauth2 = self.env.ref("credential.credential_category_oauth2")

        self.assertEqual(api_key.code, "api_key")
        self.assertEqual(oauth2.code, "oauth2")

    def test_category_unique_code(self):
        with mute_logger("odoo.db.cursor"):
            with self.assertRaises(UniqueViolation):
                self.env["credential.category"].create(
                    {
                        "name": "Duplicate API Key",
                        "code": "api_key",
                        "storage_hint": "simple",
                    }
                )

    def test_credential_count(self):
        with patch.dict(
            os.environ,
            {"ODOO_API_ENCRYPTION_KEY": "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="},
        ):
            category = self.env.ref("credential.credential_category_custom")

            initial_count = category.credential_count

            self.env["credential.credential"].create(
                {
                    "name": "Count Test",
                    "category_id": category.id,
                    "credential_value": "test",
                }
            )

            category.invalidate_recordset()
            self.assertEqual(category.credential_count, initial_count + 1)


class TestCredentialSecurityValidations(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()

        cls.category_custom = cls.env.ref("credential.credential_category_custom")

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_credential_value_size_limit(self):
        large_value = "x" * 10000

        with self.assertRaises(ValidationError) as cm:
            self.env["credential.credential"].create(
                {
                    "name": "Large Value Test",
                    "category_id": self.category_custom.id,
                    "credential_value": large_value,
                }
            )

        self.assertIn("exceeds maximum size", str(cm.exception))

    def test_credential_data_size_limit(self):
        large_data = '{"key": "' + "x" * 70000 + '"}'

        with self.assertRaises(ValidationError) as cm:
            self.env["credential.credential"].create(
                {
                    "name": "Large Data Test",
                    "category_id": self.category_custom.id,
                    "credential_data": large_data,
                }
            )

        self.assertIn("exceeds maximum size", str(cm.exception))

    def test_credential_data_nesting_depth_limit(self):
        nested = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "level5": {
                                "level6": {
                                    "level7": {
                                        "level8": {
                                            "level9": {"level10": {"level11": "deep"}}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        deep_json = __import__("json").dumps(nested)

        with self.assertRaises(ValidationError) as cm:
            self.env["credential.credential"].create(
                {
                    "name": "Deep Nesting Test",
                    "category_id": self.category_custom.id,
                    "credential_data": deep_json,
                }
            )

        self.assertIn("nesting depth", str(cm.exception))

    def test_notes_secret_detection_password(self):
        with self.assertLogs(
            "odoo.addons.credential.models.credential_credential",
            level="WARNING",
        ) as cm:
            credential = self.env["credential.credential"].create(
                {
                    "name": "Password in Notes Test",
                    "category_id": self.category_custom.id,
                    "credential_value": "safe_value",
                    "notes": "The password=MySecretPass123 for this service",
                }
            )
        self.assertTrue(credential.id, "Save must not be blocked")
        self.assertTrue(
            any("Possible secret pattern" in m for m in cm.output),
            f"Expected warning about secret pattern, got: {cm.output}",
        )

    def test_notes_secret_detection_api_key(self):
        with self.assertLogs(
            "odoo.addons.credential.models.credential_credential",
            level="WARNING",
        ) as cm:
            credential = self.env["credential.credential"].create(
                {
                    "name": "API Key in Notes Test",
                    "category_id": self.category_custom.id,
                    "credential_value": "safe_value",
                    "notes": "Use api_key: sk-1234567890abcdef",
                }
            )
        self.assertTrue(credential.id, "Save must not be blocked")
        self.assertTrue(
            any("Possible secret pattern" in m for m in cm.output),
            f"Expected warning about secret pattern, got: {cm.output}",
        )

    def test_notes_safe_content_allowed(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Safe Notes Test",
                "category_id": self.category_custom.id,
                "credential_value": "test_value",
                "notes": "This is documentation about how to use the API.",
            }
        )

        self.assertTrue(credential.id)
        self.assertEqual(
            credential.notes, "This is documentation about how to use the API."
        )


class TestAuditLogImmutability(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()

        cls.category_api_key = cls.env.ref("credential.credential_category_api_key")

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_audit_log_cannot_be_modified(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Audit Test Credential",
                "category_id": self.category_api_key.id,
                "credential_value": "test_key",
            }
        )

        log = self.env["credential.access.log"].search(
            [("credential_id", "=", credential.id)], limit=1
        )

        self.assertTrue(log, "creating a credential must write an access-log row")

        with self.assertRaises(UserError) as cm:
            log.write({"operation": "delete"})

        self.assertIn("cannot be modified", str(cm.exception))

    def test_audit_log_cannot_be_deleted(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Delete Test Credential",
                "category_id": self.category_api_key.id,
                "credential_value": "test_key",
            }
        )

        log = self.env["credential.access.log"].search(
            [("credential_id", "=", credential.id)], limit=1
        )

        self.assertTrue(log, "creating a credential must write an access-log row")

        with self.assertRaises(UserError) as cm:
            log.unlink()

        self.assertIn("cannot be deleted", str(cm.exception))

    def test_audit_log_cleanup_bypass_needs_both_halves(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Cleanup Test Credential",
                "category_id": self.category_api_key.id,
                "credential_value": "test_key",
            }
        )

        log = self.env["credential.access.log"].search(
            [("credential_id", "=", credential.id)], limit=1
        )

        self.assertTrue(log, "creating a credential must write an access-log row")

        with self.assertRaises(UserError) as cm:
            log.unlink()
        self.assertIn("cannot be deleted", str(cm.exception))

        log.with_context(_credential_log_cleanup_bypass=True).unlink()
        self.assertFalse(log.exists())

    def test_credential_delete_is_audited_and_logs_survive(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Delete Audit Cred",
                "category_id": self.category_api_key.id,
                "credential_value": "sk-delete-audit",
            }
        )
        cred_id = credential.id
        cred_name = credential.name

        credential.invalidate_recordset()
        _ = credential.credential_value

        pre_delete = self.env["credential.access.log"].search(
            [("credential_id", "=", cred_id)],
        )
        self.assertTrue(pre_delete, "Expected access log(s) before delete")

        credential.unlink()

        surviving = self.env["credential.access.log"].search(
            [("credential_name", "=", cred_name)],
        )
        self.assertTrue(
            surviving,
            "Access-log history must survive credential deletion",
        )
        for log in surviving:
            self.assertFalse(
                log.credential_id,
                "credential_id must be nulled (set null) after delete",
            )
            self.assertEqual(log.credential_name, cred_name)

        self.assertTrue(
            surviving.filtered(lambda log: log.operation == "delete"),
            "unlink() must emit a 'delete' audit entry",
        )


class TestCredentialStatsProtection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()

        cls.category_api_key = cls.env.ref("credential.credential_category_api_key")

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_cannot_modify_usage_count_directly(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Stats Protection Test",
                "category_id": self.category_api_key.id,
                "credential_value": "test_key",
            }
        )

        with self.assertRaises(ValidationError) as cm:
            credential.write({"usage_count": 999})

        self.assertIn("Cannot modify protected statistics", str(cm.exception))

    def test_cannot_modify_health_status_directly(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Health Status Test",
                "category_id": self.category_api_key.id,
                "credential_value": "test_key",
            }
        )

        with self.assertRaises(ValidationError) as cm:
            credential.write({"health_status": "error"})

        self.assertIn("Cannot modify protected statistics", str(cm.exception))

    def test_cannot_seed_usage_count_at_create(self):
        with self.assertRaises(ValidationError) as cm:
            self.env["credential.credential"].create(
                {
                    "name": "Seeded stats test",
                    "category_id": self.category_api_key.id,
                    "credential_value": "test_key",
                    "usage_count": 9999,
                },
            )
        self.assertIn("Cannot seed protected statistics", str(cm.exception))

    def test_cannot_seed_health_status_at_create(self):
        with self.assertRaises(ValidationError) as cm:
            self.env["credential.credential"].create(
                {
                    "name": "Seeded health test",
                    "category_id": self.category_api_key.id,
                    "credential_value": "test_key",
                    "health_status": "healthy",
                },
            )
        self.assertIn("Cannot seed protected statistics", str(cm.exception))

    def test_internal_context_allows_seeding_stats(self):
        key = self.env["credential.credential"]._INTERNAL_STATS_UPDATE_KEY
        credential = (
            self.env["credential.credential"]
            .with_context(**{key: True})
            .create(
                {
                    "name": "Internal seed test",
                    "category_id": self.category_api_key.id,
                    "credential_value": "test_key",
                    "usage_count": 42,
                },
            )
        )
        self.assertEqual(credential.usage_count, 42)

    def test_increment_usage_works(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Increment Usage Test",
                "category_id": self.category_api_key.id,
                "credential_value": "test_key",
            }
        )

        initial_count = credential.usage_count

        credential.increment_usage(success=True)

        self.assertEqual(credential.usage_count, initial_count + 1)
        self.assertEqual(credential.success_count, 1)

    def test_mark_as_used_works(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Mark Used Test",
                "category_id": self.category_api_key.id,
                "credential_value": "test_key",
            }
        )

        self.assertFalse(credential.last_used_at)

        credential.mark_as_used()

        self.assertTrue(credential.last_used_at)


class TestEncryptionKeyRotation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.old_key = Fernet.generate_key().decode()
        cls.new_key = Fernet.generate_key().decode()

        cls.category_api_key = cls.env.ref("credential.credential_category_api_key")

    def test_key_version_detection_no_old_keys(self):
        with patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": self.new_key}, clear=True
        ):
            self.env["credential.credential"]._invalidate_key_version_cache()

            version = self.env[
                "credential.credential"
            ]._get_current_encryption_key_version()
            self.assertEqual(version, 1)

    def test_key_version_detection_with_old_keys(self):
        env_vars = {
            "ODOO_API_ENCRYPTION_KEY": self.new_key,
            "ODOO_API_ENCRYPTION_KEY_V1": self.old_key,
        }

        with patch.dict(os.environ, env_vars, clear=True):
            self.env["credential.credential"]._invalidate_key_version_cache()

            version = self.env[
                "credential.credential"
            ]._get_current_encryption_key_version()
            self.assertEqual(version, 2)

    def test_decrypt_with_old_key_fallback(self):
        with patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": self.old_key}, clear=True
        ):
            self.env["credential.credential"]._invalidate_key_version_cache()

            credential = self.env["credential.credential"].create(
                {
                    "name": "Old Key Credential",
                    "category_id": self.category_api_key.id,
                    "credential_value": "secret_value_123",
                }
            )
            credential_id = credential.id

        env_vars = {
            "ODOO_API_ENCRYPTION_KEY": self.new_key,
            "ODOO_API_ENCRYPTION_KEY_V1": self.old_key,
        }

        with patch.dict(os.environ, env_vars, clear=True):
            self.env["credential.credential"]._invalidate_key_version_cache()

            credential = self.env["credential.credential"].browse(credential_id)
            credential.invalidate_recordset()

            decrypted = credential.credential_value
            self.assertEqual(decrypted, "secret_value_123")

    def test_key_version_cache_invalidation(self):
        with patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": self.new_key}, clear=True
        ):
            self.env["credential.credential"]._invalidate_key_version_cache()
            version1 = self.env[
                "credential.credential"
            ]._get_current_encryption_key_version()

            version2 = self.env[
                "credential.credential"
            ]._get_current_encryption_key_version()

            self.assertEqual(version1, version2)

            with patch.dict(
                os.environ,
                {
                    "ODOO_API_ENCRYPTION_KEY": self.new_key,
                    "ODOO_API_ENCRYPTION_KEY_V1": self.old_key,
                },
                clear=True,
            ):
                self.env["credential.credential"]._invalidate_key_version_cache()
                version3 = self.env[
                    "credential.credential"
                ]._get_current_encryption_key_version()

                self.assertEqual(version3, 2)


class TestSimpleToJsonStorageTransition(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()
        cls.category_api_key = cls.env.ref("credential.credential_category_api_key")
        cls.category_custom = cls.env.ref("credential.credential_category_custom")

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_simple_value_survives_after_setting_json_accessor(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "simple-then-json",
                "category_id": self.category_api_key.id,
                "credential_value": "SK-simple-original",
            }
        )
        self.assertEqual(cred.credential_value, "SK-simple-original")

        try:
            cred.write({"bearer_token": "tok-added-later"})
        except ValidationError:
            return

        cred.invalidate_recordset(
            ["cached_plaintext", "credential_value", "credential_data"]
        )

        value = cred.credential_value
        self.assertEqual(
            value,
            "SK-simple-original",
            msg=(
                "After writing bearer_token on a simple-storage credential, "
                "credential_value no longer returns the original string. "
                f"Got: {value!r}. This indicates the simple value was "
                "overwritten by a JSON blob during the inverse chain."
            ),
        )

    def test_simple_value_is_not_a_json_dump_after_transition(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "simple-then-json-fingerprint",
                "category_id": self.category_api_key.id,
                "credential_value": "SK-fingerprint",
            }
        )

        try:
            cred.write({"bearer_token": "tok-xyz"})
        except ValidationError:
            return

        cred.invalidate_recordset(
            ["cached_plaintext", "credential_value", "credential_data"]
        )

        value = cred.credential_value or ""
        self.assertNotIn(
            '"value":',
            value,
            msg=(
                "credential_value contains a JSON 'value' key, which is the "
                "exact shape produced by get_credential_dict's fallback "
                "branch when a simple credential is promoted to JSON. "
                f"Got: {value!r}"
            ),
        )
        self.assertNotIn(
            '"bearer_token":',
            value,
            msg=(
                "credential_value contains a JSON 'bearer_token' key; "
                "the simple-value accessor is leaking the JSON blob. "
                f"Got: {value!r}"
            ),
        )

    def test_storage_method_sealed_to_simple_on_first_write(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "seal-simple",
                "category_id": self.category_api_key.id,
                "credential_value": "SK-sealed",
            }
        )
        self.assertEqual(cred.storage_method, "simple")
        self.assertEqual(cred.credential_value, "SK-sealed")

    def test_storage_method_sealed_to_json_on_first_json_accessor(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "seal-json",
                "category_id": self.category_custom.id,
                "bearer_token": "tok-sealed",
            }
        )
        self.assertEqual(cred.storage_method, "json")
        self.assertEqual(cred.bearer_token, "tok-sealed")
        self.assertFalse(cred.credential_value)

    def test_storage_method_rejects_simple_then_json(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "reject-simple-to-json",
                "category_id": self.category_api_key.id,
                "credential_value": "SK-locked",
            }
        )
        with self.assertRaises(ValidationError):
            cred.write({"bearer_token": "tok-should-fail"})
        cred.invalidate_recordset(
            ["cached_plaintext", "credential_value", "credential_data"]
        )
        self.assertEqual(cred.credential_value, "SK-locked")
        self.assertEqual(cred.storage_method, "simple")

    def test_storage_method_rejects_json_then_simple(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "reject-json-to-simple",
                "category_id": self.category_custom.id,
                "bearer_token": "tok-locked",
            }
        )
        with self.assertRaises(ValidationError):
            cred.write({"credential_value": "SK-should-fail"})
        cred.invalidate_recordset(
            ["cached_plaintext", "credential_value", "credential_data"]
        )
        self.assertEqual(cred.storage_method, "json")
        self.assertEqual(cred.bearer_token, "tok-locked")

    def test_storage_method_cannot_be_written_directly(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "protect-storage-method",
                "category_id": self.category_api_key.id,
                "credential_value": "SK-protected",
            }
        )
        with self.assertRaises(ValidationError):
            cred.write({"storage_method": "json"})
        with self.assertRaises(ValidationError):
            self.env["credential.credential"].create(
                {
                    "name": "seed-storage-method",
                    "category_id": self.category_api_key.id,
                    "storage_method": "json",
                }
            )

    def test_storage_method_none_on_empty_create(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "empty-no-payload",
                "category_id": self.category_custom.id,
            }
        )
        self.assertEqual(cred.storage_method, "none")


class TestActionTestEncryptionKeys(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()
        cls.env.user.group_ids |= cls.env.ref("credential.group_credential_admin")
        cls.category_api_key = cls.env.ref("credential.credential_category_api_key")
        cls.cred_a = cls.env["credential.credential"].create(
            {
                "name": "probe-target",
                "category_id": cls.category_api_key.id,
                "credential_value": "value-a",
            }
        )
        cls.cred_b = cls.env["credential.credential"].create(
            {
                "name": "unrelated-neighbour",
                "category_id": cls.category_api_key.id,
                "credential_value": "value-b",
            }
        )

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_action_scope_is_self_only(self):
        result = self.cred_a.action_test_encryption_keys()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["current_key"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(result["details"]), 1)
        self.assertEqual(result["details"][0]["id"], self.cred_a.id)

    def test_action_multi_record_scope(self):
        both = self.cred_a | self.cred_b
        result = both.action_test_encryption_keys()
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["current_key"], 2)
        ids = {d["id"] for d in result["details"]}
        self.assertEqual(ids, {self.cred_a.id, self.cred_b.id})

    def test_action_empty_recordset(self):
        result = (
            self.env["credential.credential"].browse([]).action_test_encryption_keys()
        )
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["details"], [])


class TestBinaryWireFormatCompat(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()
        cls.Model = cls.env["credential.credential"]

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_canonical_shape_roundtrip(self):
        plaintext = b"binary-payload-bytes-123"
        upload = base64.b64encode(plaintext)
        ciphertext = self.Model._encrypt_binary_value(upload)
        self.assertTrue(ciphertext.startswith(b"gAAAAA"))
        decrypted_b64 = self.Model._decrypt_binary_value(ciphertext)
        self.assertEqual(base64.b64decode(decrypted_b64), plaintext)

    def test_legacy_double_base64_shape_still_decrypts(self):
        plaintext = b"legacy-pkcs12-bytes-xyz"
        cipher = Fernet(self.test_key)
        fernet_token = cipher.encrypt(plaintext)
        legacy_stored = base64.b64encode(fernet_token)
        decrypted_b64 = self.Model._decrypt_binary_value(legacy_stored)
        self.assertEqual(base64.b64decode(decrypted_b64), plaintext)

    def test_canonical_and_legacy_shapes_yield_same_plaintext(self):
        plaintext = b"shared-plaintext"
        cipher = Fernet(self.test_key)
        fernet_token = cipher.encrypt(plaintext)
        legacy = base64.b64encode(fernet_token)
        from_canonical = base64.b64decode(
            self.Model._decrypt_binary_value(fernet_token)
        )
        from_legacy = base64.b64decode(self.Model._decrypt_binary_value(legacy))
        self.assertEqual(from_canonical, plaintext)
        self.assertEqual(from_legacy, plaintext)

    def test_garbage_input_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            self.Model._decrypt_binary_value(b"\x00\x01\x02not-valid")

    def test_char_and_binary_paths_agree_on_canonical_shape(self):
        plaintext_str = "string-credential"
        cipher = Fernet(self.test_key)
        token = cipher.encrypt(plaintext_str.encode("utf-8"))
        self.assertEqual(self.Model._decrypt_value(token), plaintext_str)
        legacy = base64.b64encode(token)
        self.assertEqual(self.Model._decrypt_value(legacy), plaintext_str)

    def test_cron_cleanup_old_logs_works_under_non_superuser(self):
        admin_group = self.env.ref("credential.group_credential_admin")
        non_su_user = self.env["res.users"].create(
            {
                "name": "Non-Super Cron Runner",
                "login": "non-su-cron@test",
                "group_ids": [Command.link(admin_group.id)],
            }
        )

        cred = self.Model.create(
            {
                "name": "audit-source-for-cleanup",
                "category_id": self.env.ref(
                    "credential.credential_category_api_key"
                ).id,
                "credential_value": "v1",
            }
        )
        cred._log_access("read")
        self.env.cr.execute(
            "UPDATE credential_access_log SET timestamp = %s WHERE credential_id = %s",
            ["2000-01-01 00:00:00", cred.id],
        )

        log = self.env["credential.access.log"].with_user(non_su_user)
        deleted = log.cron_cleanup_old_logs(retention_days=1)
        self.assertGreaterEqual(
            deleted,
            1,
            "cron_cleanup_old_logs must clean up old rows even when "
            "invoked by a non-superuser cron runner",
        )


class TestOAuthClientCredentials(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_key = Fernet.generate_key().decode()
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()
        cls.env["credential.credential"]._invalidate_key_version_cache()
        cls.category_oauth2 = cls.env.ref("credential.credential_category_oauth2")

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_client_accessors_roundtrip(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "OAuth App",
                "category_id": self.category_oauth2.id,
                "oauth_client_id": "my-app-id",
                "oauth_client_secret": "s3cr3t-value",
            }
        )
        self.assertTrue(credential.credential_value_encrypted)
        credential.invalidate_recordset()
        reread = self.env["credential.credential"].browse(credential.id)
        self.assertEqual(reread.oauth_client_id, "my-app-id")
        self.assertEqual(reread.oauth_client_secret, "s3cr3t-value")

    def test_oauth2_client_secret_alone_satisfies_validator(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Pre-authorization OAuth App",
                "category_id": self.category_oauth2.id,
                "oauth_client_secret": "s3cr3t-value",
            }
        )
        self.assertTrue(credential.id)
        self.assertFalse(credential.oauth_access_token)

    def test_oauth2_access_token_alone_still_valid(self):
        credential = self.env["credential.credential"].create(
            {
                "name": "Token-only OAuth",
                "category_id": self.category_oauth2.id,
                "oauth_access_token": "tok-123",
            }
        )
        self.assertTrue(credential.id)

    def test_oauth2_without_token_or_secret_rejected(self):
        with self.assertRaises(ValidationError) as cm:
            self.env["credential.credential"].create(
                {
                    "name": "Empty OAuth",
                    "category_id": self.category_oauth2.id,
                    "oauth_client_id": "id-without-secret",
                }
            )
        self.assertIn("access token or a client secret", str(cm.exception))

    def test_rotation_preserves_client_secret(self):
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        self.env.user.group_ids = [
            Command.link(self.env.ref("credential.group_credential_admin").id)
        ]

        with patch.dict(os.environ, {"ODOO_API_ENCRYPTION_KEY": old_key}, clear=True):
            self.env["credential.credential"]._invalidate_key_version_cache()
            credential = self.env["credential.credential"].create(
                {
                    "name": "Rotating OAuth App",
                    "category_id": self.category_oauth2.id,
                    "oauth_client_secret": "rotate-me",
                }
            )
            credential_id = credential.id

        env_vars = {
            "ODOO_API_ENCRYPTION_KEY": new_key,
            "ODOO_API_ENCRYPTION_KEY_V1": old_key,
        }
        with patch.dict(os.environ, env_vars, clear=True):
            self.env["credential.credential"]._invalidate_key_version_cache()
            self.env["credential.credential"].action_migrate_encryption_keys()

        with patch.dict(os.environ, {"ODOO_API_ENCRYPTION_KEY": new_key}, clear=True):
            self.env["credential.credential"]._invalidate_key_version_cache()
            credential = self.env["credential.credential"].browse(credential_id)
            credential.invalidate_recordset()
            self.assertEqual(credential.oauth_client_secret, "rotate-me")
