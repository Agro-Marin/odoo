import unittest
from unittest.mock import patch

from odoo.db import utils as db_utils
from odoo.db.utils import _HEALTH_PARAMS, connection_info_for, is_maintenance_db


class _Config(dict):
    pass


def _config(**overrides):
    base = {
        "db_app_name": "odoo-{pid}",
        "db_host": "primary.example",
        "db_port": 5432,
        "db_user": "odoo",
        "db_password": "secret",
        "db_sslmode": "require",
        "db_template": "template0",
        "db_replica_host": None,
        "db_replica_port": None,
    }
    base.update(overrides)
    return _Config(base)


class TestIsMaintenanceDb(unittest.TestCase):
    def test_system_and_template_databases(self):
        with patch.object(db_utils, "tools") as tools:
            tools.config = _config()
            for name in ("postgres", "template0", "template1"):
                with self.subTest(name=name):
                    self.assertTrue(is_maintenance_db(name))

    def test_the_configured_template_is_included(self):
        with patch.object(db_utils, "tools") as tools:
            tools.config = _config(db_template="tpl_custom")
            self.assertTrue(is_maintenance_db("tpl_custom"))

    def test_read_per_call_not_frozen_at_import(self):
        with patch.object(db_utils, "tools") as tools:
            tools.config = _config(db_template="tpl_a")
            self.assertTrue(is_maintenance_db("tpl_a"))
            tools.config = _config(db_template="tpl_b")
            self.assertFalse(is_maintenance_db("tpl_a"))
            self.assertTrue(is_maintenance_db("tpl_b"))

    def test_ordinary_databases_are_not_maintenance(self):
        with patch.object(db_utils, "tools") as tools:
            tools.config = _config()
            for name in ("prod", "template_of_mine", "postgres_backup"):
                with self.subTest(name=name):
                    self.assertFalse(is_maintenance_db(name))

    def test_system_dbs_has_one_definition(self):
        """``SYSTEM_DBS`` is defined here and only re-exported elsewhere.

        The predicate used to be re-spelled inline at seven call sites across
        ``service``/``http``/``cli``/``orm.runtime`` — one of them the sole
        runtime ``orm -> service`` edge (now forbidden by the
        ``orm-below-the-serving-tier`` contract). Identity, not equality:
        a second frozenset with the same members would drift independently.
        """
        self.assertEqual(
            db_utils.SYSTEM_DBS, frozenset({"postgres", "template0", "template1"})
        )
        import odoo.db

        self.assertIs(odoo.db.SYSTEM_DBS, db_utils.SYSTEM_DBS)


class TestConnectionInfoForKeywords(unittest.TestCase):
    def _info(self, name="mydb", readonly=False, **overrides):
        with patch.object(db_utils, "tools") as tools:
            tools.config = _config(**overrides)
            return connection_info_for(name, readonly)

    def test_returns_the_database_name_unchanged(self):
        db, info = self._info("mydb")
        self.assertEqual(db, "mydb")
        self.assertEqual(info["dbname"], "mydb")

    def test_carries_the_configured_credentials(self):
        _, info = self._info()
        self.assertEqual(info["host"], "primary.example")
        self.assertEqual(info["user"], "odoo")
        self.assertEqual(info["password"], "secret")
        self.assertEqual(info["sslmode"], "require")

    def test_falsy_config_values_are_omitted_not_sent_empty(self):
        _, info = self._info(db_host=False, db_password=False)
        self.assertNotIn("host", info)
        self.assertNotIn("password", info)

    def test_health_parameters_are_applied(self):
        _, info = self._info()
        for key, value in _HEALTH_PARAMS.items():
            with self.subTest(key=key):
                self.assertEqual(info[key], value)

    def test_application_name_interpolates_the_pid_and_is_truncated(self):
        import os

        _, info = self._info()
        self.assertEqual(info["application_name"], f"odoo-{os.getpid()}")
        _, long_info = self._info(db_app_name="x" * 200)
        self.assertEqual(len(long_info["application_name"]), 63)


class TestConnectionInfoForReplica(unittest.TestCase):
    def _info(self, readonly, **overrides):
        with patch.object(db_utils, "tools") as tools:
            tools.config = _config(**overrides)
            return connection_info_for("mydb", readonly)[1]

    def test_replica_overrides_host_and_port_only(self):
        info = self._info(True, db_replica_host="replica.example", db_replica_port=5433)
        self.assertEqual(info["host"], "replica.example")
        self.assertEqual(info["port"], 5433)
        self.assertEqual(info["user"], "odoo")
        self.assertEqual(info["password"], "secret")
        self.assertEqual(info["sslmode"], "require")

    def test_without_a_replica_host_readonly_targets_the_primary(self):
        self.assertEqual(self._info(True)["host"], "primary.example")

    def test_readonly_false_ignores_replica_settings(self):
        info = self._info(False, db_replica_host="replica.example")
        self.assertEqual(info["host"], "primary.example")


class TestConnectionInfoForUri(unittest.TestCase):
    def _info(self, uri):
        with patch.object(db_utils, "tools") as tools:
            tools.config = _config()
            return connection_info_for(uri)

    def test_database_is_taken_from_the_uri_path(self):
        db, info = self._info("postgresql://user@host:5432/thedb")
        self.assertEqual(db, "thedb")
        self.assertEqual(info["dsn"], "postgresql://user@host:5432/thedb")

    def test_username_is_the_fallback_database_name(self):
        db, _ = self._info("postgresql://theuser@host")
        self.assertEqual(db, "theuser")

    def test_malformed_uri_warns_instead_of_silently_guessing(self):
        with self.assertWarns(RuntimeWarning):
            db, _ = self._info("postgresql://host.example")
        self.assertEqual(db, "host.example")

    def test_health_params_do_not_override_the_uri_query_string(self):
        _, info = self._info("postgresql://h/db?connect_timeout=60&keepalives=0")
        self.assertNotIn("connect_timeout", info)
        self.assertNotIn("keepalives", info)
        self.assertEqual(info["keepalives_idle"], _HEALTH_PARAMS["keepalives_idle"])

    def test_uri_application_name_is_respected(self):
        _, info = self._info("postgresql://h/db?application_name=mine")
        self.assertNotIn("application_name", info)

    def test_application_name_is_added_when_the_uri_omits_it(self):
        _, info = self._info("postgresql://h/db")
        self.assertIn("application_name", info)

    def test_postgres_scheme_is_accepted_too(self):
        db, _ = self._info("postgres://user@host/thedb")
        self.assertEqual(db, "thedb")


if __name__ == "__main__":
    unittest.main()
