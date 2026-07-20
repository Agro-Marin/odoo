"""Regression tests for the post-promotion hardening pass.

Covers:
* encryption_key_is_current compute (form-view key-rotation banner logic)
* ORM-cache consistency after the raw-SQL key-version stamp in write()
* ORM-cache consistency after the raw-SQL token consumption in
  rate.limit.bucket.consume_token()
* ValidationError (not AccessError) for payload-less creates by users
  outside base.group_system
* group_credential_admin implying base.group_system (suite pattern)
* batched delete audit rows on multi-record unlink
* _verify_custom method-name gate (sudo arbitrary-method hardening)
"""

import os
from unittest.mock import patch

from cryptography.fernet import Fernet

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.base_credential_manager.tools.authentication import _verify_custom


class TestHardeningFixesBase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_key = Fernet.generate_key().decode()
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}, clear=False
        )
        cls.env_patcher.start()
        cls.env["credential.credential"]._invalidate_key_version_cache()
        cls.category_api_key = cls.env.ref(
            "base_credential_manager.credential_category_api_key"
        )
        cls.category_custom = cls.env.ref(
            "base_credential_manager.credential_category_custom"
        )

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        cls.env["credential.credential"]._invalidate_key_version_cache()
        super().tearDownClass()


class TestEncryptionKeyCurrentFlag(TestHardeningFixesBase):
    """The key-rotation banner must only show for genuinely old ciphertext."""

    def test_fresh_credential_is_current(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "Fresh Key Cred",
                "category_id": self.category_api_key.id,
                "credential_value": "abc123",
            }
        )
        self.assertTrue(cred.encryption_key_is_current)

    def test_no_payload_counts_as_current(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "No Payload Cred",
                "category_id": self.category_custom.id,
            }
        )
        self.assertFalse(cred.encryption_key_version)
        self.assertTrue(cred.encryption_key_is_current)

    def test_old_key_version_is_not_current(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "Old Key Cred",
                "category_id": self.category_api_key.id,
                "credential_value": "abc123",
            }
        )
        self.assertEqual(cred.encryption_key_version, 1)
        # Introduce a V1 old key: current version becomes 2, the record's
        # ciphertext (stamped v1) is now old.
        with patch.dict(
            os.environ,
            {
                "ODOO_API_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "ODOO_API_ENCRYPTION_KEY_V1": self.test_key,
            },
        ):
            self.env["credential.credential"]._invalidate_key_version_cache()
            cred.invalidate_recordset(["encryption_key_is_current"])
            self.assertFalse(cred.encryption_key_is_current)
        self.env["credential.credential"]._invalidate_key_version_cache()

    def test_write_stamps_version_visible_in_same_transaction(self):
        """The raw-SQL version stamp in write() must not leave a stale 0 in
        the ORM cache (regression: probe showed cache 0 vs DB 1)."""
        cred = self.env["credential.credential"].create(
            {
                "name": "Stamp Cred",
                "category_id": self.category_custom.id,
            }
        )
        self.env.cr.execute(
            "UPDATE credential_credential SET encryption_key_version = NULL "
            "WHERE id = %s",
            [cred.id],
        )
        cred.invalidate_recordset()
        self.assertFalse(cred.encryption_key_version)

        cred.credential_value = "sealed-now"

        # Same transaction, no manual invalidation: the ORM must already
        # see the stamped version.
        self.assertEqual(cred.encryption_key_version, 1)
        self.assertTrue(cred.encryption_key_is_current)


class TestConsumeTokenCacheConsistency(TestHardeningFixesBase):
    """consume_token's raw-SQL UPDATE must be visible through the ORM."""

    def test_tokens_field_reflects_consumption(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "Bucket Endpoint",
                "category_id": self.category_custom.id,
            }
        )
        bucket = self.env["rate.limit.bucket"].create(
            {
                "bucket_key": f"credential.credential:{cred.id}:global",
                "endpoint_model": "credential.credential",
                "endpoint_id": cred.id,
                "tokens": 5.0,
            }
        )
        self.assertTrue(bucket.consume_token())
        self.assertAlmostEqual(bucket.tokens, 4.0, places=1)
        self.assertTrue(bucket.last_request_at)


class TestValidationWithoutSystemGroup(TestHardeningFixesBase):
    """Payload presence checks must not AccessError for non-system users."""

    def test_missing_payload_raises_validation_not_access_error(self):
        user = self.env["res.users"].create(
            {
                "name": "Credential User",
                "login": "cred_user_validation_test",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref(
                                "base_credential_manager.group_credential_user"
                            ).id
                        ],
                    )
                ],
            }
        )
        with self.assertRaises(ValidationError) as ctx:
            self.env["credential.credential"].with_user(user).create(
                {
                    "name": "No Payload API Key",
                    "category_id": self.category_api_key.id,
                }
            )
        self.assertIn("secret value", str(ctx.exception))


class TestAdminGroupImpliesSystem(TestHardeningFixesBase):
    """Credential Manager admins must actually be able to manage secrets."""

    def test_admin_group_implies_group_system(self):
        admin_group = self.env.ref("base_credential_manager.group_credential_admin")
        system_group = self.env.ref("base.group_system")
        self.assertIn(system_group, admin_group.all_implied_ids)

    def test_admin_can_create_and_read_secret(self):
        user = self.env["res.users"].create(
            {
                "name": "Credential Admin",
                "login": "cred_admin_secret_test",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref(
                                "base_credential_manager.group_credential_admin"
                            ).id
                        ],
                    )
                ],
            }
        )
        cred = (
            self.env["credential.credential"]
            .with_user(user)
            .create(
                {
                    "name": "Admin Made Cred",
                    "category_id": self.category_api_key.id,
                    "credential_value": "admin-secret",
                }
            )
        )
        self.assertEqual(cred.credential_value, "admin-secret")


class TestBatchDeleteAudit(TestHardeningFixesBase):
    """Bulk unlink must produce one delete audit row per credential."""

    def test_bulk_unlink_writes_one_row_per_credential(self):
        creds = self.env["credential.credential"].create(
            [
                {
                    "name": f"Bulk Delete Cred {i}",
                    "category_id": self.category_custom.id,
                }
                for i in range(3)
            ]
        )
        names = set(creds.mapped("name"))
        creds.unlink()
        rows = self.env["credential.access.log"].search(
            [("operation", "=", "delete"), ("credential_name", "in", list(names))]
        )
        self.assertEqual(set(rows.mapped("credential_name")), names)
        self.assertEqual(len(rows), 3)


class TestRotationMigrationGeneralization(TestHardeningFixesBase):
    """action_migrate_encryption_keys must cover every mixin consumer."""

    def _grant_admin(self):
        self.env.user.group_ids = [
            (
                4,
                self.env.ref("base_credential_manager.group_credential_admin").id,
            )
        ]

    def test_walker_discovers_consumers_not_the_mixin(self):
        models = self.env["credential.credential"]._get_encryption_migration_models()
        self.assertIn("credential.credential", models)
        self.assertNotIn("credential.encryption.mixin", models)

    def test_null_version_rows_are_eligible(self):
        """Unstamped rows are NULL in SQL; a bare '<' domain excluded them.

        Regression for the latent eligibility gap: rows whose
        encryption_key_version was never stamped (NULL, not 0) must still be
        picked up and re-encrypted by the migration.
        """
        self._grant_admin()
        cred = self.env["credential.credential"].create(
            {
                "name": "Null Version Cred",
                "category_id": self.category_api_key.id,
                "credential_value": "rotate-me",
            }
        )
        self.env.cr.execute(
            "UPDATE credential_credential SET encryption_key_version = NULL "
            "WHERE id = %s",
            [cred.id],
        )
        cred.invalidate_recordset()
        ciphertext_before = bytes(
            cred.with_context(bin_size=False).credential_value_encrypted
        )

        result = self.env["credential.credential"].action_migrate_encryption_keys()

        cred.invalidate_recordset()
        self.assertNotEqual(
            bytes(cred.with_context(bin_size=False).credential_value_encrypted),
            ciphertext_before,
            "NULL-version row must be re-encrypted",
        )
        self.assertEqual(cred.encryption_key_version, 1)
        self.assertEqual(cred.credential_value, "rotate-me")
        self.assertGreaterEqual(result["migrated"], 1)

    def test_result_contains_per_model_breakdown(self):
        self._grant_admin()
        result = self.env["credential.credential"].action_migrate_encryption_keys()
        self.assertIn("models", result)
        self.assertIn("credential.credential", result["models"])
        per_model = result["models"]["credential.credential"]
        for key in ("total", "eligible", "skipped", "migrated", "failed"):
            self.assertIn(key, per_model)
        # Top-level keys stay backward compatible (server action message
        # in credential_credential_views.xml formats them).
        for key in ("total", "skipped", "migrated", "failed", "errors"):
            self.assertIn(key, result)

    @mute_logger("odoo.addons.base_credential_manager.models.credential_credential")
    def test_failed_row_rolls_back_orm_cache_and_is_not_counted_migrated(self):
        """A row that raises mid-migration must roll back its ORM cache too.

        ``_reencrypt_with_current_key`` writes the new-key ciphertext through
        the ORM (``self[enc_field] = ...``), a *deferred* write that lands in
        the ORM cache before any flush. If that row then fails, a bare
        ``ROLLBACK TO SAVEPOINT`` (the pre-fix manual pair) undoes SQL but
        leaves that new-key ciphertext lingering in the cache — it would flush
        into the transaction later and corrupt a row the migration reported as
        *failed*. The ORM-aware ``env.cr.savepoint()`` clears the cache on
        rollback, so the stale payload never survives.

        Asserts, for a row that raises after re-encryption but before its key
        version is stamped:

        * it is counted under ``failed`` (surfaced by id in ``errors``),
          never ``migrated`` — the ``else`` clause tallies only on clean exit;
        * its re-encrypted payload does NOT linger in the ORM cache (the
          discriminator: the version field is raw-SQL + invalidate and rolls
          back either way, but the deferred payload write does not);
        * once flushed, the persisted row still decrypts under the old key —
          i.e. the failed row was not silently corrupted;
        * a sibling eligible row still migrates in the same run.
        """
        self._grant_admin()
        Model = self.env["credential.credential"]
        old_key = self.test_key
        new_key = Fernet.generate_key().decode()

        # Two rows encrypted under the old key (version 1).
        doomed = Model.create(
            {
                "name": "Doomed Cred",
                "category_id": self.category_api_key.id,
                "credential_value": "keep-me-doomed",
            }
        )
        healthy = Model.create(
            {
                "name": "Healthy Cred",
                "category_id": self.category_api_key.id,
                "credential_value": "keep-me-healthy",
            }
        )
        self.assertEqual(doomed.encryption_key_version, 1)
        self.assertEqual(healthy.encryption_key_version, 1)
        doomed_id = doomed.id

        # Snapshot the old-key ciphertext from a clean read, for comparison.
        old_ciphertext = bytes(
            doomed.with_context(bin_size=False).credential_value_encrypted
        )

        # Fail the doomed row *after* re-encryption has populated the ORM cache
        # but before its version is stamped; the sibling stamps normally.
        orig_stamp = type(Model)._stamp_encryption_key_version

        def stamp_or_raise(self, version):
            if doomed_id in self.ids:
                raise RuntimeError("injected failure after re-encryption")
            return orig_stamp(self, version)

        # Rotate: new key becomes current (version 2), old key retained as V1.
        env_vars = {
            "ODOO_API_ENCRYPTION_KEY": new_key,
            "ODOO_API_ENCRYPTION_KEY_V1": old_key,
        }
        with patch.dict(os.environ, env_vars, clear=True):
            Model._invalidate_key_version_cache()
            self.assertEqual(Model._get_current_encryption_key_version(), 2)
            with patch.object(
                type(Model), "_stamp_encryption_key_version", stamp_or_raise
            ):
                result = Model.action_migrate_encryption_keys()

            # The doomed row is reported as failed, identified by id, and is
            # never double-counted as migrated.
            self.assertGreaterEqual(result["failed"], 1)
            self.assertTrue(
                any(f"ID: {doomed_id})" in err for err in result["errors"]),
                "the injected failure must surface in the per-row error list",
            )

            # Discriminator: the deferred re-encryption write must NOT linger
            # in the ORM cache. Read straight from cache (no invalidate) — the
            # rollback should have cleared it back to the old-key ciphertext.
            self.assertEqual(
                bytes(doomed.with_context(bin_size=False).credential_value_encrypted),
                old_ciphertext,
                "failed row's re-encrypted payload must not survive in the "
                "ORM cache after rollback",
            )

            # The sibling still migrates in the same run: each row's rollback
            # is isolated to its own savepoint.
            healthy.invalidate_recordset(["encryption_key_version"])
            self.assertEqual(healthy.encryption_key_version, 2)
            self.assertGreaterEqual(result["migrated"], 1)

        # Persisted integrity: flushing must not push a stale new-key payload
        # to the DB — the failed row still decrypts under the old key and
        # keeps its old key version.
        self.env.flush_all()
        Model._invalidate_key_version_cache()
        fresh = Model.browse(doomed_id)
        fresh.invalidate_recordset()
        self.assertEqual(fresh.credential_value, "keep-me-doomed")
        self.assertEqual(fresh.encryption_key_version, 1)


class TestEO78SudoReads(TestHardeningFixesBase):
    """Three reads that must not AccessError for a non-privileged calling
    context — allow_key_fallback (x2 decrypt paths) and the category defaults
    read in _onchange_category_id."""

    def _low_priv_user(self, login):
        return self.env["res.users"].create(
            {
                "name": "Low Priv Credential User",
                "login": login,
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref(
                                "base_credential_manager.group_credential_user"
                            ).id
                        ],
                    )
                ],
            }
        )

    def test_decrypt_value_reads_allow_key_fallback_without_accesserror(self):
        user = self._low_priv_user("eo78_decrypt_char_user")
        cred = self.env["credential.credential"].create(
            {
                "name": "Fallback Char Cred",
                "category_id": self.category_api_key.id,
                "credential_value": "secret-value",
                "allow_key_fallback": False,
            }
        )
        # Not asserting a specific plaintext here — just that reading
        # allow_key_fallback via sudo() doesn't itself raise, regardless of
        # the calling user's direct access to this record.
        cred.with_user(user)._decrypt_value(
            cred.with_context(bin_size=False).credential_value_encrypted
        )

    def test_decrypt_binary_value_reads_allow_key_fallback_without_accesserror(self):
        user = self._low_priv_user("eo78_decrypt_binary_user")
        cred = self.env["credential.credential"].create(
            {
                "name": "Fallback Binary Cred",
                "category_id": self.category_custom.id,
                "allow_key_fallback": False,
            }
        )
        encrypted = cred._encrypt_binary_value(b"YmluYXJ5LXBheWxvYWQ=")
        cred.with_user(user)._decrypt_binary_value(encrypted)

    def test_onchange_category_id_applies_defaults_without_accesserror(self):
        user = self._low_priv_user("eo78_onchange_user")
        cred = self.env["credential.credential"].new(
            {"name": "Onchange Cred", "category_id": self.category_api_key.id}
        )
        cred_as_user = cred.with_user(user)
        # The call itself must not raise — this is what the sudo() fix
        # covers (reading category.default_* as a group_credential_user).
        cred_as_user._onchange_category_id()
        # enable_rate_limiting/allow_key_fallback are themselves restricted
        # to group_credential_admin (by design, unrelated to this fix) —
        # read back via sudo() rather than as the low-priv user.
        self.assertEqual(
            cred_as_user.sudo().enable_rate_limiting,
            self.category_api_key.default_enable_rate_limiting,
        )
        self.assertEqual(
            cred_as_user.sudo().allow_key_fallback,
            self.category_api_key.default_allow_key_fallback,
        )


class TestRateLimitBucketLockTimeoutScope(TestHardeningFixesBase):
    """A strict consume_token() must not leave lock_timeout tightened for the
    rest of the transaction."""

    def test_lock_timeout_reset_after_strict_consume(self):
        cred = self.env["credential.credential"].create(
            {
                "name": "Lock Timeout Scope Cred",
                "category_id": self.category_custom.id,
            }
        )
        self.env.cr.execute("SHOW lock_timeout")
        (before,) = self.env.cr.fetchone()

        bucket = self.env["rate.limit.bucket"].create(
            {
                "bucket_key": f"credential.credential:{cred.id}:global",
                "endpoint_model": "credential.credential",
                "endpoint_id": cred.id,
                "tokens": 5.0,
            }
        )
        self.assertTrue(bucket.consume_token(strict=True))

        self.env.cr.execute("SHOW lock_timeout")
        (after,) = self.env.cr.fetchone()
        self.assertEqual(
            before,
            after,
            "lock_timeout must be reset immediately after the locked query, "
            "not leak into the rest of the transaction",
        )


class TestVerifyCustomPrefixGate(TransactionCase):
    """_verify_custom must refuse to invoke non-verify methods under sudo."""

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_non_verify_method_rejected(self):
        # 'search_count' exists and is callable, but is not a verify_ method:
        # the gate must reject it BEFORE invocation.
        result = _verify_custom("res.partner.search_count", {}, "{}", env=self.env)
        self.assertFalse(result)

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_private_non_verify_method_rejected(self):
        result = _verify_custom(
            "res.partner._compute_display_name", {}, "{}", env=self.env
        )
        self.assertFalse(result)

    def test_verify_method_invoked(self):
        calls = []

        def fake_verify(model_self, headers, body):
            calls.append((headers, body))
            return True

        partner_cls = type(self.env["res.partner"])
        with patch.object(
            partner_cls, "verify_test_webhook", create=True, new=fake_verify
        ):
            result = _verify_custom(
                "res.partner.verify_test_webhook",
                {"X-Test": "1"},
                "body",
                env=self.env,
            )
        self.assertTrue(result)
        self.assertEqual(calls, [({"X-Test": "1"}, "body")])
