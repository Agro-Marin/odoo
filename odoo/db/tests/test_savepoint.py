import unittest

from odoo.db.savepoint import Savepoint, _FlushingSavepoint


class _StubCursor:
    def __init__(self, raise_on=None):
        self._savepoint_depth = 0
        self.sql = []
        self._raise_on = raise_on

    def execute(self, query):
        self.sql.append(query)
        if self._raise_on and self._raise_on in query:
            raise RuntimeError(f"simulated failure on: {query}")


class TestSavepointDepth(unittest.TestCase):
    def test_open_bumps_depth(self):
        cr = _StubCursor()
        sp = Savepoint(cr)
        self.assertEqual(cr._savepoint_depth, 1)
        self.assertIn(f'SAVEPOINT "{sp.name}"', cr.sql[0])

    def test_close_release_balances_to_zero(self):
        cr = _StubCursor()
        sp = Savepoint(cr)
        sp.close(rollback=False)
        self.assertEqual(cr._savepoint_depth, 0)
        self.assertTrue(sp.closed)

    def test_close_with_rollback_balances_to_zero(self):
        cr = _StubCursor()
        sp = Savepoint(cr)
        sp.close(rollback=True)
        self.assertEqual(cr._savepoint_depth, 0)
        self.assertIn("ROLLBACK TO SAVEPOINT", cr.sql[1])

    def test_failed_close_still_balances_and_marks_closed(self):
        cr = _StubCursor(raise_on="RELEASE")
        sp = Savepoint(cr)
        with self.assertRaises(RuntimeError):
            sp.close(rollback=False)
        self.assertEqual(cr._savepoint_depth, 0)
        self.assertTrue(sp.closed)

    def test_double_close_after_failure_does_not_go_negative(self):
        cr = _StubCursor(raise_on="ROLLBACK TO")
        sp = Savepoint(cr)
        with self.assertRaises(RuntimeError):
            sp.close(rollback=True)
        self.assertEqual(cr._savepoint_depth, 0)
        sp.close(rollback=True)
        self.assertEqual(cr._savepoint_depth, 0)

    def test_rollback_after_close_raises(self):
        cr = _StubCursor()
        sp = Savepoint(cr)
        sp.close(rollback=False)
        with self.assertRaises(RuntimeError):
            sp.rollback()

    def test_context_manager_releases_on_success(self):
        cr = _StubCursor()
        with Savepoint(cr) as sp:
            self.assertEqual(cr._savepoint_depth, 1)
        self.assertEqual(cr._savepoint_depth, 0)
        self.assertTrue(sp.closed)

    def test_context_manager_rolls_back_on_exception(self):
        cr = _StubCursor()
        with self.assertRaises(ValueError):
            with Savepoint(cr):
                raise ValueError("boom")
        self.assertEqual(cr._savepoint_depth, 0)
        self.assertTrue(any("ROLLBACK TO SAVEPOINT" in q for q in cr.sql))


class TestDepthCounterFailsSafe(unittest.TestCase):
    def test_base_cursor_carries_a_class_level_default(self):
        from odoo.db.cursor import BaseCursor

        self.assertEqual(BaseCursor._savepoint_depth, 0)

    def test_subclass_skipping_super_init_still_counts(self):
        from odoo.db.cursor import BaseCursor

        class _NoInitCursor(BaseCursor):
            def __init__(self):
                self.sql = []

            def execute(
                self,
                query: object,
                params: object = None,
                log_exceptions: bool = True,
                prepare: bool | None = None,
            ) -> None:
                self.sql.append(query)

        cr = _NoInitCursor()
        sp = Savepoint(cr)
        self.assertEqual(
            cr._savepoint_depth, 1, "the guard must arm even without __init__"
        )
        sp.close(rollback=False)
        self.assertEqual(cr._savepoint_depth, 0)

    def test_raw_cursor_without_the_counter_is_still_supported(self):

        class _RawLike:
            def __init__(self):
                self.sql = []

            def execute(self, query):
                self.sql.append(query)

        cr = _RawLike()
        Savepoint(cr).close(rollback=False)
        self.assertFalse(hasattr(cr, "_savepoint_depth"))
        self.assertTrue(any("RELEASE SAVEPOINT" in q for q in cr.sql))


class TestRestoresOrmStateIsDeclaredOnTheBase(unittest.TestCase):
    def test_plain_savepoint_declares_it(self):
        self.assertFalse(Savepoint._restores_orm_state)

    def test_flushing_savepoint_inherits_the_same_default(self):
        self.assertFalse(_FlushingSavepoint._restores_orm_state)


if __name__ == "__main__":
    unittest.main()


class TestOneInvalidationMechanism(unittest.TestCase):
    def test_rollback_does_not_notify_the_cursor_itself(self):
        import inspect

        src = inspect.getsource(Savepoint.rollback)
        self.assertIn("ROLLBACK TO SAVEPOINT", src)
        self.assertNotIn(
            "_on_rollback_to_savepoint",
            src,
            "the execute-path scan is the single mechanism; a second one here "
            "either double-fires or is a no-op depending on the host",
        )

    def test_rollback_still_issues_the_statement_through_the_host(self):
        calls = []

        class Host:
            def execute(self, q, *a, **k):
                calls.append(str(q))

        sp = Savepoint(Host())
        calls.clear()
        sp.rollback()
        self.assertEqual(len(calls), 1)
        self.assertIn("ROLLBACK TO SAVEPOINT", calls[0])
        self.assertIn(sp.name, calls[0])


class _FlushSpyCursor:
    def __init__(self):
        self.flush_calls = 0
        self.savepoint_flush = []

    def flush(self):
        self.flush_calls += 1

    def savepoint(self, flush=True):
        self.savepoint_flush.append(flush)
        if flush:
            self.flush()
        return Savepoint(self)

    def execute(self, query, *args, **kwargs):
        pass


class TestGetOrCreateRowFlush(unittest.TestCase):
    def test_default_flushes_through_the_savepoint(self):
        from odoo.db.savepoint import get_or_create_row

        cr = _FlushSpyCursor()
        row, created = get_or_create_row(
            cr, lambda: "row", lambda: None, conflict="row"
        )
        self.assertEqual((row, created), ("row", True))
        self.assertEqual(cr.savepoint_flush, [True])
        self.assertEqual(cr.flush_calls, 1)

    def test_flush_false_opens_the_savepoint_without_flushing(self):
        from odoo.db.savepoint import get_or_create_row

        cr = _FlushSpyCursor()
        row, created = get_or_create_row(
            cr, lambda: "row", lambda: None, conflict="row", flush=False
        )
        self.assertEqual((row, created), ("row", True))
        self.assertEqual(cr.savepoint_flush, [False])
        self.assertEqual(cr.flush_calls, 0)

    def test_flush_false_still_recovers_the_existing_row(self):
        import psycopg.errors

        from odoo.db.savepoint import get_or_create_row

        def insert():
            raise psycopg.errors.UniqueViolation

        cr = _FlushSpyCursor()
        row, created = get_or_create_row(
            cr, insert, lambda: "existing", conflict="row", flush=False
        )
        self.assertEqual((row, created), ("existing", False))
        self.assertEqual(cr.flush_calls, 0)
