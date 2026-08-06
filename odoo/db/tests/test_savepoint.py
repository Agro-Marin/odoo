"""Pure-Python regression tests for ``Savepoint`` depth accounting — no database.

``Savepoint`` is purely SQL (``SAVEPOINT`` / ``ROLLBACK TO`` / ``RELEASE``) plus
the cursor-level ``_savepoint_depth`` counter that ``BaseCursor.commit``/
``rollback`` read as their "inside a savepoint" guard.  The subtle invariant is
that ``__init__``'s ``+1`` is balanced by ``_close``'s ``-1`` **exactly once**,
even when the ROLLBACK TO / RELEASE SQL fails — otherwise a leaked or negative
count wedges every later commit/rollback on the cursor.

These run against a stub cursor (records SQL, can be told to raise on a given
statement), so a regression in the counting fails here, fast, instead of only
under a concurrent-DDL race in production.
"""

import unittest

from odoo.db.savepoint import Savepoint, _FlushingSavepoint


class _StubCursor:
    """Minimal stand-in for BaseCursor: records SQL and holds the depth counter."""

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
    """``_savepoint_depth`` must exist even on a half-built cursor.

    ``Savepoint`` guards its ``+1``/``-1`` with ``hasattr`` — needed because
    ``TestCursor._check_savepoint`` reuses this class with a RAW psycopg cursor,
    which has no depth counter.  That guard fails *open*: if a ``BaseCursor``
    subclass ever skipped ``super().__init__()``, the attribute would be absent,
    the counter would never move, and ``commit()`` inside a savepoint would be
    silently permitted — corrupting the savepoint's rollback state rather than
    raising.

    Every subclass in the tree does call ``super().__init__()`` today, so this
    is defence in depth, not a live defect.  The class-level default on
    ``BaseCursor`` (mirroring ``_closed``, which got one for the same reason)
    is what keeps the guard armed regardless; these tests pin both halves.
    """

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
        """The ``hasattr`` guard must stay: TestCursor passes a raw psycopg cursor."""

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
    """The savepoint seam's guard must report a seam failure, not an AttributeError.

    ``BaseCursor.savepoint`` refuses a transaction-bearing cursor a savepoint
    class that does not restore ORM state.  That check reads
    ``_restores_orm_state``, which only ``_FlushingSavepoint`` declared, so
    pointing the seam at a plain ``Savepoint`` raised ``AttributeError`` from
    inside the guard instead of the intended ``RuntimeError``.
    """

    def test_plain_savepoint_declares_it(self):
        self.assertFalse(Savepoint._restores_orm_state)

    def test_flushing_savepoint_inherits_the_same_default(self):
        self.assertFalse(_FlushingSavepoint._restores_orm_state)


if __name__ == "__main__":
    unittest.main()
