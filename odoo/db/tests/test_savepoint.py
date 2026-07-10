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

from odoo.db.savepoint import Savepoint


class _StubCursor:
    """Minimal stand-in for BaseCursor: records SQL and holds the depth counter."""

    def __init__(self, raise_on=None):
        self._savepoint_depth = 0
        self.sql = []
        # substring that, when present in an executed statement, raises — used
        # to simulate a ROLLBACK TO / RELEASE against a savepoint that no longer
        # exists (e.g. released behind the object's back).
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
        # RELEASE fails, but the depth must still return to 0 and the savepoint
        # must be marked closed (so it is never retried).
        cr = _StubCursor(raise_on="RELEASE")
        sp = Savepoint(cr)
        with self.assertRaises(RuntimeError):
            sp.close(rollback=False)
        self.assertEqual(cr._savepoint_depth, 0)
        self.assertTrue(sp.closed)

    def test_double_close_after_failure_does_not_go_negative(self):
        # H3 regression: a ROLLBACK TO that fails (savepoint released behind our
        # back) used to leave closed=False, so a second close() decremented the
        # depth again — driving it to -1 and permanently wedging the cursor.
        cr = _StubCursor(raise_on="ROLLBACK TO")
        sp = Savepoint(cr)
        with self.assertRaises(RuntimeError):
            sp.close(rollback=True)
        self.assertEqual(cr._savepoint_depth, 0)
        # A second close() must be a no-op (the close() gate reads .closed).
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


if __name__ == "__main__":
    unittest.main()
