"""Regression coverage for the rehash-on-verify path in res.users (audit RU-T02).

Pins the behaviour of ``_check_credentials`` (res_users.py) when the stored
password hash uses deprecated KDF parameters: ``verify_and_update`` returns a
replacement hash, which the method persists via ``_set_encrypted_password``.
These tests assert the CURRENT behaviour against the unmodified code.

The configured work factor is read from the live crypt context at runtime
(``_crypt_context().hash()``) rather than assumed, so the tests are robust to
whatever ``password.hashing.rounds`` the database is configured with.
"""

from odoo.exceptions import AccessDenied
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger
from odoo.tools.password import _parse_hash, pbkdf2_sha512_hash


@tagged("post_install", "-at_install")
class TestPasswordRehashOnVerify(TransactionCase):
    """Cover the deprecated-hash upgrade branch of res.users._check_credentials."""

    def _store_raw_password(self, user, raw_hash):
        """Write ``raw_hash`` directly into res_users.password via SQL, bypassing
        the ORM hashing so the stored hash is exactly the value under test."""
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_users SET password=%s WHERE id=%s", (raw_hash, user.id)
        )
        self.env.invalidate_all()

    def _read_raw_password(self, user):
        """Return the password column for ``user`` straight from the database."""
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT COALESCE(password, '') FROM res_users WHERE id=%s", (user.id,)
        )
        [stored] = self.env.cr.fetchone()
        self.env.invalidate_all()
        return stored

    def _configured_rounds(self, user):
        """The effective pbkdf2 round count of the live crypt context."""
        return _parse_hash(user._crypt_context().hash("probe"))[0]

    def test_deprecated_rounds_hash_is_upgraded_on_verify(self):
        """A hash whose rounds differ from the configured work factor is
        rehashed (to the configured rounds) on a valid login, and still
        authenticates the same plaintext."""
        plaintext = "deprecated-rounds-secret"
        user = new_test_user(self.env, login="rehash_rounds_user")
        ctx = user._crypt_context()
        configured = self._configured_rounds(user)

        # A valid pbkdf2 hash at a DIFFERENT round count -> deprecated.
        deprecated_hash = pbkdf2_sha512_hash(plaintext, rounds=configured + 1)
        self._store_raw_password(user, deprecated_hash)

        # _check_credentials validates self.env.user, so bind env to the user.
        with mute_logger("odoo.addons.base.models.res_users"):
            user.with_user(user)._check_credentials(
                {"type": "password", "password": plaintext}, {"interactive": True}
            )

        stored_after = self._read_raw_password(user)
        self.assertNotEqual(stored_after, deprecated_hash, "hash must be upgraded")
        self.assertEqual(
            _parse_hash(stored_after)[0], configured, "upgraded to configured rounds"
        )
        self.assertTrue(ctx.verify(plaintext, stored_after), "still authenticates")

    def test_configured_rounds_hash_is_not_rehashed(self):
        """A hash already at the configured work factor is left untouched."""
        plaintext = "up-to-date-secret"
        user = new_test_user(self.env, login="rehash_noop_user")
        current_hash = user._crypt_context().hash(plaintext)
        self._store_raw_password(user, current_hash)

        with mute_logger("odoo.addons.base.models.res_users"):
            user.with_user(user)._check_credentials(
                {"type": "password", "password": plaintext}, {"interactive": True}
            )

        self.assertEqual(self._read_raw_password(user), current_hash)

    def test_wrong_password_does_not_upgrade_deprecated_hash(self):
        """A failed verify leaves the deprecated stored hash unchanged."""
        plaintext = "deprecated-rounds-secret"
        user = new_test_user(self.env, login="rehash_wrongpw_user")
        configured = self._configured_rounds(user)
        deprecated_hash = pbkdf2_sha512_hash(plaintext, rounds=configured + 1)
        self._store_raw_password(user, deprecated_hash)

        with (
            mute_logger("odoo.addons.base.models.res_users"),
            self.assertRaises(AccessDenied),
        ):
            user.with_user(user)._check_credentials(
                {"type": "password", "password": "not-the-password"},
                {"interactive": True},
            )

        self.assertEqual(self._read_raw_password(user), deprecated_hash)
