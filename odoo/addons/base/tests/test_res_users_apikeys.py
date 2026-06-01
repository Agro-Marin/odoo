import datetime
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestResUsersApikeys(TransactionCase):
    """Coverage for API-key authentication negatives and guards (audit AK-T1):
    wrong / empty / expired / inactive credential checks, the expiration-date
    policy (system bypass, required for non-system, over-limit), GC of expired
    keys, and the _remove / make_key access controls. Happy-path auth is
    already covered in auth_totp / test_http.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="ak_user")
        cls.Apikeys = cls.env["res.users.apikeys"]

    def _generate(self, scope="rpc", hours=1):
        """Generate a key owned by cls.user with a relative expiration."""
        exp = fields.Datetime.now() + timedelta(hours=hours)
        return self.Apikeys.with_user(self.user)._generate(scope, "k", exp)

    # --- _check_credentials -------------------------------------------------
    def test_check_credentials_valid(self):
        key = self._generate(scope="rpc")
        self.assertEqual(
            self.Apikeys._check_credentials(scope="rpc", key=key), self.user.id
        )

    def test_check_credentials_wrong_key(self):
        self._generate(scope="rpc")
        self.assertIsNone(self.Apikeys._check_credentials(scope="rpc", key="0" * 40))

    def test_check_credentials_empty_args_raise(self):
        with self.assertRaises(ValueError):
            self.Apikeys._check_credentials(scope="", key="x")
        with self.assertRaises(ValueError):
            self.Apikeys._check_credentials(scope="rpc", key="")

    def test_check_credentials_expired(self):
        # A past date is accepted at generation (<= the upper bound) but the key
        # is filtered out at verification time.
        key = self._generate(scope="rpc", hours=-1)
        self.assertIsNone(self.Apikeys._check_credentials(scope="rpc", key=key))

    def test_check_credentials_inactive_user(self):
        key = self._generate(scope="rpc")
        self.user.active = False
        # _check_credentials reads u.active via raw SQL; flush the ORM write.
        self.env.flush_all()
        self.assertIsNone(self.Apikeys._check_credentials(scope="rpc", key=key))

    # --- _check_expiration_date ---------------------------------------------
    def test_expiration_date_system_bypass(self):
        # A system user may create a persistent (no-expiration) key.
        self.Apikeys.sudo()._check_expiration_date(None)  # must not raise

    def test_expiration_date_required_for_non_system(self):
        with self.assertRaises(ValidationError):
            self.Apikeys.with_user(self.user)._check_expiration_date(None)

    def test_expiration_date_over_limit(self):
        too_far = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + timedelta(
            days=3650
        )
        with self.assertRaises(ValidationError):
            self.Apikeys.with_user(self.user)._check_expiration_date(too_far)

    # --- _gc_user_apikeys ---------------------------------------------------
    def test_gc_removes_expired_keys(self):
        valid = self._generate(scope="rpc", hours=1)
        expired = self._generate(scope="rpc", hours=-1)
        self.Apikeys._gc_user_apikeys()
        self.assertEqual(
            self.Apikeys._check_credentials(scope="rpc", key=valid), self.user.id
        )
        self.assertIsNone(self.Apikeys._check_credentials(scope="rpc", key=expired))

    # --- access controls ----------------------------------------------------
    def test_remove_other_users_key_raises(self):
        self._generate(scope="rpc")
        key_rec = self.Apikeys.sudo().search([("user_id", "=", self.user.id)], limit=1)
        other = new_test_user(self.env, login="ak_other")
        with self.assertRaises(AccessError):
            key_rec.with_user(other)._remove()

    def test_make_key_requires_internal_user(self):
        portal = new_test_user(self.env, login="ak_portal", groups="base.group_portal")
        with self.assertRaises(AccessError):
            self.env["res.users.apikeys.description"].with_user(
                portal
            ).check_access_make_key()

    def test_generate_requires_internal_user(self):
        """AK-T4: the minting primitive itself rejects a non-internal user, so
        the "only internal users hold API keys" invariant is enforced at
        ``_generate`` and not only at the ``make_key`` UI path (audit AK-P1)."""
        portal = new_test_user(
            self.env, login="ak_portal_gen", groups="base.group_portal"
        )
        exp = fields.Datetime.now() + timedelta(hours=1)
        with self.assertRaises(AccessError):
            self.Apikeys.with_user(portal)._generate("rpc", "k", exp)

    # --- scope discrimination (AK-T2) ---------------------------------------
    def test_check_credentials_scope_mismatch(self):
        """A key minted for scope X must not authenticate a scope Y request."""
        key = self._generate(scope="scope_x")
        self.assertIsNone(self.Apikeys._check_credentials(scope="scope_y", key=key))

    def test_check_credentials_scope_match(self):
        """A key minted for scope X authenticates a scope X request."""
        key = self._generate(scope="scope_x")
        self.assertEqual(
            self.Apikeys._check_credentials(scope="scope_x", key=key), self.user.id
        )

    def test_check_credentials_null_scope_matches_any(self):
        """A global (NULL-scope) key authenticates any requested scope."""
        exp = fields.Datetime.now() + timedelta(hours=1)
        key = self.Apikeys.with_user(self.user)._generate(None, "k", exp)
        self.assertEqual(
            self.Apikeys._check_credentials(scope="anything", key=key), self.user.id
        )

    # --- no-plaintext storage invariant (AK-T3) -----------------------------
    def test_generate_stores_hash_not_plaintext(self):
        """AK-T3: ``_generate`` returns a 40-hex key whose first 8 chars equal the
        stored cleartext ``index``, while the ``key`` column holds a pbkdf2 hash,
        never the cleartext key (the core no-plaintext property of this file)."""
        key = self._generate(scope="rpc")
        self.assertEqual(len(key), 40)
        self.assertTrue(all(c in "0123456789abcdef" for c in key))
        self.env.cr.execute(
            "SELECT index, key FROM res_users_apikeys WHERE user_id = %s",
            (self.user.id,),
        )
        index, stored_key = self.env.cr.fetchone()
        self.assertEqual(index, key[:8])
        self.assertNotEqual(stored_key, key)
        self.assertTrue(stored_key.startswith("$pbkdf2-sha512$"))

    # --- persistent key (system bypass) authenticates (AK-T3) ---------------
    def test_check_credentials_persistent_key_never_expires(self):
        """A persistent (NULL-expiration) key created by a system user
        authenticates (no expiration filter to reject it)."""
        # A persistent (NULL-expiration) key is restricted to system users. Use
        # base.user_admin -- an ACTIVE system user -- because _check_credentials
        # joins res_users WHERE u.active, and the superuser (base.user_root) is
        # inactive, so a key minted under sudo would never match.
        admin = self.env.ref("base.user_admin")
        key = self.Apikeys.with_user(admin)._generate("rpc", "persistent", None)
        self.assertEqual(
            self.Apikeys._check_credentials(scope="rpc", key=key),
            admin.id,
        )
