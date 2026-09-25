import contextlib
import unittest

import psycopg

from odoo.modules import loading


class _Cursor:
    def __init__(self, *, granted=True, holders=(), unlock_error=None):
        self.granted = granted
        self.holders = list(holders)
        self.unlock_error = unlock_error
        self.statements = []
        self._rows = []
        self.session_state_holds = 0

    @contextlib.contextmanager
    def holding_session_state(self):
        self.session_state_holds += 1
        try:
            yield
        finally:
            self.session_state_holds -= 1

    def execute(self, query, params=None):
        query = " ".join(query.split())
        self.statements.append(query)
        if query.startswith("SELECT pg_try_advisory_lock"):
            self._rows = [(self.granted,)]
        elif query.startswith("SELECT pg_advisory_unlock"):
            if self.unlock_error:
                raise self.unlock_error
            self._rows = [(True,)]
        else:
            self._rows = self.holders

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return self._rows


class TestModuleOperationsLock(unittest.TestCase):
    def tearDown(self):
        loading._module_operations_held.clear()

    def test_the_lock_is_taken_and_released(self):
        cr = _Cursor()
        with loading._module_operations_lock(cr, "db"):
            self.assertEqual(loading._module_operations_held, {"db": 1})
            self.assertEqual(cr.session_state_holds, 1, "a replay would lose the lock")
        self.assertEqual(loading._module_operations_held, {})
        self.assertEqual(cr.session_state_holds, 0)
        self.assertTrue(cr.statements[0].startswith("SELECT pg_try_advisory_lock"))
        self.assertTrue(cr.statements[-1].startswith("SELECT pg_advisory_unlock"))

    def test_a_held_lock_names_its_holder(self):
        cr = _Cursor(granted=False, holders=[(4242, "odoo-17")])
        with (
            self.assertRaisesRegex(
                loading.ModuleOperationInProgress, r"'db'.*odoo-17 \(backend 4242\)"
            ),
            loading._module_operations_lock(cr, "db"),
        ):
            self.fail("the body must not run without the lock")
        self.assertEqual(loading._module_operations_held, {})

    def test_the_uninstall_reload_reenters_without_a_second_lock(self):
        outer, inner = _Cursor(), _Cursor(granted=False)
        with loading._module_operations_lock(outer, "db"):
            with loading._module_operations_lock(inner, "db"):
                self.assertEqual(loading._module_operations_held, {"db": 2})
            self.assertEqual(loading._module_operations_held, {"db": 1})
        self.assertEqual(inner.statements, [])
        self.assertEqual(loading._module_operations_held, {})

    def test_an_aborted_transaction_leaves_the_unlock_to_the_pool(self):
        cr = _Cursor(unlock_error=psycopg.errors.InFailedSqlTransaction())
        with (
            self.assertRaises(ZeroDivisionError),
            loading._module_operations_lock(cr, "db"),
        ):
            1 / 0
        self.assertEqual(loading._module_operations_held, {})

    def test_databases_do_not_share_the_count(self):
        with loading._module_operations_lock(_Cursor(), "a"):
            with loading._module_operations_lock(_Cursor(), "b"):
                self.assertEqual(loading._module_operations_held, {"a": 1, "b": 1})
