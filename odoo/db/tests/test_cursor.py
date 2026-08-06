"""Tier-1 (database-free) tests for :mod:`odoo.db.cursor` and :mod:`odoo.db.metrics`.

Everything here exercises :class:`BaseCursor` — the hooks, the flush-convergence
budget, the ORM savepoint seam and the context-manager contract — plus the
metrics mixin, none of which need a server.  The real :class:`Cursor` (borrow,
COPY, DDL detection against a live backend) stays in
``odoo/addons/base/tests/test_db_cursor.py``.
"""

import unittest

from odoo.db import metrics
from odoo.db.cursor import BaseCursor
from odoo.db.savepoint import Savepoint, _FlushingSavepoint
from odoo.tools import SQL


class _Cursor(BaseCursor):
    """Minimal concrete BaseCursor: records SQL instead of executing it."""

    def __init__(self):
        super().__init__()
        self.dbname = "fake"
        self.statements = []
        self.committed = 0
        self.closed_count = 0

    def execute(self, query, params=None, log_exceptions=True):
        self.statements.append(str(query))

    def commit(self):
        self.committed += 1

    def close(self):
        self.closed_count += 1
        self._closed = True


class _Transaction:
    """Stand-in ORM transaction whose ``flush()`` queues follow-up precommit
    work for the first *rounds* calls — the cross-pass ping-pong the flush
    budget exists to bound."""

    def __init__(self, cr, rounds=0):
        self.cr = cr
        self.rounds = rounds
        self.flush_calls = 0
        self.cleared = 0
        self.reset_calls = 0

    def flush(self):
        self.flush_calls += 1
        if self.flush_calls <= self.rounds:
            self.cr.precommit.add(lambda: None)

    def clear(self):
        self.cleared += 1

    def reset(self):
        self.reset_calls += 1


def _attach(cr, rounds=0):
    """Attach a stand-in transaction to *cr* and return it.

    ``BaseCursor.transaction`` is typed ``Transaction | None``; substituting a
    stand-in is the whole point here, so the mismatch is asserted once rather
    than at each call site, and the returned handle keeps the fake's own
    counters readable without narrowing an Optional.
    """
    txn = _Transaction(cr, rounds)
    cr.transaction = txn
    return txn


class TestContextManagerContract(unittest.TestCase):
    """``__exit__`` reads ``_closed``, so it must be part of the base contract.

    Regression: ``BaseCursor`` only *annotated* ``_closed``.  A subclass that
    did not define it (``InMemoryCursor``) raised AttributeError from
    ``__exit__`` — after ``close()`` had already run in the ``finally`` — which
    silently skipped the commit and masked whatever the block was doing.
    ``registry.cursor()`` is typed ``-> BaseCursor``, so any subclass returned
    from there inherits this contract.
    """

    def test_closed_is_a_class_level_default_on_the_base(self):
        self.assertIs(BaseCursor._closed, False)

    def test_clean_exit_commits_then_closes(self):
        cr = _Cursor()
        with cr:
            pass
        self.assertEqual((cr.committed, cr.closed_count), (1, 1))

    def test_exception_closes_without_committing(self):
        cr = _Cursor()
        with self.assertRaises(ValueError), cr:
            raise ValueError("boom")
        self.assertEqual((cr.committed, cr.closed_count), (0, 1))

    def test_body_closing_the_cursor_skips_the_commit(self):
        """Nothing to commit and the connection is already back in the pool;
        committing here would raise on the closed cursor."""
        cr = _Cursor()
        with cr:
            cr.close()
        self.assertEqual(cr.committed, 0)
        self.assertEqual(cr.closed_count, 2)


class TestFlushConvergence(unittest.TestCase):
    """``flush()`` drains precommit work until a pass produces none.

    The contract is that a hook signals follow-up work by dirtying the ORM (which
    the NEXT pass re-queues), never by re-adding itself — that would spin forever
    inside ``Callbacks.run()``, which this budget cannot catch.
    """

    def test_no_transaction_and_no_hooks_is_a_noop(self):
        cr = _Cursor()
        cr.flush()

    def test_hooks_run_once_and_are_drained(self):
        cr = _Cursor()
        calls = []
        cr.precommit.add(lambda: calls.append(1))
        cr.flush()
        self.assertEqual(calls, [1])
        self.assertFalse(cr.precommit)

    def test_converging_chain_settles_without_raising(self):
        cr = _Cursor()
        txn = _attach(cr, rounds=3)
        cr.flush()
        self.assertEqual(txn.flush_calls, 4)

    def test_chain_settling_on_the_very_last_pass_does_not_raise(self):
        """This is why the final flush after the loop exists: the convergence
        check runs BEFORE each ``run()``, so without it the last pass's effect
        is never re-examined and a chain that just settled would raise."""
        cr = _Cursor()
        txn = _attach(cr, rounds=BaseCursor._MAX_FLUSH_PASSES)
        cr.flush()
        self.assertEqual(txn.flush_calls, BaseCursor._MAX_FLUSH_PASSES + 1)

    def test_non_converging_chain_raises_instead_of_dropping_work(self):
        """commit() would otherwise COMMIT and clear() the still-pending hooks,
        silently discarding their work."""
        cr = _Cursor()
        _attach(cr, rounds=BaseCursor._MAX_FLUSH_PASSES + 1)
        with self.assertRaises(RuntimeError) as ctx:
            cr.flush()
        self.assertIn("did not converge", str(ctx.exception))
        self.assertTrue(cr.precommit, "pending hooks must survive the failure")

    def test_clear_drops_transaction_state_and_precommit(self):
        cr = _Cursor()
        txn = _attach(cr)
        cr.precommit.add(lambda: None)
        cr.clear()
        self.assertEqual(txn.cleared, 1)
        self.assertFalse(cr.precommit)


class TestSavepointSeam(unittest.TestCase):
    """``savepoint(flush=True)`` resolves through ``_flushing_savepoint_cls`` so
    the ORM can inject its cache-restoring subclass without db importing it."""

    class _NonRestoring(_FlushingSavepoint):
        _restores_orm_state = False

    def test_flushing_savepoint_is_used_by_default(self):
        cr = _Cursor()
        cr._flushing_savepoint_cls = self._NonRestoring
        sp = cr.savepoint()
        self.assertIsInstance(sp, _FlushingSavepoint)
        self.assertEqual(cr.statements, ['SAVEPOINT "%s"' % sp.name])
        self.assertEqual(cr._savepoint_depth, 1)

    def test_flush_false_uses_the_plain_savepoint(self):
        cr = _Cursor()
        sp = cr.savepoint(flush=False)
        self.assertIsInstance(sp, Savepoint)
        self.assertNotIsInstance(sp, _FlushingSavepoint)

    def test_db_layer_flushing_savepoint_does_not_restore_orm_state(self):
        """The db-layer class is deliberately ORM-blind; the ORM subclass flips
        this flag on itself, which is what the guard below keys on."""
        self.assertFalse(_FlushingSavepoint._restores_orm_state)

    def test_transaction_bearing_cursor_refuses_a_non_restoring_savepoint(self):
        """Fail loudly rather than corrupt the ORM cache: a cursor carrying a
        transaction MUST use a savepoint that restores ORM state on rollback.
        If it does not, the odoo.orm.runtime seam was never installed (an
        import-order bug) and ROLLBACK TO SAVEPOINT would leave a stale cache.
        """
        cr = _Cursor()
        cr._flushing_savepoint_cls = self._NonRestoring
        _attach(cr)
        with self.assertRaises(RuntimeError) as ctx:
            cr.savepoint()
        self.assertIn("does not restore ORM state", str(ctx.exception))
        self.assertEqual(cr._savepoint_depth, 0, "no savepoint may have opened")

    def test_rollback_to_savepoint_hook_is_a_noop_on_the_base(self):
        """Declared on BaseCursor so ``Savepoint`` can call it without knowing
        which cursor flavour it holds; only the real Cursor carries
        transaction-scoped catalog facts to drop."""
        cr = _Cursor()
        cr._on_rollback_to_savepoint()

    def test_discard_cached_plans_is_a_noop_on_the_base(self):
        _Cursor().discard_cached_plans()


class TestDictFetchHelpers(unittest.TestCase):
    """The base implements the ``dictfetch*`` family over ``dictfetchone``."""

    class _Rows(_Cursor):
        def __init__(self, rows):
            super().__init__()
            self._rows = list(rows)

        def dictfetchone(self):
            return self._rows.pop(0) if self._rows else None

        def fetchone(self):
            return self._rows.pop(0) if self._rows else None

    def test_dictfetchall_drains(self):
        cr = self._Rows([{"a": 1}, {"a": 2}])
        self.assertEqual(cr.dictfetchall(), [{"a": 1}, {"a": 2}])
        self.assertEqual(cr.dictfetchall(), [])

    def test_dictfetchmany_respects_size_and_exhaustion(self):
        cr = self._Rows([{"a": 1}, {"a": 2}, {"a": 3}])
        self.assertEqual(cr.dictfetchmany(2), [{"a": 1}, {"a": 2}])
        self.assertEqual(cr.dictfetchmany(5), [{"a": 3}])

    def test_dictfetchmany_non_positive_size_yields_nothing(self):
        cr = self._Rows([{"a": 1}])
        for size in (0, -1):
            with self.subTest(size=size):
                self.assertEqual(cr.dictfetchmany(size), [])

    def test_fetchscalar_returns_none_on_no_rows(self):
        """Eliminates the ``cr.fetchone()[0]`` pattern, which raises on empty."""
        self.assertIsNone(self._Rows([]).fetchscalar())
        self.assertEqual(self._Rows([(7, "x")]).fetchscalar(), 7)


class _MetricsCursor(metrics._MetricsMixin):
    def __init__(self):
        import threading

        self._thread = threading.current_thread()
        self.sql_from_log = {}
        self.sql_into_log = {}
        self.sql_log_count = 0


class TestMetricsMixin(unittest.TestCase):
    def setUp(self):
        self._saved = metrics.sql_counter
        self.addCleanup(setattr, metrics, "sql_counter", self._saved)
        self.cur = _MetricsCursor()

    def test_record_metrics_bumps_both_counters(self):
        metrics.sql_counter = 0
        self.cur._record_metrics(0.01)
        self.cur._record_metrics(0.01, count=5)
        self.assertEqual(self.cur.sql_log_count, 6)
        self.assertEqual(metrics.sql_counter, 6)

    def test_record_metrics_runs_query_hooks_with_the_call_context(self):
        seen = []
        self.cur._record_metrics(
            0.5, query="Q", params=(1,), start=2.0, hooks=[lambda *a: seen.append(a)]
        )
        self.assertEqual(seen, [(self.cur, "Q", (1,), 2.0, 0.5)])

    def test_record_metrics_tolerates_a_thread_without_metric_attrs(self):
        self.cur._record_metrics(0.01)

    def test_record_sql_log_buckets_reads_and_writes(self):
        self.cur._record_sql_log("from", "res_users", 0.001)
        self.cur._record_sql_log("from", "res_users", 0.002)
        self.cur._record_sql_log("into", "res_partner", 0.004)
        self.cur._record_sql_log("other", None, 9.0)
        self.assertEqual(self.cur.sql_from_log["res_users"][0], 2)
        self.assertEqual(self.cur.sql_into_log["res_partner"][0], 1)
        self.assertNotIn(None, self.cur.sql_from_log)

    def test_format_interpolates_positional_and_named_params(self):
        self.assertEqual(self.cur._format("SELECT 1"), "SELECT 1")
        self.assertEqual(self.cur._format("a=%s", (1,)), "a=1")
        self.assertEqual(self.cur._format("a=%(k)s", {"k": 2}), "a=2")

    def test_format_unwraps_sql_objects(self):
        self.assertEqual(self.cur._format(SQL("a=%s", 3)), "a=3")

    def test_format_falls_back_instead_of_raising(self):
        """Debug formatting must never break the query path — a mismatched
        placeholder count would otherwise raise inside logging."""
        out = self.cur._format("a=%s b=%s", (1,))
        self.assertIn("a=%s b=%s", out)
        self.assertIn("(1,)", out)


class TestBeforeStatementSeam(unittest.TestCase):
    """Every statement entry point announces itself through one hook.

    ``odoo.tests.cursor.TestCursor`` creates its rollback savepoint lazily on
    first use.  It used to hang that off its own ``execute()`` override, so the
    bulk APIs it does not override reached the real cursor via ``__getattr__``
    and wrote outside the savepoint — verified against a live database: rows
    written by ``copy_from``/``executemany``/``execute_values`` survived the
    test rollback while ``execute``'s did not.
    """

    def test_base_cursor_hook_is_a_noop(self):
        self.assertIsNone(_Cursor()._before_statement())

    def test_every_statement_entry_point_calls_it(self):
        missing = [name for name in _STATEMENT_APIS if name not in _marks_statements()]
        self.assertEqual(
            missing,
            [],
            "a statement entry point that skips the hook lets a wrapper cursor's "
            "per-statement bookkeeping be bypassed silently",
        )

    def test_the_hook_marks_exactly_the_known_entry_points(self):
        self.assertEqual(
            _marks_statements(),
            set(_STATEMENT_APIS),
            "update _STATEMENT_APIS (and TestCursor) when the set changes",
        )


_STATEMENT_APIS = ("execute", "executemany", "execute_values", "copy_from", "copy")


def _marks_statements() -> set:
    """Names on :class:`Cursor` whose body calls ``_before_statement``."""
    from odoo.db.cursor import Cursor

    return {
        name
        for name in dir(Cursor)
        if callable(getattr(Cursor, name, None))
        and getattr(getattr(Cursor, name), "__code__", None) is not None
        and "_before_statement" in getattr(Cursor, name).__code__.co_names
    }


if __name__ == "__main__":
    unittest.main()
