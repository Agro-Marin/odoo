"""Tests for credential.credential model."""

import base64
import datetime as dt
import os
from unittest.mock import patch

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from psycopg.errors import UniqueViolation

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.base_credential_manager.models.mixins import (
    credential_encryption_mixin as mixin_mod,
)


class TestCredentialCredential(TransactionCase):
    """Test credential model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Mock encryption key for tests (must be valid 32-byte Fernet key)
        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()

        # Get API Key category
        cls.category_api_key = cls.env.ref(
            "base_credential_manager.credential_category_api_key"
        )
        cls.category_certificate = cls.env.ref(
            "base_credential_manager.credential_category_certificate"
        )

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
        """Test creating a credential."""
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
        """Test that credential values are encrypted."""
        credential = self.env["credential.credential"].create(
            {
                "name": "Encrypted Test",
                "category_id": self.category_api_key.id,
                "credential_value": "my_bearer_token",
            }
        )

        # Encrypted value should exist
        self.assertTrue(credential.credential_value_encrypted)

        # Decrypted value should match original
        self.assertEqual(credential.credential_value, "my_bearer_token")

    def test_credential_decryption(self):
        """Test that encrypted credentials can be decrypted."""
        original_value = "test_secret_value"

        credential = self.env["credential.credential"].create(
            {
                "name": "Decrypt Test",
                "category_id": self.category_api_key.id,
                "credential_value": original_value,
            }
        )

        # Read from database
        credential.invalidate_recordset()
        credential_read = self.env["credential.credential"].browse(credential.id)

        self.assertEqual(credential_read.credential_value, original_value)

    def test_missing_encryption_key(self):
        """Test that missing encryption key raises error."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValidationError) as cm:
                self.env["credential.credential"]._get_encryption_key()

            self.assertIn("Encryption key not configured", str(cm.exception))

    def test_basic_auth_json_storage_missing_password_rejected(self):
        """M4 regression: JSON-storage validator checks specific keys.

        Previously _validate_required_fields_for_category used a blob-
        existence shortcut: if credential_value_encrypted was non-empty,
        the field list was cleared regardless of what keys were actually
        present in the decrypted JSON. The fix parses the payload and
        verifies each required field individually.

        basic_auth requires username+password. Setting only username via
        the JSON-storage path must now fail instead of sneaking through
        because the blob exists.
        """
        category_basic_auth = self.env.ref(
            "base_credential_manager.credential_category_basic_auth"
        )
        with self.assertRaises(ValidationError) as cm:
            self.env["credential.credential"].create(
                {
                    "name": "basic auth missing password",
                    "category_id": category_basic_auth.id,
                    # Only set username — goes into credential_data JSON via
                    # the _inverse_credential_field_username chain. Blob exists
                    # but the "password" key is missing.
                    "username": "luis",
                },
            )
        self.assertIn("password", str(cm.exception))

    def test_basic_auth_json_storage_complete_accepted(self):
        """Positive M4 case: both username and password in JSON → pass."""
        category_basic_auth = self.env.ref(
            "base_credential_manager.credential_category_basic_auth"
        )
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
        """action_migrate_encryption_keys must not re-encrypt current rows (N8).

        Re-running the migration after a successful rotation should be a
        near-no-op: credentials already stamped with the current key
        version are filtered out by the search domain, so ``migrated``
        counts only the legacy / pre-rotation rows. Re-encrypting a row
        that's already on the current key is wasted work and would
        unnecessarily change its ciphertext (invalidating session caches
        keyed on credential_hash).
        """
        # Put the current user in the admin group so the action is callable.
        self.env.user.group_ids = [
            (
                4,
                self.env.ref("base_credential_manager.group_credential_admin").id,
            )
        ]

        current_version = self.env[
            "credential.credential"
        ]._get_current_encryption_key_version()

        # Fresh record — create() stamps encryption_key_version = current.
        already_current = self.env["credential.credential"].create(
            {
                "name": "N8 already-current",
                "category_id": self.category_api_key.id,
                "credential_value": "sk-already-current",
            }
        )
        self.assertEqual(already_current.encryption_key_version, current_version)

        # Legacy-style record — pretend it was encrypted by a previous key
        # version. Use a raw SQL UPDATE so the test bypasses the field's
        # readonly flag.
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

        # The already-current row was NOT re-encrypted — ciphertext unchanged.
        already_current.invalidate_recordset()
        self.assertEqual(
            bytes(
                already_current.with_context(bin_size=False).credential_value_encrypted
            ),
            ciphertext_current_before,
            "Already-current credential must not be re-encrypted",
        )

        # The legacy row WAS re-encrypted — ciphertext differs (Fernet IV is
        # random, so even same-plaintext re-encryption produces new bytes).
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

        # The return payload distinguishes skipped from migrated.
        self.assertGreaterEqual(result["skipped"], 1)
        self.assertGreaterEqual(result["migrated"], 1)
        self.assertEqual(result["failed"], 0)

    def test_form_open_emits_one_audit_log_entry(self):
        """Reading plaintext-derived fields produces exactly one audit row (S2).

        Regression: the JSON-accessor compute path used to bypass audit
        logging entirely, so a system admin opening a credential form read
        up to seven plaintext secrets with zero credential.access.log
        entries. Audit logging is now centralized in _compute_cached_plaintext,
        which is memoized per (record, transaction) by Odoo's compute cache
        and thus fires exactly once per form open per credential.
        """
        credential = self.env["credential.credential"].create(
            {
                "name": "S2 audit log test",
                "category_id": self.category_api_key.id,
                "credential_value": "sk-s2-audit",
            }
        )
        # Baseline audit log rows for this credential (the create may emit
        # its own entries via the inverse chain; snapshot after create).
        baseline = self.env["credential.access.log"].search_count(
            [("credential_id", "=", credential.id)],
        )

        # Force a clean cache so the compute has to actually fire.
        credential.invalidate_recordset()

        # Simulate a form open: read the simple-value field AND all seven
        # JSON-accessor fields in the same transaction.
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

        # Second form open in a fresh compute pass → one more entry.
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
        """Reading only non-plaintext fields produces zero audit rows (S2).

        The credential list view displays name / category / health / usage
        stats — never plaintext. Opening the list must not flood the audit
        log with 'read' entries for every credential on screen.
        """
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
        # Read only list-view-like fields.
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
        """credential_value, credential_data, storage_method share one decrypt (M1).

        Regression: the three compute methods used to each call _decrypt_value
        against the same ciphertext, so opening a credential form caused
        three Fernet.decrypt operations. They now all depend on a private
        cached_plaintext field that decrypts once and is memoized by Odoo's
        compute cache for the transaction.
        """
        credential = self.env["credential.credential"].create(
            {
                "name": "M1 decrypt counter",
                "category_id": self.category_api_key.id,
                "credential_value": "sk-m1-regression-value",
            }
        )
        # Flush so the create-time inverse decrypt cycle is done and the
        # compute cache for the read below is clean.
        credential.invalidate_recordset()

        credential_cls = type(self.env["credential.credential"])
        real_decrypt_safe = credential_cls._decrypt_value_safe
        call_count = {"n": 0}

        def counting_decrypt_safe(self_, encrypted_value, default=False):
            call_count["n"] += 1
            return real_decrypt_safe(self_, encrypted_value, default=default)

        with patch.object(credential_cls, "_decrypt_value_safe", counting_decrypt_safe):
            # Read all three plaintext-derived fields in one pass.
            value = credential.credential_value
            data = credential.credential_data
            method = credential.storage_method

        self.assertEqual(value, "sk-m1-regression-value")
        self.assertEqual(data, "{}")  # raw simple value, not JSON
        self.assertEqual(method, "simple")
        self.assertEqual(
            call_count["n"],
            1,
            f"Expected exactly 1 decrypt across the three reads, got {call_count['n']}",
        )

    def test_validation_errors_preserve_cause(self):
        """Raised ValidationErrors must chain the underlying exception (N2).

        Regression: the mixin used to `raise ValidationError(...)` without
        `from e` in six places, losing the original traceback and making
        production diagnosis harder. Each ValidationError raised from an
        except-block must now carry .__cause__.
        """
        # Invalid Fernet key format: env var is set, but value is garbage.
        # Hits _get_encryption_key's except block at the bottom of the file.
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
        """Missing-key warning in _decrypt_value re-fires after cooldown (N1).

        Regression: a class-level boolean latch used to silence the warning
        forever after the first occurrence, hiding recovery/re-break cycles
        from operators. The latch is now a (last_at, cooldown) pair stored
        at module level (shared across every mixin consumer).
        """
        credential_model = self.env["credential.credential"]

        # Reset the module-level latch so this test is order-independent.
        # Use float("-inf") instead of 0.0: on a fresh CI container
        # time.monotonic() can be < 300 s, making now - 0.0 < 300 trigger
        # the cooldown and suppress the warning before it fires.
        # float("-inf") guarantees now - (-inf) = +inf > 300 always.
        mixin_mod._KEY_STATE["missing_warning_last_at"] = float("-inf")

        with patch.dict(os.environ, {}, clear=True):
            with self.assertLogs(
                "odoo.addons.base_credential_manager.models.mixins.credential_encryption_mixin",
                level="WARNING",
            ) as first:
                result = credential_model._decrypt_value(b"gAAAAA-not-a-real-token")
            self.assertFalse(result)
            self.assertTrue(
                any("encryption key not configured" in m for m in first.output),
                f"First call must emit the warning, got: {first.output}",
            )

            # Immediate second call — still inside cooldown — must NOT re-warn.
            latched_at = mixin_mod._KEY_STATE["missing_warning_last_at"]
            self.assertGreater(latched_at, 0.0)
            credential_model._decrypt_value(b"gAAAAA-not-a-real-token")
            self.assertEqual(
                mixin_mod._KEY_STATE["missing_warning_last_at"],
                latched_at,
                "Warning fired again inside cooldown window",
            )

            # Simulate cooldown expiry by rewinding the latch, then re-assert.
            mixin_mod._KEY_STATE["missing_warning_last_at"] = latched_at - 10_000
            with self.assertLogs(
                "odoo.addons.base_credential_manager.models.mixins.credential_encryption_mixin",
                level="WARNING",
            ) as second:
                credential_model._decrypt_value(b"gAAAAA-not-a-real-token")
            self.assertTrue(
                any("encryption key not configured" in m for m in second.output),
                "Warning must re-fire after cooldown expiry",
            )

    def test_unique_constraint(self):
        """Test that credential names are unique per company."""
        # Create first credential
        self.env["credential.credential"].create(
            {
                "name": "Unique Test",
                "category_id": self.category_api_key.id,
                "credential_value": "test",
            }
        )

        # Try to create duplicate (should fail due to unique index)
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
        """Test display name computation."""
        credential = self.env["credential.credential"].create(
            {
                "name": "Display Test",
                "category_id": self.category_api_key.id,
                "credential_value": "test",
            }
        )

        # Display name should include name and category
        self.assertIn("Display Test", credential.display_name)
        self.assertIn("API Key", credential.display_name)

    def test_mark_as_used(self):
        """Test marking credential as used."""
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
        """Test that credentials are isolated by company."""
        # Create second company
        company2 = self.env["res.company"].create({"name": "Test Company 2"})
        company1 = self.env.company

        # Create credential in second company
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

        # The ir.rule `company_id in company_ids + [False]` references
        # env.user.company_ids. Admin has access to all companies, so a plain
        # search would find company2 records. Create a scoped user whose
        # company_ids only contains company1.
        company1_user = self.env["res.users"].create(
            {
                "name": "Company 1 Only",
                "login": "test_company1_only",
                "company_id": company1.id,
                "company_ids": [(6, 0, [company1.id])],
                "group_ids": [
                    (
                        4,
                        self.env.ref(
                            "base_credential_manager.group_credential_user"
                        ).id,
                    ),
                ],
            }
        )

        credentials = (
            self.env["credential.credential"]
            .with_user(company1_user)
            .search([("name", "=", "Company 2 Credential")])
        )

        # Due to record rules, should not find it (different company)
        self.assertNotIn(credential_company2, credentials)

    def test_category_code_stored(self):
        """Test that category code is stored as related field."""
        credential = self.env["credential.credential"].create(
            {
                "name": "Category Code Test",
                "category_id": self.category_api_key.id,
                "credential_value": "test",
            }
        )

        self.assertEqual(credential.category_code, "api_key")


class TestCredentialCategory(TransactionCase):
    """Test credential category model."""

    def test_default_categories_exist(self):
        """Test that default categories are created."""
        api_key = self.env.ref("base_credential_manager.credential_category_api_key")
        certificate = self.env.ref(
            "base_credential_manager.credential_category_certificate"
        )

        self.assertEqual(api_key.code, "api_key")
        self.assertEqual(certificate.code, "certificate")

    def test_category_unique_code(self):
        """Test that category codes are unique."""
        with mute_logger("odoo.db.cursor"):
            with self.assertRaises(UniqueViolation):
                self.env["credential.category"].create(
                    {
                        "name": "Duplicate API Key",
                        "code": "api_key",  # Already exists
                        "storage_hint": "simple",
                    }
                )

    def test_credential_count(self):
        """Test credential count computation."""
        # Mock encryption key (must be valid 32-byte Fernet key)
        with patch.dict(
            os.environ,
            {"ODOO_API_ENCRYPTION_KEY": "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="},
        ):
            category = self.env.ref(
                "base_credential_manager.credential_category_custom"
            )

            initial_count = category.credential_count

            # Create a credential
            self.env["credential.credential"].create(
                {
                    "name": "Count Test",
                    "category_id": category.id,
                    "credential_value": "test",
                }
            )

            # Invalidate cache and recompute
            category.invalidate_recordset()
            self.assertEqual(category.credential_count, initial_count + 1)


class TestCredentialSecurityValidations(TransactionCase):
    """Test security validations for credentials."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Mock encryption key for tests
        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()

        cls.category_custom = cls.env.ref(
            "base_credential_manager.credential_category_custom"
        )

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_credential_value_size_limit(self):
        """Test that credential values exceeding size limit are rejected."""
        # Create a value that exceeds 8KB
        large_value = "x" * 10000  # 10KB

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
        """Test that credential data exceeding size limit is rejected."""
        # Create JSON data that exceeds 64KB
        large_data = '{"key": "' + "x" * 70000 + '"}'  # > 64KB

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
        """Test that deeply nested JSON is rejected."""
        # Create deeply nested JSON (11 levels)
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
        """Password patterns in notes emit a warning but do NOT block save.

        _check_notes_for_secrets was downgraded from a hard ValidationError
        to a logged warning so legitimate operational notes like
        "rotate the old password: expired" don't lock the user out.
        """
        with self.assertLogs(
            "odoo.addons.base_credential_manager.models.credential_credential",
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
        """API key patterns in notes emit a warning but do NOT block save."""
        with self.assertLogs(
            "odoo.addons.base_credential_manager.models.credential_credential",
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
        """Test that safe notes content is allowed."""
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
    """Test audit log write-once protection."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Mock encryption key for tests
        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()

        cls.category_api_key = cls.env.ref(
            "base_credential_manager.credential_category_api_key"
        )

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_audit_log_cannot_be_modified(self):
        """Test that audit logs cannot be modified after creation."""
        # Create a credential (which creates an access log)
        credential = self.env["credential.credential"].create(
            {
                "name": "Audit Test Credential",
                "category_id": self.category_api_key.id,
                "credential_value": "test_key",
            }
        )

        # Get the access log
        log = self.env["credential.access.log"].search(
            [("credential_id", "=", credential.id)], limit=1
        )

        if log:
            # Try to modify it
            with self.assertRaises(UserError) as cm:
                log.write({"operation": "delete"})

            self.assertIn("cannot be modified", str(cm.exception))

    def test_audit_log_cannot_be_deleted(self):
        """Test that audit logs cannot be deleted."""
        # Create a credential (which creates an access log)
        credential = self.env["credential.credential"].create(
            {
                "name": "Delete Test Credential",
                "category_id": self.category_api_key.id,
                "credential_value": "test_key",
            }
        )

        # Get the access log
        log = self.env["credential.access.log"].search(
            [("credential_id", "=", credential.id)], limit=1
        )

        if log:
            # Try to delete it
            with self.assertRaises(UserError) as cm:
                log.unlink()

            self.assertIn("cannot be deleted", str(cm.exception))

    def test_audit_log_cleanup_with_bypass_rejected(self):
        """Test that cleanup bypass without proper authorization is rejected."""
        # Create a credential
        credential = self.env["credential.credential"].create(
            {
                "name": "Cleanup Test Credential",
                "category_id": self.category_api_key.id,
                "credential_value": "test_key",
            }
        )

        # Get the access log
        log = self.env["credential.access.log"].search(
            [("credential_id", "=", credential.id)], limit=1
        )

        if log:
            # Try to delete with just context (should be rejected - not from cron)
            with self.assertRaises(UserError) as cm:
                log.with_context(_credential_log_cleanup_bypass=True).unlink()

            self.assertIn("cannot be deleted", str(cm.exception))

    def test_credential_delete_is_audited_and_logs_survive(self):
        """Deleting a credential audits the delete and preserves its logs.

        The audit-log FKs are ondelete=set null (NOT cascade), so history
        outlives the credential; the denormalized credential_name keeps the
        rows readable. unlink() additionally emits a 'delete' audit entry
        out-of-band so the deletion itself is recorded.
        """
        credential = self.env["credential.credential"].create(
            {
                "name": "Delete Audit Cred",
                "category_id": self.category_api_key.id,
                "credential_value": "sk-delete-audit",
            }
        )
        cred_id = credential.id
        cred_name = credential.name

        # Force a plaintext read so at least one 'read' log exists.
        credential.invalidate_recordset()
        _ = credential.credential_value

        pre_delete = self.env["credential.access.log"].search(
            [("credential_id", "=", cred_id)],
        )
        self.assertTrue(pre_delete, "Expected access log(s) before delete")

        credential.unlink()

        # Logs must survive the credential deletion (NOT cascade-wiped).
        surviving = self.env["credential.access.log"].search(
            [("credential_name", "=", cred_name)],
        )
        self.assertTrue(
            surviving,
            "Access-log history must survive credential deletion",
        )
        for log in surviving:
            # FK is nulled (set null), never dangling; name is preserved.
            self.assertFalse(
                log.credential_id,
                "credential_id must be nulled (set null) after delete",
            )
            self.assertEqual(log.credential_name, cred_name)

        # unlink() must emit a 'delete' audit entry.
        self.assertTrue(
            surviving.filtered(lambda log: log.operation == "delete"),
            "unlink() must emit a 'delete' audit entry",
        )


class TestCredentialCertificates(TransactionCase):
    """Test certificate handling functionality."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Mock encryption key for tests
        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()

        cls.category_certificate = cls.env.ref(
            "base_credential_manager.credential_category_certificate"
        )

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_certificate_pem_not_stored(self):
        """Test that certificate_pem is computed but not stored."""
        field = self.env["credential.credential"]._fields["certificate_pem"]
        self.assertFalse(field.store, "certificate_pem should not be stored")
        self.assertTrue(field.compute, "certificate_pem should be computed")

    def test_private_key_pem_not_stored(self):
        """Test that private_key_pem is computed but not stored."""
        field = self.env["credential.credential"]._fields["private_key_pem"]
        self.assertFalse(field.store, "private_key_pem should not be stored")
        self.assertTrue(field.compute, "private_key_pem should be computed")

    def _build_self_signed_pkcs12(self, password: str) -> bytes:
        """Build a self-signed RSA cert wrapped in PKCS12 protected by password."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        subject = issuer = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "m6-regression-test")],
        )
        now = dt.datetime.now(dt.UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + dt.timedelta(days=30))
            .sign(private_key, hashes.SHA256())
        )
        pkcs12_bytes = pkcs12.serialize_key_and_certificates(
            name=b"m6-regression-test",
            key=private_key,
            cert=cert,
            cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(
                password.encode("utf-8"),
            ),
        )
        return base64.b64encode(pkcs12_bytes)

    def test_certificate_metadata_preserved_on_wrong_password(self):
        """Wrong password must not wipe previously loaded cert metadata (M6).

        Regression: _compute_certificate_data used to blank certificate_subject,
        certificate_serial, and the validity dates whenever _parse_certificate
        returned an error. Changing the password to something wrong thus made
        the UI look like "no cert loaded" even though the ciphertext was intact.
        The compute now preserves last-known-good metadata and only surfaces
        certificate_loading_error.
        """
        pkcs12_bytes = self._build_self_signed_pkcs12("correct-horse")

        credential = self.env["credential.credential"].create(
            {
                "name": "M6 regression cert",
                "category_id": self.category_certificate.id,
                "certificate_content": pkcs12_bytes,
                "certificate_password": "correct-horse",
            },
        )

        # First: with the correct password, metadata is populated.
        self.assertEqual(credential.certificate_format, "pkcs12")
        self.assertEqual(credential.certificate_subject, "m6-regression-test")
        self.assertTrue(credential.certificate_serial)
        self.assertTrue(credential.certificate_date_start)
        self.assertTrue(credential.certificate_date_end)
        self.assertFalse(credential.certificate_loading_error)

        subject_before = credential.certificate_subject
        serial_before = credential.certificate_serial
        start_before = credential.certificate_date_start
        end_before = credential.certificate_date_end

        # Break the password — parse now fails.
        credential.certificate_password = "battery-staple-wrong"

        # Error is surfaced...
        self.assertTrue(credential.certificate_loading_error)
        # ...but previously-stored metadata is preserved.
        self.assertEqual(credential.certificate_subject, subject_before)
        self.assertEqual(credential.certificate_serial, serial_before)
        self.assertEqual(credential.certificate_date_start, start_before)
        self.assertEqual(credential.certificate_date_end, end_before)

        # Clearing the cert content entirely DOES blank metadata.
        credential.certificate_content = False
        self.assertFalse(credential.certificate_subject)
        self.assertFalse(credential.certificate_serial)
        self.assertFalse(credential.certificate_date_start)
        self.assertFalse(credential.certificate_date_end)

    def test_sign_emits_use_audit_entry(self):
        """Signing audits a 'use' access via the private-key choke point.

        Certificate/private-key decryption and _sign() previously had no audit
        trail. Enforcement now lives at the decrypt layer: _sign rate-limits
        and logs a single 'use' entry (reading private_key_pem with the
        internal-access flag so the compute does not double-log).
        """
        pkcs12_bytes = self._build_self_signed_pkcs12("s3cr3t-pass")
        credential = self.env["credential.credential"].create(
            {
                "name": "Sign Audit Cert",
                "category_id": self.category_certificate.id,
                "certificate_content": pkcs12_bytes,
                "certificate_password": "s3cr3t-pass",
            },
        )
        self.assertTrue(credential.certificate_is_valid)

        baseline = self.env["credential.access.log"].search_count(
            [
                ("credential_id", "=", credential.id),
                ("operation", "=", "use"),
            ],
        )

        signature = credential._sign(b"hello world", "sha256")
        self.assertTrue(signature)

        after = self.env["credential.access.log"].search_count(
            [
                ("credential_id", "=", credential.id),
                ("operation", "=", "use"),
            ],
        )
        self.assertEqual(
            after - baseline,
            1,
            "Signing must emit exactly one 'use' audit entry",
        )


class TestCredentialStatsProtection(TransactionCase):
    """Test protection of health statistics fields."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()

        cls.category_api_key = cls.env.ref(
            "base_credential_manager.credential_category_api_key"
        )

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_cannot_modify_usage_count_directly(self):
        """Test that usage_count cannot be modified directly."""
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
        """Test that health_status cannot be modified directly."""
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
        """Protected stats fields must also be rejected at creation time (M7).

        Regression: write() guarded _PROTECTED_STATS_FIELDS but create() did
        not, so a caller could bypass the write guard by seeding the protected
        value in the initial vals dict. create() now mirrors the write guard.
        """
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
        """health_status must not be settable at creation time."""
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
        """Internal callers (imports, migrations) can bypass via context."""
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
        """Test that increment_usage() can update stats."""
        credential = self.env["credential.credential"].create(
            {
                "name": "Increment Usage Test",
                "category_id": self.category_api_key.id,
                "credential_value": "test_key",
            }
        )

        initial_count = credential.usage_count

        # This should work through the internal method
        credential.increment_usage(success=True)

        self.assertEqual(credential.usage_count, initial_count + 1)
        self.assertEqual(credential.success_count, 1)

    def test_mark_as_used_works(self):
        """Test that mark_as_used() can update last_used_at."""
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
    """Test encryption key rotation functionality."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Generate two different test keys for rotation testing
        cls.old_key = Fernet.generate_key().decode()
        cls.new_key = Fernet.generate_key().decode()

        cls.category_api_key = cls.env.ref(
            "base_credential_manager.credential_category_api_key"
        )

    def test_key_version_detection_no_old_keys(self):
        """Test key version detection with only current key."""
        with patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": self.new_key}, clear=True
        ):
            # Invalidate cache
            self.env["credential.credential"]._invalidate_key_version_cache()

            version = self.env[
                "credential.credential"
            ]._get_current_encryption_key_version()
            self.assertEqual(version, 1)

    def test_key_version_detection_with_old_keys(self):
        """Test key version detection with old versioned keys."""
        env_vars = {
            "ODOO_API_ENCRYPTION_KEY": self.new_key,
            "ODOO_API_ENCRYPTION_KEY_V1": self.old_key,
        }

        with patch.dict(os.environ, env_vars, clear=True):
            # Invalidate cache
            self.env["credential.credential"]._invalidate_key_version_cache()

            version = self.env[
                "credential.credential"
            ]._get_current_encryption_key_version()
            self.assertEqual(version, 2)  # V1 exists, so current is V2

    def test_decrypt_with_old_key_fallback(self):
        """Test that credentials encrypted with old key can be decrypted."""
        # First, create credential with old key
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

        # Now switch to new key with old key as fallback
        env_vars = {
            "ODOO_API_ENCRYPTION_KEY": self.new_key,
            "ODOO_API_ENCRYPTION_KEY_V1": self.old_key,
        }

        with patch.dict(os.environ, env_vars, clear=True):
            self.env["credential.credential"]._invalidate_key_version_cache()

            # Should still be able to decrypt with fallback
            credential = self.env["credential.credential"].browse(credential_id)
            credential.invalidate_recordset()

            # This should work due to key fallback
            decrypted = credential.credential_value
            self.assertEqual(decrypted, "secret_value_123")

    def test_key_version_cache_invalidation(self):
        """Test that key version cache can be invalidated."""
        with patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": self.new_key}, clear=True
        ):
            # First call - should compute
            self.env["credential.credential"]._invalidate_key_version_cache()
            version1 = self.env[
                "credential.credential"
            ]._get_current_encryption_key_version()

            # Second call - should use cache
            version2 = self.env[
                "credential.credential"
            ]._get_current_encryption_key_version()

            self.assertEqual(version1, version2)

            # After invalidation with new env, should recompute
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

                # Should now be version 2 (V1 exists)
                self.assertEqual(version3, 2)


class TestSimpleToJsonStorageTransition(TransactionCase):
    """Regression tests for the simple->JSON storage transition path.

    Hypothesis under test: when a credential is first saved with
    `credential_value` (simple storage) and a JSON-accessor field
    (e.g. `bearer_token`) is written to the same record afterwards,
    the inverse chain silently promotes the record to JSON storage
    AND leaves `credential_value` reading back as the raw JSON dump
    instead of the original simple string.

    A correct implementation should either:
      (a) preserve the original simple string on subsequent reads of
          `credential_value`, OR
      (b) refuse the transition with a clear ValidationError.

    Anything in between -- silent mutation of the decrypted value --
    is the bug.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()
        cls.category_api_key = cls.env.ref(
            "base_credential_manager.credential_category_api_key"
        )
        # 'custom' category has no required-fields rule, so tests that
        # exercise JSON-accessor-first creation (bearer_token, etc.) and
        # empty-payload creation can use it without tripping the
        # category-based validation layer.
        cls.category_custom = cls.env.ref(
            "base_credential_manager.credential_category_custom"
        )

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_simple_value_survives_after_setting_json_accessor(self):
        """Write simple credential_value, then write bearer_token in a
        SEPARATE save, then re-read credential_value.

        Either the simple value must be recoverable unchanged, or the
        second write must have raised ValidationError. A credential
        that silently returns a JSON blob from `credential_value`
        fails this test.
        """
        cred = self.env["credential.credential"].create(
            {
                "name": "simple-then-json",
                "category_id": self.category_api_key.id,
                "credential_value": "SK-simple-original",
            }
        )
        self.assertEqual(cred.credential_value, "SK-simple-original")

        # Now promote to JSON by writing a JSON-accessor field.
        # This is the suspected silent-transition path.
        try:
            cred.write({"bearer_token": "tok-added-later"})
        except ValidationError:
            # Acceptable outcome (b): the module refused the transition.
            return

        # Outcome (a): the transition was allowed. Now the simple value
        # must still be readable as the original string. Invalidate the
        # compute cache so we test the on-disk state, not stale memo.
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
        """Narrower assertion: even if we can't agree on what
        credential_value should return post-transition, it should
        at minimum NOT be a JSON string containing the simple value
        under a 'value' key. That specific shape is the fingerprint
        of the get_credential_dict fallback at line 1988 leaking
        into storage.
        """
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
        """A credential created with credential_value seals to 'simple'."""
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
        """A credential created with a JSON accessor seals to 'json'.

        Uses the 'custom' category which has no required-fields rule,
        so this test isolates the storage-mode invariant from the
        category validation layer.
        """
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
        """Writing a JSON accessor on a sealed simple credential raises."""
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
        """Writing credential_value on a sealed json credential raises."""
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
        """Direct writes or seeds of storage_method are rejected."""
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
        """A credential created with no payload stays at 'none'."""
        cred = self.env["credential.credential"].create(
            {
                "name": "empty-no-payload",
                "category_id": self.category_custom.id,
            }
        )
        self.assertEqual(cred.storage_method, "none")


class TestActionTestEncryptionKeys(TransactionCase):
    """Lock down that action_test_encryption_keys operates on self.

    Regression guard for a defect where the method called
    ``self.search([])`` and probed every credential in the database from a
    form-header button advertised as "test if this credential can be
    decrypted". A single-record click should test exactly one record.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()
        cls.env.user.group_ids |= cls.env.ref(
            "base_credential_manager.group_credential_admin"
        )
        cls.category_api_key = cls.env.ref(
            "base_credential_manager.credential_category_api_key"
        )
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
        """Calling on one record tests exactly one record."""
        result = self.cred_a.action_test_encryption_keys()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["current_key"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(result["details"]), 1)
        self.assertEqual(result["details"][0]["id"], self.cred_a.id)

    def test_action_multi_record_scope(self):
        """Calling on a multi-record set tests that set, no more."""
        both = self.cred_a | self.cred_b
        result = both.action_test_encryption_keys()
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["current_key"], 2)
        ids = {d["id"] for d in result["details"]}
        self.assertEqual(ids, {self.cred_a.id, self.cred_b.id})

    def test_action_empty_recordset(self):
        """Empty recordset yields an empty probe, not a global scan."""
        result = (
            self.env["credential.credential"].browse([]).action_test_encryption_keys()
        )
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["details"], [])


class TestBinaryWireFormatCompat(TransactionCase):
    """Dual-shape support for binary encrypted values (D4/D5 regression).

    Canonical shape:  raw Fernet token (ASCII, starts with ``gAAAAA``).
    Legacy shape:     ``base64.b64encode(fernet_token)`` — what the
                      pre-19.0.1.0.2 ``_encrypt_binary_value`` produced.

    Both must decrypt cleanly so we never need an all-or-nothing re-encrypt
    migration on upgrade.
    """

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
        """Write via the current _encrypt_binary_value, read, match plaintext."""
        plaintext = b"certificate-file-bytes-123"
        # Simulate an Odoo Binary field upload: base64-encoded plaintext.
        upload = base64.b64encode(plaintext)
        ciphertext = self.Model._encrypt_binary_value(upload)
        # Canonical shape = raw Fernet token, starts with gAAAAA.
        self.assertTrue(ciphertext.startswith(b"gAAAAA"))
        # Round-trip.
        decrypted_b64 = self.Model._decrypt_binary_value(ciphertext)
        self.assertEqual(base64.b64decode(decrypted_b64), plaintext)

    def test_legacy_double_base64_shape_still_decrypts(self):
        """A credential written in the legacy shape must still decrypt."""
        plaintext = b"legacy-pkcs12-bytes-xyz"
        # Build the legacy on-disk shape by hand.
        cipher = Fernet(self.test_key)
        fernet_token = cipher.encrypt(plaintext)
        legacy_stored = base64.b64encode(fernet_token)
        # _coerce_fernet_token should accept both shapes; decrypt must succeed.
        decrypted_b64 = self.Model._decrypt_binary_value(legacy_stored)
        self.assertEqual(base64.b64decode(decrypted_b64), plaintext)

    def test_canonical_and_legacy_shapes_yield_same_plaintext(self):
        """Both shapes of the same ciphertext decrypt to the same bytes."""
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
        """Non-Fernet, non-base64 bytes raise ValidationError, not silent pass-through."""
        with self.assertRaises(ValidationError):
            self.Model._decrypt_binary_value(b"\x00\x01\x02not-valid")

    def test_char_and_binary_paths_agree_on_canonical_shape(self):
        """_decrypt_value and _decrypt_binary_value share the same coerce helper."""
        plaintext_str = "string-credential"
        cipher = Fernet(self.test_key)
        token = cipher.encrypt(plaintext_str.encode("utf-8"))
        # Char path reads the token directly.
        self.assertEqual(self.Model._decrypt_value(token), plaintext_str)
        # Legacy-shape bytes in a char field should also work.
        legacy = base64.b64encode(token)
        self.assertEqual(self.Model._decrypt_value(legacy), plaintext_str)

    def test_full_orm_roundtrip_legacy_shape_binary_field(self):
        """Plant legacy-shape bytes via raw SQL; the full compute chain reads them.

        This simulates a real customer database upgraded from a pre-19.0.1.0.2
        release: certificate_content_encrypted rows contain base64(token), not
        raw tokens. The ORM compute for certificate_content must decrypt them
        without complaint and hand the plaintext base64 back through the
        certificate parser.
        """
        plaintext = b"legacy-upgrade-bytes-" + b"A" * 100
        cipher = Fernet(self.test_key)
        legacy_stored = base64.b64encode(cipher.encrypt(plaintext))

        cred = self.Model.create(
            {
                "name": "legacy-shape-binary",
                "category_id": self.env.ref(
                    "base_credential_manager.credential_category_custom"
                ).id,
            }
        )
        self.env.cr.execute(
            "UPDATE credential_credential "
            "SET certificate_content_encrypted = %s WHERE id = %s",
            [legacy_stored, cred.id],
        )
        cred.invalidate_recordset(["certificate_content_encrypted"])

        got_b64 = cred.with_context(bin_size=False).certificate_content
        self.assertTrue(got_b64)
        self.assertEqual(base64.b64decode(got_b64), plaintext)

    def test_cron_cleanup_old_logs_works_under_non_superuser(self):
        """D6 regression: cron_cleanup_old_logs must not depend on uid == SUPERUSER_ID.

        The cron's XML user_id is ``base.user_root`` today, but an operator
        retargeting the cron to a service account used to silently break
        cleanup because ``_is_cleanup_authorized`` checked the runtime uid.
        The fix adds ``.sudo()`` inside the method so the cron-user identity
        is irrelevant.
        """
        admin_group = self.env.ref("base_credential_manager.group_credential_admin")
        non_su_user = self.env["res.users"].create(
            {
                "name": "Non-Super Cron Runner",
                "login": "non-su-cron@test",
                "group_ids": [(4, admin_group.id)],
            }
        )

        cred = self.Model.create(
            {
                "name": "audit-source-for-cleanup",
                "category_id": self.env.ref(
                    "base_credential_manager.credential_category_api_key"
                ).id,
                "credential_value": "v1",
            }
        )
        # Plant an ancient log row directly; the write-once ACL blocks
        # normal ORM creation paths, so we go through the model's own
        # logging helper and then backdate the timestamp via raw SQL.
        cred._log_access("read")
        self.env.cr.execute(
            "UPDATE credential_access_log SET timestamp = %s WHERE credential_id = %s",
            ["2000-01-01 00:00:00", cred.id],
        )

        # Run the cleanup method as the NON-SUPERUSER user. Without the
        # sudo() fix this raises a silent zero-delete outcome; with it,
        # the call returns a positive count.
        log = self.env["credential.access.log"].with_user(non_su_user)
        deleted = log.cron_cleanup_old_logs(retention_days=1)
        self.assertGreaterEqual(
            deleted,
            1,
            "cron_cleanup_old_logs must clean up old rows even when "
            "invoked by a non-superuser cron runner",
        )

    def test_migration_action_rewrites_legacy_binary_to_canonical(self):
        """action_migrate_encryption_keys promotes legacy-shape binary columns.

        This closes the test gap at the one seam where D4 could silently
        corrupt: ``_ENCRYPTED_FIELD_PAIRS`` binary fields flowing through
        ``_decrypt_binary_value → _encrypt_binary_value`` during a key
        migration. Existing tests only exercised the char-field half of the
        pairs list, so a mistake in the binary half would have slipped.
        """
        plaintext = b"pkcs12-like-bytes-" + b"B" * 200
        cipher = Fernet(self.test_key)
        legacy_stored = base64.b64encode(cipher.encrypt(plaintext))

        cred = self.Model.create(
            {
                "name": "migrate-legacy-binary",
                "category_id": self.env.ref(
                    "base_credential_manager.credential_category_custom"
                ).id,
            }
        )
        self.env.cr.execute(
            "UPDATE credential_credential SET "
            "certificate_content_encrypted = %s, "
            "encryption_key_version = 0 WHERE id = %s",
            [legacy_stored, cred.id],
        )
        cred.invalidate_recordset(
            ["certificate_content_encrypted", "encryption_key_version"]
        )

        # Admin group is required by the action.
        self.env.user.group_ids |= self.env.ref(
            "base_credential_manager.group_credential_admin"
        )

        # action_migrate_encryption_keys walks the entire table (admin
        # batch op, ignores self). On a cloned marin190 there can be
        # pre-existing credentials at encryption_key_version=0 written
        # with the production key, which this test environment can't
        # decrypt (test env uses a throwaway Fernet key). Park them at
        # the current version so they are skipped by the eligibility
        # filter and only our fixture record is migrated.
        current_version = self.Model._get_current_encryption_key_version()
        self.env.cr.execute(
            "UPDATE credential_credential "
            "SET encryption_key_version = %s WHERE id != %s",
            [current_version, cred.id],
        )
        self.Model.invalidate_model(["encryption_key_version"])

        result = self.Model.action_migrate_encryption_keys()
        self.assertGreaterEqual(result["migrated"], 1)
        self.assertEqual(result["failed"], 0)

        cred.invalidate_recordset()
        after = bytes(cred.with_context(bin_size=False).certificate_content_encrypted)
        # Canonical shape after migration: raw Fernet token, starts with gAAAAA.
        self.assertTrue(
            after.startswith(b"gAAAAA"),
            f"Post-migration ciphertext must be canonical shape, got {after[:16]!r}",
        )
        # Plaintext survives the format transition.
        got_b64 = cred.with_context(bin_size=False).certificate_content
        self.assertEqual(base64.b64decode(got_b64), plaintext)
