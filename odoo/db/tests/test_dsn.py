import unittest

import psycopg

from odoo.db.dsn import _normalize_dsn_key, _translate_connect_error


class TestNormalizeDsnKey(unittest.TestCase):
    def test_dbname_aliased_to_database(self):
        key_dict = dict(_normalize_dsn_key({"dbname": "test", "host": "localhost"}))
        self.assertEqual(key_dict["database"], "test")
        self.assertNotIn("dbname", key_dict)

    def test_password_excluded(self):
        key_dict = dict(_normalize_dsn_key({"dbname": "test", "password": "secret"}))
        self.assertNotIn("password", key_dict)

    def test_none_values_excluded(self):
        key_dict = dict(_normalize_dsn_key({"dbname": "test", "host": None}))
        self.assertNotIn("host", key_dict)

    def test_string_dsn(self):
        key_dict = dict(_normalize_dsn_key("dbname=test host=localhost"))
        self.assertEqual(key_dict["database"], "test")
        self.assertEqual(key_dict["host"], "localhost")

    def test_same_dsn_same_key(self):
        key1 = _normalize_dsn_key({"dbname": "test", "host": "localhost"})
        key2 = _normalize_dsn_key({"database": "test", "host": "localhost"})
        self.assertEqual(key1, key2)


class TestNormalizeDsnKeyPassword(unittest.TestCase):
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
