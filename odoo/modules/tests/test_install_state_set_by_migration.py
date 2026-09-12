import unittest
from typing import Any, cast

from odoo.modules import loading
from odoo.tools import OrderedSet


class _Cursor:
    sql_log_count = 0

    def __init__(self, row):
        self.row = row
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return self.row


class _Migrations:
    def __init__(self):
        self.indexed = 0

    def index_migration_scripts(self):
        self.indexed += 1


class _Env:
    def __init__(self, cr):
        self.registry = None
        self.cr = cr


class _Package:
    def __init__(self, state):
        self.name = "approval_app"
        self.id = 42
        self.state = state
        self.load_state = state
        self.demo = False


def _operation(package, row, update_module=True):
    cr = _Cursor(row)
    migrations = _Migrations()
    loader = loading._PackageLoader(
        cast("Any", _Env(cr)),
        cast("Any", cr),
        cast("Any", package),
        index=1,
        module_count=1,
        migrations=cast("Any", migrations),
        update_module=update_module,
        install_demo=False,
        run_tests=False,
        report=None,
        models_to_check=OrderedSet(),
        models_updated=set(),
    )
    loader.update_operation()
    return loader.operation, cr, migrations


class TestInstallStateSetByMigration(unittest.TestCase):
    def test_an_install_a_migration_turned_into_an_upgrade_is_upgraded(self):
        package = _Package("to install")

        operation, _cr, migrations = _operation(package, ("to upgrade", True))

        self.assertEqual(operation, "upgrade")
        self.assertEqual(package.load_state, "to upgrade")
        self.assertTrue(package.demo)
        self.assertEqual(migrations.indexed, 1, "its migrations were never indexed")

    def test_an_install_nobody_changed_is_installed(self):
        package = _Package("to install")

        operation, _cr, migrations = _operation(package, ("to install", False))

        self.assertEqual(operation, "install")
        self.assertEqual(package.load_state, "to install")
        self.assertEqual(migrations.indexed, 0)

    def test_an_upgrade_reads_nothing(self):
        operation, cr, _migrations = _operation(_Package("to upgrade"), None)

        self.assertEqual(operation, "upgrade")
        self.assertEqual(cr.queries, [])

    def test_a_plain_load_reads_nothing(self):
        operation, cr, _migrations = _operation(
            _Package("to install"), None, update_module=False
        )

        self.assertIsNone(operation)
        self.assertEqual(cr.queries, [])
