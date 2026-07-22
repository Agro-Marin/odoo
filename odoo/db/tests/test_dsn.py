"""Tier-1 (database-free) tests for :mod:`odoo.db.dsn`.

DSN normalization (pool-key hygiene: password fingerprinting, URI expansion)
and connect-phase error classification are pure functions in a
security-sensitive module — tested at the lowest tier that can express them
(coding_guidelines §6): plain pytest, no database, no framework import.

Moved from ``odoo/addons/base/tests/test_db_cursor.py`` so a regression fails
in milliseconds instead of requiring a live database with ``base`` installed.
"""

import unittest

import psycopg

from odoo.db.dsn import _normalize_dsn_key, _translate_connect_error


class TestNormalizeDsnKey(unittest.TestCase):
    """Test DSN normalization for pool lookup keys."""

    def test_dbname_aliased_to_database(self):
        key_dict = dict(_normalize_dsn_key({"dbname": "test", "host": "localhost"}))
        self.assertEqual(key_dict["database"], "test")
        self.assertNotIn("dbname", key_dict)

    def test_password_excluded(self):
        """Passwords are excluded from pool keys (security + correctness)."""
        key_dict = dict(_normalize_dsn_key({"dbname": "test", "password": "secret"}))
        self.assertNotIn("password", key_dict)

    def test_none_values_excluded(self):
        key_dict = dict(_normalize_dsn_key({"dbname": "test", "host": None}))
        self.assertNotIn("host", key_dict)

    def test_string_dsn(self):
        """String DSNs are parsed via conninfo_to_dict."""
        key_dict = dict(_normalize_dsn_key("dbname=test host=localhost"))
        self.assertEqual(key_dict["database"], "test")
        self.assertEqual(key_dict["host"], "localhost")

    def test_same_dsn_same_key(self):
        """Different dict representations of the same DSN produce equal keys."""
        key1 = _normalize_dsn_key({"dbname": "test", "host": "localhost"})
        key2 = _normalize_dsn_key({"database": "test", "host": "localhost"})
        self.assertEqual(key1, key2)


class TestNormalizeDsnKeyPassword(unittest.TestCase):
    """_normalize_dsn_key must differentiate pools by password (via
    fingerprint) so rotating a database password invalidates the
    cached pool and forces a reconnect with the new credentials.
    """

    def test_password_rotation_yields_different_key(self):
        base = {"dbname": "x", "host": "h", "user": "u"}
        k0 = _normalize_dsn_key({**base, "password": "old"})
        k1 = _normalize_dsn_key({**base, "password": "new"})
        self.assertNotEqual(
            k0, k1, "different passwords must yield different pool keys"
        )

    def test_password_not_leaked_in_key(self):
        key = _normalize_dsn_key(
            {"dbname": "x", "host": "h", "user": "u", "password": "s3cr3t"}
        )
        for _k, v in key:
            self.assertNotIn(
                "s3cr3t", v, "raw password must not appear in the pool key"
            )


class TestNormalizeDsnKeyUriExpansion(unittest.TestCase):
    """URI DSNs must be expanded into components before keying: the raw
    URI string carries the cleartext password into the key (and the pool
    logs), and keyword-form lookups can never match URI-form pools."""

    def test_uri_password_not_in_key(self):
        key = _normalize_dsn_key(
            {"dsn": "postgresql://u:s3cret@h:5433/dbz", "application_name": "x"}
        )
        self.assertNotIn("s3cret", str(sorted(key)))
        kd = dict(key)
        self.assertEqual(kd.get("database"), "dbz")
        self.assertEqual(kd.get("host"), "h")

    def test_uri_password_rotation_changes_key(self):
        k1 = _normalize_dsn_key({"dsn": "postgresql://u:old@h/dbz"})
        k2 = _normalize_dsn_key({"dsn": "postgresql://u:new@h/dbz"})
        self.assertNotEqual(k1, k2)

    def test_kwargs_override_uri_components(self):
        key = dict(
            _normalize_dsn_key(
                {
                    "dsn": "postgresql://h/dbz?application_name=uriapp",
                    "application_name": "kwapp",
                }
            )
        )
        self.assertEqual(key.get("application_name"), "kwapp")


class TestConnectErrorTranslation(unittest.TestCase):
    """libpq surfaces connection-phase failures as a bare OperationalError with
    no SQLSTATE (diag.sqlstate is None), so the precise subclass is never raised
    on a *connect* — only the server's FATAL text. ``_translate_connect_error``
    maps that text back to the precise, permanent psycopg class so the pool can
    fail fast instead of letting psycopg_pool retry a hopeless connection for
    the full ~30s getconn budget."""

    def _op_error(self, message):
        return psycopg.OperationalError(message)

    def test_missing_database_translates_to_invalid_catalog_name(self):
        exc = self._op_error(
            'connection failed: FATAL:  database "nope" does not exist'
        )
        self.assertIsInstance(
            _translate_connect_error(exc), psycopg.errors.InvalidCatalogName
        )

    def test_missing_role_translates_to_auth_error(self):
        exc = self._op_error('connection failed: FATAL:  role "nobody" does not exist')
        self.assertIsInstance(
            _translate_connect_error(exc),
            psycopg.errors.InvalidAuthorizationSpecification,
        )

    def test_bad_password_translates_to_auth_error(self):
        exc = self._op_error('FATAL:  password authentication failed for user "x"')
        self.assertIsInstance(
            _translate_connect_error(exc),
            psycopg.errors.InvalidAuthorizationSpecification,
        )

    def test_no_pg_hba_entry_translates_to_auth_error(self):
        exc = self._op_error('FATAL:  no pg_hba.conf entry for host "1.2.3.4"')
        self.assertIsInstance(
            _translate_connect_error(exc),
            psycopg.errors.InvalidAuthorizationSpecification,
        )

    def test_transient_errors_return_none(self):
        # Retrying these may succeed — they must NOT be classified permanent,
        # or a momentary blip becomes a hard failure.
        for msg in (
            "connection refused",
            "connection timeout",
            "could not connect to server: Connection refused",
            "server closed the connection unexpectedly",
            "FATAL:  the database system is starting up",
        ):
            with self.subTest(msg=msg):
                self.assertIsNone(_translate_connect_error(self._op_error(msg)))


if __name__ == "__main__":
    unittest.main()
