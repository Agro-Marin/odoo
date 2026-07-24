import inspect
import json
import logging
import os
import threading
import time
import warnings
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from unittest.mock import MagicMock, patch

import psycopg
from psycopg import IsolationLevel
from psycopg_pool import PoolTimeout

from odoo import api
from odoo.db import db_connect
from odoo.db import pool as pool_module
from odoo.db import utils as _db_utils
from odoo.db.cursor import (
    Cursor,
    _FlushingSavepoint,
)
from odoo.db.lifecycle import (
    _HEALTHCHECK_GRACE_PERIOD,
    _IDLE_SINCE_ATTR,
    _RESET_SESSION_STATE_SQL,
)
from odoo.db.pool import (
    Connection,
    ConnectionPool,
    PoolError,
    _check_connection,
    _configure_connection,
    _normalize_dsn_key,
    _reset_connection,
    _SuppressKnownPoolWarnings,
)
from odoo.db.schema_cache import schema_cache
from odoo.db.utils import categorize_query, connection_info_for
from odoo.modules.registry import Registry
from odoo.service.db import exp_drop
from odoo.tests import common
from odoo.tests.common import BaseCase, HttpCase
from odoo.tests.cursor import TestCursor
from odoo.tools import SQL

ADMIN_USER_ID = common.ADMIN_USER_ID

# Alias the SchemaCache singleton's backing dicts so the white-box cache tests
# below assert on the same shared state.  clear()/set_* mutate in place (never
# reassign), so the aliases stay valid for the life of the process.
_id_sequence_cache = schema_cache._id_sequences
_column_type_cache = schema_cache._column_types


def registry():
    return Registry(common.get_db_name())


class TestRealCursor(BaseCase):
    def test_execute_bad_params(self):
        """Reject iterable-but-non-list and scalar params."""
        with registry().cursor() as cr:
            with self.assertRaises(ValueError):
                cr.execute("SELECT id FROM res_users WHERE login=%s", "admin")
            with self.assertRaises(ValueError):
                cr.execute("SELECT id FROM res_users WHERE id=%s", 1)
            with self.assertRaises(ValueError):
                cr.execute("SELECT id FROM res_users WHERE id=%s", "1")

    def test_using_closed_cursor(self):
        with registry().cursor() as cr:
            cr.close()
            with self.assertRaises(psycopg.InterfaceError):
                cr.execute("SELECT 1", log_exceptions=False)

    def test_commit_rollback_on_closed_cursor_raise(self):
        # After close() returns the connection to the pool it may be checked out
        # by another cursor; commit()/rollback() must raise rather than silently
        # act on that (possibly foreign) connection.
        cr = registry().cursor()
        cr.close()
        with self.assertRaises(psycopg.InterfaceError):
            cr.commit()
        with self.assertRaises(psycopg.InterfaceError):
            cr.rollback()

    def test_multiple_close_call_cursor(self):
        cr = registry().cursor()
        cr.close()
        cr.close()

    def test_transaction_isolation_cursor(self):
        with registry().cursor() as cr:
            self.assertEqual(
                cr.connection.isolation_level, IsolationLevel.REPEATABLE_READ
            )

    def test_connection_readonly(self):
        # even without db_replica, we expect the connection to be readonly for consistency
        registry_ = registry()
        with registry_.cursor(readonly=False) as cr:
            cr.execute("SHOW transaction_read_only")
            self.assertEqual(cr.fetchone(), ("off",))
            self.assertFalse(cr.readonly)

        with registry_.cursor(readonly=True) as cr:
            cr.execute("SHOW transaction_read_only")
            self.assertEqual(cr.fetchone(), ("on",))
            self.assertTrue(cr.readonly)


class TestSeedPlannerStats(BaseCase):
    """``seed_planner_stats`` floors reltuples/relpages for never-analyzed tables.

    Test transactions always roll back, so test-only tables keep committed
    "empty" stats forever; the planner then estimates ``rows=1`` and builds
    cartesian nested-loop plans that slow down quadratically as a class
    accumulates rows.  The floor keeps join order and index choice sane;
    ``_run_post_install_tests`` seeds once per suite.
    """

    def test_seeds_floors_for_zero_stat_tables(self):
        from odoo.db.utils import seed_planner_stats

        cr = registry().cursor()
        try:
            # Fresh table: reltuples=0 / relpages=0 — the planner-blind signature.
            cr.execute(
                'CREATE TABLE "_test_seed_planner_stats" '
                "(id serial PRIMARY KEY, val integer)"
            )
            seeded = seed_planner_stats(cr)
            self.assertGreaterEqual(seeded, 1)

            cr.execute(
                "SELECT reltuples::int, relpages FROM pg_class "
                "WHERE relname = '_test_seed_planner_stats'"
            )
            reltuples, relpages = cr.fetchone()
            self.assertGreater(reltuples, 0)
            self.assertGreater(relpages, 0)

            # Idempotent: a second pass finds nothing left to seed.
            self.assertEqual(seed_planner_stats(cr), 0)
        finally:
            # Catalog updates are transactional: roll back to leave pg_class clean.
            cr.rollback()
            cr.close()


class TestSeedPlannerStatsInClassTransaction(common.TransactionCase):
    """Every TransactionCase must see planner-stat floors on all its tables.

    Autovacuum can undo the committed pre-suite seeding mid-suite (VACUUM
    rewrites ``reltuples = 0`` for always-rolled-back tables and invalidates the
    relcache), reintroducing the cartesian nested-loop pathology.  ``setUpClass``
    re-seeds inside the class transaction; the stats locks keep autovacuum off
    the seeded tables while the class runs.
    """

    def test_no_zero_stat_tables_visible(self):
        self.env.cr.execute(
            """
            SELECT c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.relkind = 'r'
               AND n.nspname = 'public'
               AND c.reltuples <= 0
               AND c.relowner = quote_ident(current_user)::regrole
            """
        )
        self.assertEqual([row[0] for row in self.env.cr.fetchall()], [])


class TestHTTPCursor(HttpCase):
    def test_cursor_keeps_readwriteness(self):
        with self.env.registry.cursor(readonly=False) as cr:
            self.assertFalse(cr.readonly)
            cr.execute("SELECT 1")
            cr.rollback()
            self.assertFalse(cr.readonly)
            cr.execute("SELECT 1")
            cr.commit()
            self.assertFalse(cr.readonly)

        with self.env.registry.cursor(readonly=True) as cr:
            self.assertTrue(cr.readonly)
            cr.execute("SELECT 1")
            cr.rollback()
            self.assertTrue(cr.readonly)
            cr.execute("SELECT 1")
            cr.commit()
            self.assertTrue(cr.readonly)

    def test_call_kw_readonly(self):
        self.authenticate("admin", "admin")
        _ = self.env.user.partner_id.id

        # Patcher reporting whether the method ran on a readonly cursor.
        def return_readonly(self, *args, **kwargs):
            return ["ok", self.env.cr.readonly]

        with patch.object(type(self.env["res.partner"]), "read", return_readonly):
            result_read = self.url_open(
                "/web/dataset/call_kw",
                data=json.dumps(
                    {
                        "params": {
                            "model": "res.partner",
                            "method": "read",
                            "args": [self.env.user.partner_id.id, ["name"]],
                            "kwargs": {},
                        },
                    }
                ),
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(result_read.status_code, 200)
            ok, readonly = result_read.json()["result"]
            self.assertEqual(ok, "ok")
            self.assertEqual(readonly, True, "Call to read are expecte to be read only")

        with patch.object(type(self.env["res.partner"]), "write", return_readonly):
            result_write = self.url_open(
                "/web/dataset/call_kw",
                data=json.dumps(
                    {
                        "params": {
                            "model": "res.partner",
                            "method": "write",
                            "args": [
                                self.env.user.partner_id.id,
                                {"name": "Urgo"},
                            ],
                            "kwargs": {},
                        },
                    }
                ),
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(result_write.status_code, 200)
            ok, readonly = result_write.json()["result"]
            self.assertEqual(ok, "ok")
            self.assertEqual(
                readonly, False, "Call to write are expecte to be read write"
            )


class TestTestCursor(common.TransactionCase):
    def setUp(self):
        super().setUp()
        self.registry_enter_test_mode()
        self.cr = self.registry.cursor()
        self.addCleanup(self.cr.close)
        self.env = api.Environment(self.cr, api.SUPERUSER_ID, {})
        self.record = self.env["res.partner"].create({"name": "Foo"})

    def write(self, record, value):
        record.ref = value

    def flush(self, record):
        record.flush_model(["ref"])

    def check(self, record, value):
        # force a re-read from the database
        record.invalidate_recordset()
        self.assertEqual(record.read(["ref"])[0]["ref"], value)

    def test_single_cursor(self):
        """Check the behavior of a single test cursor."""
        self.assertIsInstance(self.cr, TestCursor)
        self.write(self.record, "A")
        self.cr.commit()

        self.write(self.record, "B")
        self.cr.rollback()
        self.check(self.record, "A")

        self.write(self.record, "C")
        self.cr.rollback()
        self.check(self.record, "A")

    def test_now_is_utc_and_resets(self):
        """TestCursor.now() must mirror the real cursor: naive UTC, cached, and
        reset on commit/rollback.  The old ``datetime.now()`` returned local
        time, landing test create_date/write_date hours off on a non-UTC host.
        """
        self.assertIsInstance(self.cr, TestCursor)
        self.cr.commit()  # drop any timestamp cached during setUp
        self.assertIsNone(self.cr._now)

        t = self.cr.now()
        self.assertIsNone(t.tzinfo, "now() must be naive")
        utc_naive = datetime.now(UTC).replace(tzinfo=None)
        # 600s tolerance is CI-generous yet still catches the ~6h local-vs-UTC
        # skew on a non-UTC host (e.g. America/Mexico_City).
        self.assertLess(
            abs((utc_naive - t).total_seconds()),
            600,
            "TestCursor.now() is not UTC — local-time regression",
        )
        self.assertIs(self.cr.now(), t, "now() must be cached within a transaction")

        self.cr.commit()
        self.assertIsNone(self.cr._now, "commit() must reset now()")
        self.cr.now()
        self.cr.rollback()
        self.assertIsNone(self.cr._now, "rollback() must reset now()")

    def test_fetch_helpers_forward_to_real_cursor(self):
        """Regression: BaseCursor.fetchscalar must not shadow TestCursor's
        __getattr__ forwarding.

        fetchscalar is defined on BaseCursor (fetchone is not), so TestCursor
        resolves it to the base rather than forwarding.  The base now implements
        it over self.fetchone() so every subclass inherits a working version.
        """
        self.assertIsInstance(self.cr, TestCursor)

        self.cr.execute("SELECT 42")
        self.assertEqual(self.cr.fetchscalar(), 42)

        # empty result set -> None, not IndexError on fetchone()[0]
        self.cr.execute("SELECT 1 WHERE FALSE")
        self.assertIsNone(self.cr.fetchscalar())

        # the fetch helpers that were already forwarding must keep working
        self.cr.execute("SELECT 7 AS v")
        self.assertEqual(self.cr.fetchone(), (7,))
        self.cr.execute("SELECT 7 AS v")
        self.assertEqual(self.cr.dictfetchone(), {"v": 7})

    def test_sub_commit(self):
        """Check the behavior of a subcursor that commits."""
        self.assertIsInstance(self.cr, TestCursor)
        self.write(self.record, "A")
        self.cr.commit()

        self.write(self.record, "B")
        self.flush(self.record)

        # check behavior of a "sub-cursor" that commits
        with self.registry.cursor() as cr:
            self.assertIsInstance(cr, TestCursor)
            record = self.record.with_env(self.env(cr=cr))
            self.check(record, "B")
            self.write(record, "C")

        self.check(self.record, "C")

        self.cr.rollback()
        self.check(self.record, "A")

    def test_sub_rollback(self):
        """Check the behavior of a subcursor that rollbacks."""
        self.assertIsInstance(self.cr, TestCursor)
        self.write(self.record, "A")
        self.cr.commit()

        self.write(self.record, "B")
        self.flush(self.record)

        # check behavior of a "sub-cursor" that rollbacks
        with self.assertRaises(ValueError):
            with self.registry.cursor() as cr:
                self.assertIsInstance(cr, TestCursor)
                record = self.record.with_env(self.env(cr=cr))
                self.check(record, "B")
                self.write(record, "C")
                raise ValueError(42)

        self.check(self.record, "B")

        self.cr.rollback()
        self.check(self.record, "A")

    def test_interleaving(self):
        """Independently retrieved test cursors can interleave their savepoint
        operations (some are lazy, e.g. the request cursor) and release one
        another:

        .. code-block:: sql

            SAVEPOINT A
            SAVEPOINT B
            RELEASE SAVEPOINT A
            RELEASE SAVEPOINT B -- "savepoint b does not exist"
        """
        a = self.registry.cursor()
        b = self.registry.cursor()
        # force the savepoints to be created
        a._check_savepoint()
        b._check_savepoint()
        # closing `a` out of order warns, removes only `a`, and leaves the
        # still-open `b` on the stack (it used to evict `b` instead)
        with self.assertLogs("odoo.db.cursor", level=logging.WARNING) as cm:
            a.close()
        [msg] = cm.output
        self.assertIn("WARNING:odoo.db.cursor:Out-of-order close", msg)
        self.assertIn(b, TestCursor._cursors_stack)
        # `b`'s savepoint was destroyed by `a`'s rollback past it; closing it
        # surfaces the SQL error but cleans up without further warnings
        with self.assertNoLogs("odoo.db.cursor", level=logging.WARNING):
            with self.assertRaises(psycopg.errors.InvalidSavepointSpecification):
                b.close()
        self.assertNotIn(b, TestCursor._cursors_stack)

    def test_borrow_connection(self):
        """Pool recycles a returned connection to the next borrower.

        Connections are pooled per-database; compare backend PIDs rather than
        Python object identity (each getconn wraps a fresh ``psycopg.Connection``).

        Uses a PRIVATE pool rather than the process-wide one: "the connection I
        just released comes back to me" only holds while nothing else borrows
        from that pool, and after an HttpCase suite the live server, cron and
        bus threads are still checking connections in and out of the global
        pool — one of them takes the freed slot and this asserts a different
        backend pid. Isolating the pool tests the recycling contract itself
        instead of the ambient concurrency of whatever ran before.
        """
        cursors = []
        pool = ConnectionPool(maxconn=4)
        self.addCleanup(pool.close_all)
        db, info = connection_info_for(self.cr.dbname)
        try:
            connection = Connection(pool, db, info)

            # Two live cursors must not share a connection.
            cursors.extend((connection.cursor(), connection.cursor()))
            pid0 = cursors[0].connection.info.backend_pid
            pid1 = cursors[1].connection.info.backend_pid
            self.assertNotEqual(pid0, pid1)

            # Closing the 1st, a 3rd cursor must reuse the 1st's connection.
            cursors[0].close()
            cursors.append(connection.cursor())
            pid2 = cursors[2].connection.info.backend_pid
            self.assertEqual(pid0, pid2)

        finally:
            for cursor in cursors:
                if not cursor.closed:
                    cursor.close()


class TestCursorHooks(common.TransactionCase):
    def setUp(self):
        super().setUp()
        self.log = []

    def prepare_hooks(self, cr):
        self.log.clear()
        cr.precommit.add(partial(self.log.append, "preC"))
        cr.postcommit.add(partial(self.log.append, "postC"))
        cr.prerollback.add(partial(self.log.append, "preR"))
        cr.postrollback.add(partial(self.log.append, "postR"))
        self.assertEqual(self.log, [])

    def test_hooks_on_cursor(self):
        cr = self.registry.cursor()

        # check hook on commit()
        self.prepare_hooks(cr)
        cr.commit()
        self.assertEqual(self.log, ["preC", "postC"])

        # check hook on flush(), then on rollback()
        self.prepare_hooks(cr)
        cr.flush()
        self.assertEqual(self.log, ["preC"])
        cr.rollback()
        self.assertEqual(self.log, ["preC", "preR", "postR"])

        # check hook on close()
        self.prepare_hooks(cr)
        cr.close()
        self.assertEqual(self.log, ["preR", "postR"])

    def test_hooks_on_testcursor(self):
        self.registry_enter_test_mode()

        cr = self.registry.cursor()

        # check hook on commit(); post-commit hooks are ignored
        self.prepare_hooks(cr)
        cr.commit()
        self.assertEqual(self.log, ["preC"])

        # check hook on flush(), then on rollback()
        self.prepare_hooks(cr)
        cr.flush()
        self.assertEqual(self.log, ["preC"])
        cr.rollback()
        self.assertEqual(self.log, ["preC", "preR", "postR"])

        # check hook on close()
        self.prepare_hooks(cr)
        cr.close()
        self.assertEqual(self.log, ["preR", "postR"])


class TestCursorHooksTransactionCaseCleanup(common.TransactionCase):
    """Check savepoint cases handle commit hooks properly."""

    @staticmethod
    def initial_callback():
        pass

    @staticmethod
    def other_callback():
        pass

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cr = cls.env.cr
        cls.callback_names = [
            "precommit",
            "postcommit",
            "prerollback",
            "postrollback",
        ]
        cls.callbacks = [
            cr.precommit,
            cr.postcommit,
            cr.prerollback,
            cr.postrollback,
        ]

        for callback, name in zip(cls.callbacks, cls.callback_names, strict=False):
            callback.data[f"test_cursor_hooks_{name}"] = ["keep"]
            callback.add(cls.initial_callback)

    def assertHookData(self):
        for callback, name in zip(self.callbacks, self.callback_names, strict=False):
            self.assertEqual(
                callback.data[f"test_cursor_hooks_{name}"],
                ["keep"],
                f"{name} failed to clean up between transaction tests",
            )
            self.assertIn(self.initial_callback, callback._funcs)
            self.assertNotIn(self.other_callback, callback._funcs)

    def test_1_isolation(self):
        self.assertHookData()
        for callback, name in zip(self.callbacks, self.callback_names, strict=False):
            callback.data[f"test_cursor_hooks_{name}"].append("don't keep")
            callback.add(self.other_callback)

    def test_2_isolation(self):
        self.assertHookData()
        for callback in self.callbacks:
            callback.run()

    def test_3_isolation(self):
        self.assertHookData()
        for callback in self.callbacks:
            callback.clear()

    def test_4_isolation(self):
        self.assertHookData()
        self.env.cr.clear()

    def test_5_isolation(self):
        self.assertHookData()


class TestNumericToFloat(common.TransactionCase):
    """Test that PostgreSQL numeric values are loaded as Python floats."""

    def test_numeric_column_returns_float(self):
        """Ensure the _NumericToFloatLoader adapter is active."""
        self.env.cr.execute("SELECT 1.5::numeric")
        val = self.env.cr.fetchone()[0]
        self.assertIsInstance(val, float)
        self.assertEqual(val, 1.5)

    def test_numeric_null_returns_none(self):
        self.env.cr.execute("SELECT NULL::numeric")
        val = self.env.cr.fetchone()[0]
        self.assertIsNone(val)

    def test_numeric_precision(self):
        self.env.cr.execute("SELECT 123456789.123456789::numeric")
        val = self.env.cr.fetchone()[0]
        self.assertIsInstance(val, float)
        self.assertAlmostEqual(val, 123456789.123456789)


class TestCursorFetchMethods(BaseCase):
    """Test fetchscalar, dictfetchone, dictfetchmany, dictfetchall."""

    def test_fetchscalar_value(self):
        with registry().cursor() as cr:
            cr.execute("SELECT 42")
            self.assertEqual(cr.fetchscalar(), 42)

    def test_fetchscalar_null(self):
        """fetchscalar returns None for NULL values (not the row tuple)."""
        with registry().cursor() as cr:
            cr.execute("SELECT NULL::int")
            self.assertIsNone(cr.fetchscalar())

    def test_fetchscalar_empty(self):
        """fetchscalar returns None when no rows match."""
        with registry().cursor() as cr:
            cr.execute("SELECT 1 WHERE FALSE")
            self.assertIsNone(cr.fetchscalar())

    def test_fetchscalar_multi_column(self):
        """fetchscalar returns the first column value only."""
        with registry().cursor() as cr:
            cr.execute("SELECT 1, 2, 3")
            self.assertEqual(cr.fetchscalar(), 1)

    def test_dictfetchone(self):
        with registry().cursor() as cr:
            cr.execute("SELECT 1 AS a, 'hello' AS b")
            self.assertEqual(cr.dictfetchone(), {"a": 1, "b": "hello"})

    def test_dictfetchone_empty(self):
        with registry().cursor() as cr:
            cr.execute("SELECT 1 AS a WHERE FALSE")
            self.assertIsNone(cr.dictfetchone())

    def test_dictfetchmany(self):
        with registry().cursor() as cr:
            cr.execute("SELECT generate_series(1, 5) AS v")
            rows = cr.dictfetchmany(3)
            self.assertEqual(len(rows), 3)
            self.assertEqual([r["v"] for r in rows], [1, 2, 3])

    def test_dictfetchmany_exceeds_available(self):
        """Requesting more rows than available returns only what's there."""
        with registry().cursor() as cr:
            cr.execute("SELECT generate_series(1, 2) AS v")
            rows = cr.dictfetchmany(10)
            self.assertEqual(len(rows), 2)

    def test_dictfetchall(self):
        with registry().cursor() as cr:
            cr.execute("SELECT generate_series(1, 3) AS v")
            rows = cr.dictfetchall()
            self.assertEqual(len(rows), 3)
            self.assertEqual([r["v"] for r in rows], [1, 2, 3])

    def test_dictfetchall_empty(self):
        with registry().cursor() as cr:
            cr.execute("SELECT 1 AS v WHERE FALSE")
            self.assertEqual(cr.dictfetchall(), [])


class TestCursorNow(BaseCase):
    """Test now() caching and reset behavior."""

    def test_now_returns_datetime(self):
        with registry().cursor() as cr:
            result = cr.now()
            self.assertIsInstance(result, datetime)

    def test_now_cached_within_transaction(self):
        """Repeated calls return the exact same object (cached)."""
        with registry().cursor() as cr:
            t1 = cr.now()
            t2 = cr.now()
            self.assertIs(t1, t2)

    def test_now_reset_after_commit(self):
        """commit() resets the cached timestamp."""
        with registry().cursor() as cr:
            cr.now()
            self.assertIsNotNone(cr._now)
            cr.commit()
            self.assertIsNone(cr._now)

    def test_now_reset_after_rollback(self):
        """rollback() resets the cached timestamp."""
        with registry().cursor() as cr:
            cr.now()
            self.assertIsNotNone(cr._now)
            cr.rollback()
            self.assertIsNone(cr._now)

    def test_now_survives_savepoint(self):
        """A savepoint (release OR rollback) must NOT invalidate the cache.

        now() is the transaction start timestamp, reset only by
        commit()/rollback(); assertIs proves it was not recomputed.
        """
        with registry().cursor() as cr:
            t1 = cr.now()
            with cr.savepoint():  # released (successful) savepoint
                cr.execute("SELECT 1")
            self.assertIs(cr.now(), t1)
            with cr.savepoint() as sp:  # rolled-back savepoint
                cr.execute("SELECT 1")
                sp.rollback()
            self.assertIs(cr.now(), t1)

    def test_now_equals_transaction_timestamp(self):
        """now() equals transaction_timestamp() at UTC (transaction start), not
        the per-statement clock_timestamp().
        """
        with registry().cursor() as cr:
            t = cr.now()
            cr.execute("SELECT transaction_timestamp() AT TIME ZONE 'UTC'")
            self.assertEqual(t, cr.fetchone()[0])


class TestCursorBulkMethods(BaseCase):
    """Test execute_values, executemany, and pipeline."""

    def test_execute_values_basic(self):
        """execute_values builds multi-row VALUES queries."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_ev (a int, b text)")
            cr.execute_values(
                "INSERT INTO _test_ev (a, b) VALUES %s",
                [(1, "x"), (2, "y"), (3, "z")],
            )
            cr.execute("SELECT a, b FROM _test_ev ORDER BY a")
            self.assertEqual(cr.fetchall(), [(1, "x"), (2, "y"), (3, "z")])

    def test_execute_values_with_fetch(self):
        """execute_values with fetch=True returns RETURNING results."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_evf (id serial, val int)")
            results = cr.execute_values(
                "INSERT INTO _test_evf (val) VALUES %s RETURNING id, val",
                [(10,), (20,)],
                fetch=True,
            )
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0][1], 10)
            self.assertEqual(results[1][1], 20)

    def test_execute_values_empty(self):
        """execute_values with empty argslist is a no-op."""
        with registry().cursor() as cr:
            result = cr.execute_values("INSERT INTO nonexistent VALUES %s", [])
            self.assertIsNone(result)
            result = cr.execute_values(
                "INSERT INTO nonexistent VALUES %s", [], fetch=True
            )
            self.assertEqual(result, [])

    def test_execute_values_custom_template(self):
        """execute_values accepts a custom row template."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_evt (a int, b int)")
            cr.execute_values(
                "INSERT INTO _test_evt (a, b) VALUES %s",
                [(1, 10), (2, 20)],
                template="(%s, %s)",
            )
            cr.execute("SELECT a, b FROM _test_evt ORDER BY a")
            self.assertEqual(cr.fetchall(), [(1, 10), (2, 20)])

    def test_execute_values_paging(self):
        """execute_values respects page_size for batching large inserts."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_evp (val int)")
            data = [(i,) for i in range(10)]
            cr.execute_values(
                "INSERT INTO _test_evp (val) VALUES %s",
                data,
                page_size=3,
            )
            cr.execute("SELECT count(*) FROM _test_evp")
            self.assertEqual(cr.fetchone()[0], 10)

    def test_execute_values_pipeline_error_is_logged(self):
        """A pipelined (multi-batch, non-fetch) execute_values failure surfaces
        at pipeline sync on context exit, bypassing execute()'s _log_sql_error.
        It must still be logged on ``odoo.db.cursor``, not swallowed.
        """
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_evpl (n int)")
            cr.commit()
            # > default page_size (100) and not fetch -> the pipelined path.
            rows = [(i,) for i in range(150)]
            rows[75] = ("not-an-int",)  # aborts the INSERT at sync
            with (
                self.assertLogs("odoo.db.cursor", level="WARNING") as cm,
                self.assertRaises(psycopg.Error),
            ):
                cr.execute_values("INSERT INTO _test_evpl (n) VALUES %s", rows)
            cr.rollback()
        self.assertTrue(
            any("_test_evpl" in line for line in cm.output),
            f"pipelined execute_values error was not logged: {cm.output}",
        )

    def test_executemany_basic(self):
        """executemany inserts multiple rows via pipeline."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_em (a int, b text)")
            cr.executemany(
                "INSERT INTO _test_em (a, b) VALUES (%s, %s)",
                [(1, "x"), (2, "y"), (3, "z")],
            )
            cr.execute("SELECT a, b FROM _test_em ORDER BY a")
            self.assertEqual(cr.fetchall(), [(1, "x"), (2, "y"), (3, "z")])

    def test_executemany_returning(self):
        """executemany with returning=True collects RETURNING result sets."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_emr (id serial, val int)")
            cr.executemany(
                "INSERT INTO _test_emr (val) VALUES (%s) RETURNING id",
                [(10,), (20,), (30,)],
                returning=True,
            )
            # Results span multiple result sets — collect via nextset() loop
            ids = list(cr.fetchall())
            while cr.nextset():
                ids.extend(cr.fetchall())
            self.assertEqual(len(ids), 3)

    def test_executemany_empty(self):
        """executemany with empty params_seq is a no-op."""
        with registry().cursor() as cr:
            cr.executemany("INSERT INTO nonexistent VALUES (%s)", [])

    def test_pipeline_mode(self):
        """pipeline batches multiple queries in a single round-trip."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_pipe (val int)")
            with cr.pipeline():
                for i in range(5):
                    cr.execute("INSERT INTO _test_pipe (val) VALUES (%s)", [i])
            cr.execute("SELECT count(*) FROM _test_pipe")
            self.assertEqual(cr.fetchone()[0], 5)

    def test_pipeline_nesting(self):
        """Nested pipeline contexts reuse the active pipeline (no-op)."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_nest (val int)")
            with cr.pipeline():
                cr.execute("INSERT INTO _test_nest (val) VALUES (%s)", [1])
                with cr.pipeline():
                    cr.execute("INSERT INTO _test_nest (val) VALUES (%s)", [2])
                    cr.execute("INSERT INTO _test_nest (val) VALUES (%s)", [3])
                # Still in outer pipeline after inner exits
                cr.execute("INSERT INTO _test_nest (val) VALUES (%s)", [4])
            cr.execute("SELECT count(*) FROM _test_nest")
            self.assertEqual(cr.fetchone()[0], 4)

    def test_pipeline_fire_and_forget_updates(self):
        """Pipeline batches fire-and-forget UPDATEs without fetching results."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_upd (id int, val int)")
            cr.execute("INSERT INTO _test_upd VALUES (1, 10), (2, 20), (3, 30)")
            with cr.pipeline():
                cr.execute("UPDATE _test_upd SET val = val + 100 WHERE id = %s", [1])
                cr.execute("UPDATE _test_upd SET val = val + 200 WHERE id = %s", [2])
                cr.execute("UPDATE _test_upd SET val = val + 300 WHERE id = %s", [3])
            cr.execute("SELECT val FROM _test_upd ORDER BY id")
            self.assertEqual(cr.fetchall(), [(110,), (220,), (330,)])


def _merge(cr, table, columns, rows, on_columns, *, returning="NEW.id"):
    """Atomic upsert via MERGE (PG15+, RETURNING since PG17).

    Standalone test helper, kept out of the production Cursor API.
    """
    if not rows:
        return []

    comma = SQL(", ").join
    col_ids = [SQL.identifier(c) for c in columns]
    s_cols = [SQL("s.%s", SQL.identifier(c)) for c in columns]
    on_pred = SQL(" AND ").join(
        SQL("t.%s = s.%s", SQL.identifier(c), SQL.identifier(c)) for c in on_columns
    )
    update_cols = [c for c in columns if c not in on_columns]
    assignments = comma(
        SQL("%s = s.%s", SQL.identifier(c), SQL.identifier(c)) for c in update_cols
    )

    query = SQL(
        """
        MERGE INTO %(table)s t
        USING (VALUES %(values)s) AS s(%(cols)s)
        ON %(on_pred)s
        WHEN MATCHED THEN
            UPDATE SET %(assignments)s
        WHEN NOT MATCHED THEN
            INSERT (%(cols)s) VALUES (%(s_cols)s)
        RETURNING %(returning)s
        """,
        table=SQL.identifier(table),
        values=comma(rows),
        cols=comma(col_ids),
        on_pred=on_pred,
        assignments=assignments,
        s_cols=comma(s_cols),
        returning=SQL(returning),
    )
    cr.execute(query)
    return cr.fetchall()


class TestMerge(BaseCase):
    """Test MERGE (atomic upsert) protocol path."""

    def test_merge_insert(self):
        """merge() inserts new rows when no match exists."""
        with registry().cursor() as cr:
            cr.execute(
                "CREATE TEMP TABLE _test_mg_ins (id serial PRIMARY KEY, key text UNIQUE, val text)"
            )
            result = _merge(
                cr,
                "_test_mg_ins",
                ["key", "val"],
                [("a", "v1"), ("b", "v2")],
                on_columns=["key"],
            )
            self.assertEqual(len(result), 2)
            cr.execute("SELECT key, val FROM _test_mg_ins ORDER BY key")
            self.assertEqual(cr.fetchall(), [("a", "v1"), ("b", "v2")])

    def test_merge_update(self):
        """merge() updates existing rows when match exists."""
        with registry().cursor() as cr:
            cr.execute(
                "CREATE TEMP TABLE _test_mg_upd (id serial PRIMARY KEY, key text UNIQUE, val text)"
            )
            cr.execute("INSERT INTO _test_mg_upd (key, val) VALUES ('a', 'old')")
            _merge(
                cr,
                "_test_mg_upd",
                ["key", "val"],
                [("a", "new")],
                on_columns=["key"],
            )
            cr.execute("SELECT val FROM _test_mg_upd WHERE key = 'a'")
            self.assertEqual(cr.fetchone()[0], "new")

    def test_merge_mixed(self):
        """merge() handles a mix of inserts and updates."""
        with registry().cursor() as cr:
            cr.execute(
                "CREATE TEMP TABLE _test_mg_mix (id serial PRIMARY KEY, key text UNIQUE, val int)"
            )
            cr.execute("INSERT INTO _test_mg_mix (key, val) VALUES ('existing', 10)")
            result = _merge(
                cr,
                "_test_mg_mix",
                ["key", "val"],
                [("existing", 20), ("new_key", 30)],
                on_columns=["key"],
            )
            self.assertEqual(len(result), 2)
            cr.execute("SELECT key, val FROM _test_mg_mix ORDER BY key")
            self.assertEqual(cr.fetchall(), [("existing", 20), ("new_key", 30)])

    def test_merge_returning(self):
        """merge() respects custom RETURNING clause."""
        with registry().cursor() as cr:
            cr.execute(
                "CREATE TEMP TABLE _test_mg_ret (id serial PRIMARY KEY, key text UNIQUE, val text)"
            )
            cr.execute("INSERT INTO _test_mg_ret (key, val) VALUES ('a', 'old')")
            result = _merge(
                cr,
                "_test_mg_ret",
                ["key", "val"],
                [("a", "new"), ("b", "fresh")],
                on_columns=["key"],
                returning="merge_action(), OLD.val, NEW.val",
            )
            # First row: UPDATE with old/new values
            self.assertEqual(result[0][0], "UPDATE")
            self.assertEqual(result[0][1], "old")
            self.assertEqual(result[0][2], "new")
            # Second row: INSERT with NULL old value
            self.assertEqual(result[1][0], "INSERT")
            self.assertIsNone(result[1][1])
            self.assertEqual(result[1][2], "fresh")

    def test_merge_empty_rows(self):
        """merge() returns empty list for empty input."""
        with registry().cursor() as cr:
            cr.execute(
                "CREATE TEMP TABLE _test_mg_empty (id serial PRIMARY KEY, key text UNIQUE, val text)"
            )
            result = _merge(
                cr, "_test_mg_empty", ["key", "val"], [], on_columns=["key"]
            )
            self.assertEqual(result, [])


class TestCopyFrom(BaseCase):
    """Test COPY protocol path (copy_from)."""

    def test_copy_from_basic(self):
        """copy_from inserts rows via PostgreSQL COPY protocol."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_cp (a int, b text)")
            result = cr.copy_from("_test_cp", ["a", "b"], [(1, "x"), (2, "y")])
            self.assertIsNone(result)
            cr.execute("SELECT a, b FROM _test_cp ORDER BY a")
            self.assertEqual(cr.fetchall(), [(1, "x"), (2, "y")])

    def test_copy_from_returning_ids(self):
        """copy_from with returning_ids pre-generates IDs from the sequence."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_cpid (id serial PRIMARY KEY, val text)")
            try:
                ids = cr.copy_from(
                    "_test_cpid",
                    ["val"],
                    [("a",), ("b",), ("c",)],
                    returning_ids=True,
                )
                self.assertEqual(len(ids), 3)
                # Verify the IDs match what was actually inserted
                cr.execute("SELECT id, val FROM _test_cpid ORDER BY id")
                rows = cr.fetchall()
                self.assertEqual(len(rows), 3)
                for expected_id, (row_id, _) in zip(ids, rows, strict=False):
                    self.assertEqual(expected_id, row_id)
            finally:
                # Clean up sequence cache to avoid cross-test contamination
                _id_sequence_cache.pop((cr.dbname, "_test_cpid"), None)

    def test_resolve_id_sequence_shared_fallback_is_schema_aware(self):
        """A non-owned (shared) id DEFAULT sequence resolves via the pg_depend
        fallback, anchored on ``%s::regclass`` (search_path).  Regression: the
        fallback used to join pg_class on bare relname, matching same-named
        tables in every schema and returning an arbitrary one via LIMIT 1.
        """
        cr = registry().cursor()
        try:
            for s, seq in (("_cpseq_s1", "seq_a"), ("_cpseq_s2", "seq_b")):
                cr.execute(f"CREATE SCHEMA {s}")
                cr.execute(f"CREATE SEQUENCE {s}.{seq}")
                cr.execute(
                    f"CREATE TABLE {s}.foo "
                    f"(id int DEFAULT nextval('{s}.{seq}'), val text)"
                )
            cr.execute("SET LOCAL search_path = _cpseq_s2, public")
            # Not column-owned: pg_get_serial_sequence is NULL, forcing the
            # pg_depend fallback (the _inherits shared-sequence case).
            cr.execute("SELECT pg_get_serial_sequence('foo', 'id')")
            self.assertIsNone(cr.fetchone()[0])
            try:
                seq_name = cr._resolve_id_sequence("foo")
                self.assertEqual(seq_name, "seq_b")
            finally:
                _id_sequence_cache.pop((cr.dbname, "foo"), None)
        finally:
            cr.rollback()  # discard schemas/tables (transactional DDL)
            cr.close()

    def test_copy_from_empty_returning(self):
        """copy_from with empty rows and returning_ids returns empty list."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_cpe (id serial PRIMARY KEY, val text)")
            ids = cr.copy_from("_test_cpe", ["val"], [], returning_ids=True)
            self.assertEqual(ids, [])

    def test_copy_from_returning_ids_generator_input(self):
        """returning_ids must handle an unsized (generator) ``rows`` input.

        copy_from materializes ``rows`` only when it lacks ``__len__``; a
        generator exercises that branch and must still pre-count, pre-generate
        ids, and insert every row with its id prepended.
        """
        with registry().cursor() as cr:
            cr.execute(
                "CREATE TEMP TABLE _test_cpgen (id serial PRIMARY KEY, val text)"
            )
            try:
                rows = ((f"v{i}",) for i in range(5))  # generator: no __len__
                ids = cr.copy_from("_test_cpgen", ["val"], rows, returning_ids=True)
                self.assertEqual(len(ids), 5)
                cr.execute("SELECT id, val FROM _test_cpgen ORDER BY id")
                inserted = cr.fetchall()
                self.assertEqual([r[0] for r in inserted], ids)
                self.assertEqual([r[1] for r in inserted], [f"v{i}" for i in range(5)])
            finally:
                _id_sequence_cache.pop((cr.dbname, "_test_cpgen"), None)

    def test_copy_from_empty_nonreturning_short_circuits(self):
        """An empty (sized) non-returning copy_from returns None without issuing
        a COPY (no wasted round-trip); validations still run first."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_cpens (a int, b text)")
            before = cr.sql_log_count
            self.assertIsNone(cr.copy_from("_test_cpens", ["a", "b"], []))
            self.assertEqual(
                cr.sql_log_count, before, "empty copy_from must not hit the server"
            )
            # an empty generator (unsized) still works — falls through to a no-op
            self.assertIsNone(cr.copy_from("_test_cpens", ["a", "b"], (x for x in ())))
            # validation still fires even for empty input
            with self.assertRaises(ValueError):
                cr.copy_from("_test_cpens", [], [])

    def test_copy_from_empty_columns_raises(self):
        """An empty column list builds ``COPY t () FROM STDIN``; reject it at the
        boundary with a clear message, not a cryptic PG syntax error."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_cpec (a int)")
            with self.assertRaises(ValueError):
                cr.copy_from("_test_cpec", [], [(1,)])

    def test_copy_from_null_values(self):
        """copy_from handles None → NULL conversion."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_cpn (a int, b text)")
            cr.copy_from("_test_cpn", ["a", "b"], [(1, None), (None, "y")])
            cr.execute("SELECT a, b FROM _test_cpn ORDER BY COALESCE(a, 0)")
            rows = cr.fetchall()
            self.assertEqual(rows[0], (None, "y"))
            self.assertEqual(rows[1], (1, None))

    def test_copy_from_large_batch(self):
        """COPY handles batches larger than typical INSERT thresholds."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_cplg (val int)")
            rows = [(i,) for i in range(500)]
            cr.copy_from("_test_cplg", ["val"], rows)
            cr.execute("SELECT count(*) FROM _test_cplg")
            self.assertEqual(cr.fetchone()[0], 500)

    def test_copy_from_json_values(self):
        """COPY adapts JSON (dict/list) types via psycopg3's Transformer."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_cpj (data jsonb)")
            cr.copy_from(
                "_test_cpj",
                ["data"],
                [(psycopg.types.json.Json({"key": "value"}),)],
            )
            cr.execute("SELECT data->>'key' FROM _test_cpj")
            self.assertEqual(cr.fetchone()[0], "value")


class TestDDLFormatting(BaseCase):
    """Test that DDL statements use client-side formatting automatically."""

    def test_ddl_client_side_formatting(self):
        """DDL statements use client-side formatting automatically.

        PostgreSQL's extended query protocol rejects $N parameters in DDL
        structural positions, so execute() detects DDL and inlines params
        client-side via psycopg.sql.quote().
        """
        with registry().cursor() as cr:
            # Without client-side formatting, psycopg3 would send $1 which
            # PostgreSQL rejects for DEFAULT expressions.
            cr.execute("CREATE TEMP TABLE _test_ddl (val int DEFAULT %s)", (0,))
            cr.execute(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = '_test_ddl' AND column_name = 'val'"
            )
            default = cr.fetchone()[0]
            self.assertEqual(default, "0")

    def test_ddl_comment(self):
        """COMMENT ON is DDL and uses client-side formatting."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_ddl2 (val int)")
            cr.execute("COMMENT ON TABLE _test_ddl2 IS %s", ("test comment",))
            cr.execute(
                "SELECT obj_description(c.oid) FROM pg_class c WHERE c.relname = '_test_ddl2'"
            )
            self.assertEqual(cr.fetchone()[0], "test comment")


class TestComposableQueries(BaseCase):
    """psycopg ``sql.Composable`` queries are first-class citizens.

    ``sql.SQL(...).format(sql.Identifier(...))`` is psycopg's sanctioned way to
    build dynamic statements with safely quoted identifiers; SQL-view report
    models (e.g. fleet's odometer report) use it for ``CREATE VIEW``.  The
    cursor resolves them to their final text via ``as_string`` so DDL detection
    works on real SQL (regression: ``qs[:64]`` crashed on a ``Composed``).
    """

    def test_composed_ddl_create_view(self):
        """The fleet pattern: CREATE VIEW composed with sql.Identifier."""
        with registry().cursor() as cr:
            cr.execute(
                psycopg.sql.SQL("CREATE TEMP VIEW {} as ({})").format(
                    psycopg.sql.Identifier("_test_composed_view"),
                    psycopg.sql.SQL("SELECT 42 AS answer"),
                )
            )
            cr.execute("SELECT answer FROM _test_composed_view")
            self.assertEqual(cr.fetchone()[0], 42)
            cr.execute(
                psycopg.sql.SQL("DROP VIEW {}").format(
                    psycopg.sql.Identifier("_test_composed_view")
                )
            )

    def test_composed_ddl_with_params(self):
        """Composed DDL still gets client-side param inlining."""
        with registry().cursor() as cr:
            cr.execute(
                psycopg.sql.SQL("CREATE TEMP TABLE {} (val int DEFAULT %s)").format(
                    psycopg.sql.Identifier("_test_composed_ddl")
                ),
                (7,),
            )
            cr.execute(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = '_test_composed_ddl' AND column_name = 'val'"
            )
            self.assertEqual(cr.fetchone()[0], "7")

    def test_composed_non_ddl(self):
        """Composed DML/SELECT resolves and binds params server-side."""
        with registry().cursor() as cr:
            cr.execute(
                psycopg.sql.SQL("SELECT {} FROM res_users WHERE id = %s").format(
                    psycopg.sql.Identifier("login")
                ),
                (1,),
            )
            self.assertTrue(cr.fetchone())

    def test_composed_executemany(self):
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_composed_many (val int)")
            cr.executemany(
                psycopg.sql.SQL("INSERT INTO {} (val) VALUES (%s)").format(
                    psycopg.sql.Identifier("_test_composed_many")
                ),
                [(1,), (2,), (3,)],
            )
            cr.execute("SELECT sum(val) FROM _test_composed_many")
            self.assertEqual(cr.fetchone()[0], 6)


class TestCategorizeQuery(BaseCase):
    """Test query categorization utility (from/into/other)."""

    def test_select_from(self):
        qtype, table = categorize_query("SELECT * FROM res_users")
        self.assertEqual(qtype, "from")
        self.assertEqual(table, "res_users")

    def test_insert_into(self):
        qtype, table = categorize_query("INSERT INTO res_users (name) VALUES ('x')")
        self.assertEqual(qtype, "into")
        self.assertEqual(table, "res_users")

    def test_insert_select_prioritizes_into(self):
        """INSERT INTO ... SELECT FROM ... prioritizes 'into' over 'from'."""
        qtype, table = categorize_query("INSERT INTO t1 SELECT * FROM t2")
        self.assertEqual(qtype, "into")
        self.assertEqual(table, "t1")

    def test_update_is_a_write(self):
        """UPDATE lands in 'into' (write) with its table, not invisible 'other'."""
        qtype, table = categorize_query("UPDATE res_users SET name='x'")
        self.assertEqual(qtype, "into")
        self.assertEqual(table, "res_users")

    def test_update_schema_qualified(self):
        qtype, table = categorize_query('UPDATE "public"."res_users" SET name=1')
        self.assertEqual(qtype, "into")
        self.assertEqual(table, "res_users")

    def test_update_with_from_subquery(self):
        """The UPDATE target wins over a FROM inside the statement."""
        qtype, table = categorize_query(
            "UPDATE t1 SET a = s.a FROM (SELECT * FROM t2) s WHERE s.id = t1.id"
        )
        self.assertEqual(qtype, "into")
        self.assertEqual(table, "t1")

    def test_delete_is_a_write(self):
        """DELETE FROM lands in 'into' (write), not 'from' (read)."""
        qtype, table = categorize_query("DELETE FROM res_users WHERE id = 1")
        self.assertEqual(qtype, "into")
        self.assertEqual(table, "res_users")

    def test_select_for_update_stays_a_read(self):
        """The FOR UPDATE row-locking clause must not misfile a SELECT as a write."""
        qtype, table = categorize_query(
            "SELECT id FROM res_users WHERE id = 1 FOR UPDATE NOWAIT"
        )
        self.assertEqual(qtype, "from")
        self.assertEqual(table, "res_users")

    def test_other(self):
        qtype, table = categorize_query("COMMIT")
        self.assertEqual(qtype, "other")
        self.assertIsNone(table)

    def test_quoted_table_name(self):
        qtype, table = categorize_query('SELECT * FROM "my_table" WHERE id = 1')
        self.assertEqual(qtype, "from")
        self.assertEqual(table, "my_table")

    def test_case_insensitive(self):
        qtype, table = categorize_query("select * from RES_USERS")
        self.assertEqual(qtype, "from")
        self.assertEqual(table, "RES_USERS")

    def test_multiline_query(self):
        qtype, table = categorize_query("SELECT id\n  FROM res_partner\n WHERE active")
        self.assertEqual(qtype, "from")
        self.assertEqual(table, "res_partner")


class TestConnectionInfoFor(BaseCase):
    """Test connection_info_for URI/name parsing."""

    def test_postgresql_uri(self):
        db, info = connection_info_for("postgresql://user:pass@localhost:5432/mydb")
        self.assertEqual(db, "mydb")
        self.assertIn("dsn", info)
        self.assertEqual(info["dsn"], "postgresql://user:pass@localhost:5432/mydb")
        # Health params are always included
        self.assertIn("connect_timeout", info)
        self.assertIn("keepalives", info)

    def test_postgres_uri_scheme(self):
        """Both 'postgresql://' and 'postgres://' schemes are accepted."""
        db, info = connection_info_for("postgres://localhost/testdb")
        self.assertEqual(db, "testdb")
        self.assertIn("dsn", info)

    def test_uri_no_path_uses_username(self):
        """When URI path is just '/', fall back to username as db name."""
        db, _ = connection_info_for("postgresql://admin@localhost/")
        self.assertEqual(db, "admin")

    def test_uri_no_path_no_user_uses_hostname(self):
        """When URI has no path and no username, use hostname.

        The fallback emits a RuntimeWarning by design (asserted in
        ``TestURIMalformedWarning``); suppress it here to keep the log clean.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            db, _ = connection_info_for("postgresql://localhost/")
        self.assertEqual(db, "localhost")

    def test_plain_dbname(self):
        db, info = connection_info_for("mydb")
        self.assertEqual(db, "mydb")
        self.assertEqual(info["dbname"], "mydb")
        self.assertNotIn("dsn", info)
        # Health params are always included
        self.assertIn("connect_timeout", info)

    def test_application_name_included(self):
        _, info = connection_info_for("mydb")
        self.assertIn("application_name", info)


class TestConnectionDsnRedaction(BaseCase):
    """Connection.dsn must never expose the password.

    For URI/conninfo connections the secret lives *inside* the ``dsn`` string,
    so a bare ``pop("password")`` left it to leak into the DEBUG log from
    ``Connection.cursor()``.  Both URI and keyword forms are covered here.
    """

    # A canary value we assert never appears in the redacted output.
    CANARY = "s3cr3tPW"

    def _dsn_for(self, target):
        pool = ConnectionPool(maxconn=1)  # constructs without connecting
        dbname, info = connection_info_for(target)
        return Connection(pool, dbname, info).dsn

    def test_uri_password_not_leaked(self):
        dsn = self._dsn_for(f"postgresql://u:{self.CANARY}@dbhost:5432/mydb")
        self.assertNotIn(self.CANARY, repr(dsn))
        # The raw URI is expanded into components: the opaque "dsn" key is gone
        # but routing info remains.
        self.assertNotIn("dsn", dsn)
        self.assertEqual(dsn.get("host"), "dbhost")
        self.assertEqual(dsn.get("user"), "u")
        self.assertEqual(dsn.get("dbname"), "mydb")

    def test_keyword_password_not_leaked(self):
        pool = ConnectionPool(maxconn=1)
        _, info = connection_info_for("mydb")
        info["password"] = self.CANARY
        dsn = Connection(pool, "mydb", info).dsn
        self.assertNotIn(self.CANARY, repr(dsn))
        self.assertEqual(dsn.get("dbname"), "mydb")

    def test_uri_without_password_does_not_crash(self):
        dsn = self._dsn_for("postgresql://u@dbhost/mydb")
        self.assertNotIn("dsn", dsn)
        self.assertEqual(dsn.get("host"), "dbhost")


class TestPoolBasics(BaseCase):
    """Test pool representation, properties, and statistics."""

    def test_readwrite_pool_repr(self):
        pool = ConnectionPool(maxconn=4)
        r = repr(pool)
        self.assertIn("read/write", r)
        self.assertIn("limit=4", r)
        pool.close_all()

    def test_readonly_pool_repr(self):
        pool = ConnectionPool(maxconn=4, readonly=True)
        self.assertIn("read-only", repr(pool))
        self.assertTrue(pool.readonly)
        pool.close_all()

    def test_pool_stats_empty(self):
        pool = ConnectionPool(maxconn=4)
        stats = pool.get_stats()
        self.assertEqual(stats, {})
        pool.close_all()

    def test_tuning_params_stored_and_derived(self):
        """Pool lifecycle tuning is per-instance (production passes it from
        tools.config); the give_back reap throttle derives from the TTL."""
        pool = ConnectionPool(
            maxconn=4,
            borrow_timeout=12.5,
            max_lifetime=1234,
            max_idle=77,
            reap_idle_ttl=88.0,
        )
        self.assertEqual(pool._borrow_timeout, 12.5)
        self.assertEqual(pool._max_lifetime, 1234)
        self.assertEqual(pool._max_idle, 77)
        self.assertEqual(pool._reap_idle_ttl, 88.0)
        # quarter of the TTL, floored at 1s
        self.assertEqual(pool._reap_check_interval, 22.0)
        pool.close_all()

    def test_tuning_defaults_match_constants(self):
        """Direct construction (no config) falls back to the _DEFAULT_* values."""
        pool = ConnectionPool(maxconn=1)
        self.assertEqual(pool._borrow_timeout, pool_module._DEFAULT_BORROW_TIMEOUT)
        self.assertEqual(pool._max_lifetime, pool_module._DEFAULT_MAX_LIFETIME)
        self.assertEqual(pool._max_idle, pool_module._DEFAULT_MAX_IDLE)
        self.assertEqual(pool._reap_idle_ttl, pool_module._DEFAULT_REAP_IDLE_TTL)
        pool.close_all()

    def test_reap_check_interval_disabled_when_ttl_zero(self):
        pool = ConnectionPool(maxconn=1, reap_idle_ttl=0.0)
        self.assertEqual(pool._reap_check_interval, 0.0)
        pool.close_all()

    def test_checked_out_formula(self):
        """_checked_out is the single source of truth for size - available,
        tolerating missing stat keys (treated as 0)."""

        class _StubPool:
            def __init__(self, stats):
                self._stats = stats

            def get_stats(self):
                return self._stats

        self.assertEqual(
            ConnectionPool._checked_out(
                _StubPool({"pool_size": 5, "pool_available": 2})
            ),
            3,
        )
        self.assertEqual(
            ConnectionPool._checked_out(
                _StubPool({"pool_size": 4, "pool_available": 4})
            ),
            0,
        )
        self.assertEqual(ConnectionPool._checked_out(_StubPool({})), 0)

    def test_repr_does_not_deadlock_under_lock(self):
        """__repr__ runs from logging inside _debug() while self._lock is held
        (see _get_or_create_pool), so it must NOT re-acquire that non-reentrant
        lock.  Render the repr on another thread under the held lock; a lock
        attempt would block it and time out the join.
        """
        pool = ConnectionPool(maxconn=2)
        out = []
        with pool._lock:
            t = threading.Thread(target=lambda: out.append(repr(pool)))
            t.start()
            t.join(timeout=5)
            alive = t.is_alive()
        self.assertFalse(alive, "repr(pool) deadlocked while _lock was held")
        self.assertTrue(out and out[0].startswith("ConnectionPool("))
        pool.close_all()

    def test_repr_survives_concurrent_pool_churn(self):
        """__repr__ must materialize the pool list atomically before calling
        get_stats(): the old lazy generator raised "dictionary changed size
        during iteration" when a pool was added/evicted mid-render."""

        class _FakePool:
            closed = False

            def get_stats(self):
                return {"pool_size": 1, "pool_available": 1}

            def close(self):
                pass

        pool = ConnectionPool(maxconn=4)
        stop = threading.Event()
        errors = []

        def churn():
            i = 0
            while not stop.is_set():
                pool._pools[frozenset([("database", f"d{i & 7}"), ("n", str(i))])] = (
                    _FakePool()
                )
                keys = list(pool._pools)  # atomic snapshot; pop tolerates a race
                if len(keys) > 6:
                    pool._pools.pop(keys[0], None)
                i += 1

        def render():
            while not stop.is_set():
                try:
                    repr(pool)
                except RuntimeError as e:  # "dictionary changed size ..."
                    errors.append(str(e))
                    return

        ts = [threading.Thread(target=churn), threading.Thread(target=render)]
        for t in ts:
            t.start()
        time.sleep(1.0)
        stop.set()
        for t in ts:
            t.join()
        pool._pools.clear()
        pool.close_all()
        self.assertEqual(errors, [], "repr(pool) raced with pool churn")

    def test_pool_maxconn_rejects_non_positive(self):
        """Pool maxconn <= 0 raises instead of silently coercing to 1.

        The old max(maxconn, 1) clamp turned a misconfigured db_maxconn=0 into a
        single-slot pool that wedged the server under load.  Fail fast instead.
        """
        with self.assertRaises(ValueError):
            ConnectionPool(maxconn=0)
        with self.assertRaises(ValueError):
            ConnectionPool(maxconn=-1)


class TestSuppressKnownPoolWarnings(BaseCase):
    """Test the logging filter for known psycopg_pool warnings."""

    def test_suppresses_discard_message(self):
        f = _SuppressKnownPoolWarnings()
        record = logging.LogRecord(
            "test",
            logging.WARNING,
            "",
            0,
            "discarding closed connection in pool",
            (),
            None,
        )
        self.assertFalse(f.filter(record))

    def test_suppresses_database_does_not_exist(self):
        f = _SuppressKnownPoolWarnings()
        record = logging.LogRecord(
            "test",
            logging.WARNING,
            "",
            0,
            'error connecting: FATAL: database "test" does not exist',
            (),
            None,
        )
        self.assertFalse(f.filter(record))

    def test_passes_other_messages(self):
        f = _SuppressKnownPoolWarnings()
        record = logging.LogRecord(
            "test",
            logging.WARNING,
            "",
            0,
            "connection timeout error",
            (),
            None,
        )
        self.assertTrue(f.filter(record))


class TestPoolSemaphoreAccounting(BaseCase):
    """The pool-scoped semaphore is accounted via the Odoo-owned ``_odoo_pool``
    marker (set in ``borrow``, cleared in ``give_back``), independent of
    psycopg_pool's private ``conn._pool``.  Guards against permit leaks and
    over-release.  Needs a live database (``borrow`` opens a real connection).
    """

    def _info(self):
        return connection_info_for(common.get_db_name())[1]

    def test_borrow_tags_and_give_back_releases(self):
        pool = ConnectionPool(maxconn=2)
        self.addCleanup(pool.close_all)
        conn = pool.borrow(self._info())
        self.assertEqual(pool._pool_sem._value, 1)
        self.assertIsNotNone(getattr(conn, "_odoo_pool", None))
        self.assertIn(conn._odoo_pool, pool._pools.values())
        pool.give_back(conn)
        self.assertEqual(pool._pool_sem._value, 2)
        # give_back CLAIMS the marker with an atomic dict.pop — after return
        # the attribute is absent, not set to None (double-release safety).
        self.assertNotIn("_odoo_pool", conn.__dict__)

    def test_double_give_back_does_not_over_release(self):
        pool = ConnectionPool(maxconn=2)
        self.addCleanup(pool.close_all)
        conn = pool.borrow(self._info())
        pool.give_back(conn)
        pool.give_back(conn)  # marker already cleared -> safe no-op, no ValueError
        self.assertEqual(pool._pool_sem._value, 2)

    def test_non_borrowed_connection_does_not_release(self):
        pool = ConnectionPool(maxconn=2)
        self.addCleanup(pool.close_all)
        before = pool._pool_sem._value
        # A connection NOT created through borrow() carries no marker, so
        # give_back must close it without touching the semaphore.
        raw = psycopg.connect(**{k: v for k, v in self._info().items() if k != "dsn"})
        try:
            pool.give_back(raw)
            self.assertEqual(pool._pool_sem._value, before)
            self.assertTrue(raw.closed)
        finally:
            if not raw.closed:
                raw.close()

    def test_dead_connection_still_releases_slot(self):
        pool = ConnectionPool(maxconn=2)
        self.addCleanup(pool.close_all)
        conn = pool.borrow(self._info())
        conn.close()  # external death; marker is a plain attribute, survives
        self.assertIsNotNone(getattr(conn, "_odoo_pool", None))
        pool.give_back(conn)
        self.assertEqual(pool._pool_sem._value, 2)


class TestConnectionStateReset(BaseCase):
    """``_reset_connection`` must not leak a borrower's session-scoped state to
    the *next* borrower of the same physical connection — a multi-tenant
    isolation hazard.  Needs a live database (opens a real connection).
    """

    def _raw_conn(self):
        info = connection_info_for(common.get_db_name())[1]
        conn = psycopg.connect(
            **{k: v for k, v in info.items() if k != "dsn"}, autocommit=True
        )
        self.addCleanup(conn.close)
        return conn

    @staticmethod
    def _dirty(conn):
        conn.execute("SET application_name = 'tenant_leak_probe'")
        conn.execute("SET search_path = 'leak_schema, public'")
        conn.execute("CREATE TEMP TABLE _leak_probe (x int)")
        conn.execute("LISTEN leak_channel")
        conn.execute("SELECT pg_advisory_lock(987654321)")

    def _assert_clean(self, conn):
        get = lambda q: conn.execute(q).fetchone()[0]  # noqa: E731
        self.assertNotEqual(get("SHOW application_name"), "tenant_leak_probe")
        self.assertNotIn("leak_schema", get("SHOW search_path"))
        self.assertFalse(get("SELECT to_regclass('pg_temp._leak_probe') IS NOT NULL"))
        self.assertEqual(get("SELECT count(*) FROM pg_listening_channels()"), 0)
        # Scope to THIS backend: advisory locks are cluster-wide (not
        # database-scoped) in PostgreSQL, so a bare count would also see locks
        # held by any other Odoo process on the same cluster (a concurrent test
        # run against another database) and spuriously fail. The other checks in
        # this method are already connection-scoped.
        self.assertEqual(
            get(
                "SELECT count(*) FROM pg_locks "
                "WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
            ),
            0,
        )

    def test_reset_sql_resets_role(self):
        # RESET ALL does NOT clear SET ROLE / SET SESSION AUTHORIZATION; only
        # RESET SESSION AUTHORIZATION does, so it must be in the cheap reset.
        self.assertIn("RESET SESSION AUTHORIZATION", _RESET_SESSION_STATE_SQL)

    @staticmethod
    def _override_discard(value):
        from odoo.tools import config

        return patch.object(
            config, "options", config.options.new_child({"db_discard_on_return": value})
        )

    def test_default_mode_closes_leaks(self):
        conn = self._raw_conn()
        self._dirty(conn)
        with self._override_discard(False):
            _reset_connection(conn)
        conn.autocommit = True
        self._assert_clean(conn)

    def test_discard_mode_closes_leaks(self):
        conn = self._raw_conn()
        self._dirty(conn)
        with self._override_discard(True):
            _reset_connection(conn)
        conn.autocommit = True
        self._assert_clean(conn)

    def test_no_prepared_statement_crash_across_returns(self):
        # The reset is a multi-statement command (unpreparable) and DISCARD ALL
        # deallocates server-side prepared statements; reusing an auto-prepared
        # shape across many returns must not raise (prepare=False + cache clear).
        for discard in (False, True):
            conn = self._raw_conn()
            conn.prepare_threshold = 2
            with self._override_discard(discard):
                for _ in range(6):
                    conn.execute("SELECT 1 WHERE %s::int = 1", (1,))
                    self._dirty(conn)
                    _reset_connection(conn)
                    conn.autocommit = True
            self._assert_clean(conn)


class TestIdlePoolReaper(BaseCase):
    """Idle per-DSN pools are reaped when a new pool is created, so a process
    serving many databases over time does not accumulate pool objects (and
    their threads).  A pool with a checked-out connection is never reaped, and
    ``borrow`` rebuilds transparently when its pool is closed underneath it (the
    reaper / ``close_database`` race).  Needs a live database.

    Distinct ``application_name`` values key distinct pools to the SAME test
    database, giving several per-DSN pools without several databases.
    """

    def _info(self, app):
        return {**connection_info_for(common.get_db_name())[1], "application_name": app}

    @staticmethod
    def _dbset(pool):
        return {dict(k).get("application_name") for k in pool._pools}

    def _force_idle(self, pool, app):
        # Make every pool except *app*'s look long-untouched without sleeping:
        # the reaper checks ``monotonic() - _odoo_last_borrow`` against the TTL.
        for k, psy in pool._pools.items():
            if dict(k).get("application_name") != app:
                psy._odoo_last_borrow = 0.0

    def test_idle_pool_reaped_on_new_pool_creation(self):
        pool = ConnectionPool(maxconn=4, reap_idle_ttl=300.0)
        self.addCleanup(pool.close_all)
        for app in ("reap_a", "reap_b", "reap_c"):
            pool.give_back(pool.borrow(self._info(app)))
        self.assertEqual(len(pool._pools), 3)
        self._force_idle(pool, app="none")  # all three look idle
        # Creating a new pool (cold path) triggers the reaper.
        pool.give_back(pool.borrow(self._info("reap_d")))
        self.assertEqual(
            self._dbset(pool),
            {"reap_d"},
            "only the freshly created pool should survive",
        )

    def test_checked_out_connection_is_not_reaped(self):
        pool = ConnectionPool(maxconn=4, reap_idle_ttl=300.0)
        self.addCleanup(pool.close_all)
        held = pool.borrow(self._info("held"))  # kept checked out
        self.addCleanup(lambda: pool.give_back(held))
        pool.give_back(pool.borrow(self._info("idle")))
        self._force_idle(pool, app="none")  # both look idle by the clock
        pool.give_back(pool.borrow(self._info("trigger")))
        survivors = self._dbset(pool)
        self.assertIn("held", survivors, "pool with a held connection must stay")
        self.assertNotIn("idle", survivors, "idle pool with nothing held is reaped")

    def test_give_back_refreshes_activity_stamp(self):
        # Returning a connection is activity: give_back must re-stamp the pool,
        # or a connection held past the TTL and then returned leaves its pool
        # eligible for reaping.  Regression for stamping on borrow only.
        pool = ConnectionPool(maxconn=4, reap_idle_ttl=300.0)
        self.addCleanup(pool.close_all)
        conn = pool.borrow(self._info("returned"))
        (key,) = list(pool._pools)
        pool._pools[key]._odoo_last_borrow = 0.0  # simulate a long (>TTL) hold
        pool.give_back(conn)
        self.assertGreater(
            pool._pools[key]._odoo_last_borrow,
            0.0,
            "give_back must refresh the pool's activity stamp",
        )

    def test_long_held_then_returned_pool_survives_sweep(self):
        # End-to-end: borrow, simulate a >TTL hold, return, then trigger the
        # cold-path reaper by creating another pool.  The just-returned pool is
        # active (give_back re-stamped it) and must survive.
        pool = ConnectionPool(maxconn=4, reap_idle_ttl=300.0)
        self.addCleanup(pool.close_all)
        conn = pool.borrow(self._info("returned"))
        (key,) = list(pool._pools)
        pool._pools[key]._odoo_last_borrow = 0.0  # long hold
        pool.give_back(conn)  # re-stamps the pool fresh
        pool.give_back(pool.borrow(self._info("trigger")))  # cold-path sweep
        self.assertIn(
            "returned",
            self._dbset(pool),
            "a pool that just returned a connection is active, not idle",
        )

    def test_reaper_disabled_keeps_all_pools(self):
        pool = ConnectionPool(maxconn=4, reap_idle_ttl=0.0)
        self.addCleanup(pool.close_all)
        for app in ("a", "b", "c"):
            pool.give_back(pool.borrow(self._info(app)))
        self._force_idle(pool, app="none")
        pool.give_back(pool.borrow(self._info("d")))
        self.assertEqual(len(pool._pools), 4, "reaper disabled -> nothing reaped")

    def test_borrow_rebuilds_when_pool_closed_underneath_it(self):
        # Disable the reaper and close the pool by hand to simulate the race:
        # borrow() must discover PoolClosed, rebuild, and return a live conn.
        pool = ConnectionPool(maxconn=4, reap_idle_ttl=0.0)
        self.addCleanup(pool.close_all)
        pool.give_back(pool.borrow(self._info("rebuild")))
        (key,) = list(pool._pools)
        victim = pool._pools[key]
        victim.close()
        conn = pool.borrow(self._info("rebuild"))  # must not raise
        try:
            self.assertFalse(conn.closed)
            self.assertIsNot(
                pool._pools[key], victim, "a fresh pool replaced the closed one"
            )
            self.assertEqual(pool._pool_sem._value, 3, "exactly one permit held")
        finally:
            pool.give_back(conn)
        self.assertEqual(pool._pool_sem._value, 4, "permit released, no leak")


class TestCursorDelReclaimsConnection(BaseCase):
    """An unclosed cursor reclaimed by the GC must (1) warn so the leak is
    visible and (2) still return its connection and pool-semaphore permit.  A
    forgotten ``close()`` would otherwise exhaust the pool over the process
    life.  ``__del__`` is the untested safety net.  Needs a live database.
    """

    def _info(self):
        return connection_info_for(common.get_db_name())[1]

    def test_del_warns_and_reclaims_permit(self):
        import gc

        pool = ConnectionPool(maxconn=2)
        self.addCleanup(pool.close_all)
        dbname = common.get_db_name()
        info = self._info()

        def leak():
            # A cursor built as Connection.cursor() does, then dropped WITHOUT
            # close(): its sole reference vanishes on return so CPython finalizes
            # it here (gc.collect() below is belt-and-braces).
            cr = Cursor(pool, dbname, info)
            cr.execute("SELECT 1")
            self.assertEqual(cr.fetchscalar(), 1)
            self.assertEqual(pool._pool_sem._value, 1, "permit not consumed on open")

        with self.assertLogs("odoo.db.cursor", level="WARNING") as cm:
            leak()
            gc.collect()

        self.assertTrue(
            any("not closed explicitly" in m for m in cm.output),
            "Cursor.__del__ did not warn about the unclosed cursor",
        )
        self.assertEqual(
            pool._pool_sem._value,
            2,
            "Cursor.__del__ leaked the pool semaphore permit",
        )


class TestPoolTimeoutCleanup(BaseCase):
    """Test that dead pools are cleaned up on PoolTimeout."""

    def test_pool_removed_on_timeout(self):
        """When getconn() raises PoolTimeout, the pool must be removed from
        _pools so subsequent borrows create a fresh pool instead of hitting
        the same dead one (e.g. after a database drop).
        """
        pool = ConnectionPool(maxconn=4)
        info = connection_info_for("nonexistent_db_test")[1]
        key = _normalize_dsn_key(info)

        # Pre-create a mock psycopg_pool that raises PoolTimeout and holds
        # no live connections (the dropped-database signature).
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.getconn.side_effect = PoolTimeout("connection timeout")
        mock_pool.get_stats.return_value = {"pool_size": 0}
        pool._pools[key] = mock_pool

        with self.assertRaises(PoolError):
            pool.borrow(info)

        self.assertNotIn(key, pool._pools)
        mock_pool.close.assert_called_once()

    def test_pool_kept_on_timeout_with_live_connections(self):
        """PoolTimeout while the pool still holds live connections means the
        server is reachable but slow — tearing the pool down would close
        healthy idle connections and amplify the slowdown into a reconnect
        storm.  The pool must be kept.
        """
        pool = ConnectionPool(maxconn=4)
        info = connection_info_for("nonexistent_db_test")[1]
        key = _normalize_dsn_key(info)

        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.getconn.side_effect = PoolTimeout("connection timeout")
        mock_pool.get_stats.return_value = {"pool_size": 3}
        pool._pools[key] = mock_pool

        with self.assertRaises(PoolError):
            pool.borrow(info)

        self.assertIn(key, pool._pools)
        mock_pool.close.assert_not_called()

    def test_pool_not_removed_on_other_errors(self):
        """Non-timeout psycopg errors should NOT remove the pool —
        the error might be transient (e.g. brief network hiccup).
        """
        pool = ConnectionPool(maxconn=4)
        info = connection_info_for("nonexistent_db_test")[1]
        key = _normalize_dsn_key(info)

        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.getconn.side_effect = psycopg.OperationalError("connection refused")
        pool._pools[key] = mock_pool

        with self.assertRaises(psycopg.OperationalError):
            pool.borrow(info)

        self.assertIn(key, pool._pools)
        mock_pool.close.assert_not_called()


class TestDroppedDBRecovery(BaseCase):
    """Test that check_signaling() cleans up stale registries when the
    database is unreachable (e.g. dropped by another worker).

    Uses a mock cursor to avoid the 30s psycopg_pool retry timeout —
    the pool-level behavior is separately tested by TestPoolTimeoutCleanup.
    """

    DB_NAME = "odoo_test_pool_recovery"

    def test_check_signaling_cleans_up_after_db_drop(self):
        """check_signaling() must delete the stale registry when cursor
        creation fails with OperationalError, and re-raise the error.

        Without this fix, the stale registry stays in the LRU and every
        subsequent request creates a new pool that blocks for 30s on
        PoolTimeout — repeated hangs until the process is restarted.
        """
        # Minimal registry shell in the LRU; the cursor is mocked to fail.
        reg = object.__new__(Registry)
        reg.db_name = self.DB_NAME
        reg._db_readonly = None
        Registry.registries[self.DB_NAME] = reg
        self.addCleanup(Registry.delete, self.DB_NAME)

        # Simulate dropped DB: cursor() raises OperationalError
        with patch.object(
            type(reg),
            "cursor",
            side_effect=psycopg.OperationalError(
                f'database "{self.DB_NAME}" does not exist'
            ),
        ):
            with self.assertRaises(psycopg.OperationalError):
                reg.check_signaling()

        self.assertNotIn(self.DB_NAME, Registry.registries)

    def test_check_signaling_keeps_registry_on_pool_error(self):
        """check_signaling() propagates PoolError without deleting the registry."""
        reg = object.__new__(Registry)
        reg.db_name = self.DB_NAME
        reg._db_readonly = None
        Registry.registries[self.DB_NAME] = reg
        self.addCleanup(Registry.delete, self.DB_NAME)

        # PoolError means pool capacity exhaustion (all connections in use), NOT
        # a dead database, so check_signaling() must propagate it as-is.
        with patch.object(
            type(reg),
            "cursor",
            side_effect=PoolError("couldn't get a connection after 30.00 sec"),
        ):
            with self.assertRaises(PoolError):
                reg.check_signaling()

        # deleting the registry here would turn a transient load spike into a
        # self-inflicted outage (full module reload under the global lock);
        # dead-DB cleanup is the OperationalError path's job.
        self.assertIn(self.DB_NAME, Registry.registries)

    def test_check_signaling_keeps_registry_when_caller_provides_cursor(self):
        """When the caller provides a cursor (cr is not None) and it fails
        mid-query, the registry should NOT be deleted — the failure has a
        different cause (e.g. dead connection mid-query, not a dropped DB).
        """
        reg = object.__new__(Registry)
        reg.db_name = self.DB_NAME
        reg._db_readonly = None
        reg.registry_sequence = -1
        Registry.registries[self.DB_NAME] = reg
        self.addCleanup(Registry.delete, self.DB_NAME)

        # Simulate a cursor that fails during get_sequences()
        mock_cr = MagicMock()
        mock_cr.__enter__ = MagicMock(return_value=mock_cr)
        mock_cr.__exit__ = MagicMock(return_value=False)
        mock_cr.execute.side_effect = psycopg.OperationalError("connection closed")

        with self.assertRaises(psycopg.OperationalError):
            reg.check_signaling(cr=mock_cr)

        # Registry should still be in the LRU — caller-provided cursor
        # failure is not necessarily a dropped DB.
        self.assertIn(self.DB_NAME, Registry.registries)


class TestPoolDrainConcurrency(BaseCase):
    """drain() must not race concurrent pool creation / close_all.

    drain_all() fires on every `update_module` while the RPC layer keeps
    calling db_connect() — both paths touch ConnectionPool._pools.
    Before the fix, the unlocked `for key, pool in self._pools.items()`
    loop could raise ``RuntimeError: dictionary changed size during
    iteration``.
    """

    def test_drain_does_not_race_churn(self):
        pool = ConnectionPool(maxconn=4)
        # Seed with throwaway entries — the real per-DB pools never get
        # borrowed because we exercise only the bookkeeping dict, not the
        # underlying psycopg_pool.
        for i in range(500):
            pool._pools[f"fake-{i}"] = MagicMock(closed=False)

        errors = []
        stop = threading.Event()

        def drain_loop():
            while not stop.is_set():
                try:
                    pool.drain()
                except RuntimeError as e:
                    errors.append(str(e))
                    return

        def churn_loop():
            while not stop.is_set():
                with pool._lock:
                    snapshot = list(pool._pools.values())
                    pool._pools.clear()
                    for i, v in enumerate(snapshot):
                        pool._pools[f"fake-{i}"] = v

        threads = [
            threading.Thread(target=drain_loop),
            threading.Thread(target=churn_loop),
        ]
        for t in threads:
            t.start()
        time.sleep(1.0)
        stop.set()
        for t in threads:
            t.join()

        pool.close_all()
        self.assertEqual(
            errors, [], "drain() raced the pools dict — fix in pool.py regressed"
        )


class TestExecuteValuesTripwire(BaseCase):
    """execute_values requires exactly one '%s' marker — anything else
    silently mis-expands with ``query.replace('%s', ..., 1)``.
    """

    def test_rejects_zero_markers(self):
        with registry().cursor() as cr:
            with self.assertRaises(ValueError):
                cr.execute_values("INSERT INTO t DEFAULT VALUES", [(1,)])

    def test_rejects_multiple_markers(self):
        with registry().cursor() as cr:
            with self.assertRaises(ValueError):
                cr.execute_values(
                    "UPDATE t SET col=%s FROM (VALUES %s) s WHERE id=s.x",
                    [(1, 2), (3, 4)],
                )

    def test_accepts_single_marker(self):
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_evt_tw (v int)")
            cr.execute_values(
                "INSERT INTO _test_evt_tw (v) VALUES %s",
                [(1,), (2,)],
            )
            cr.execute("SELECT count(*) FROM _test_evt_tw")
            self.assertEqual(cr.fetchone()[0], 2)


class TestExecutemanyTripwire(BaseCase):
    """executemany cannot use SQL objects with embedded params — the per-row
    params come from params_seq. Silently dropping SQL.params would mask
    caller bugs.
    """

    def test_rejects_sql_with_embedded_params(self):
        """Reject SQL("tpl %s", value) — executemany can't merge per-row
        params_seq with the SQL's own embedded params."""
        with registry().cursor() as cr:
            with self.assertRaises(ValueError):
                cr.executemany(
                    SQL("INSERT INTO t(a,b) VALUES (%s, %s)", 1, 2),
                    [(3, 4)],
                )

    def test_plain_str_query_still_works(self):
        """The normal path (plain str with %s placeholders) is unaffected."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_em_tw (a int, b int)")
            cr.executemany(
                "INSERT INTO _test_em_tw(a, b) VALUES (%s, %s)",
                [(1, 2), (3, 4)],
            )
            cr.execute("SELECT count(*) FROM _test_em_tw")
            self.assertEqual(cr.fetchone()[0], 2)


class TestFlushingSavepointDepthOnFailure(BaseCase):
    """_FlushingSavepoint must not leak the cursor-level ``_savepoint_depth`` if
    the SAVEPOINT SQL raises — otherwise the next commit/rollback hits the
    ``_savepoint_depth`` guard and wedges the transaction.
    """

    def test_savepoint_depth_unchanged_on_sql_failure(self):
        cr = MagicMock()
        cr._savepoint_depth = 0  # real int: behaves like the live cursor's guard
        cr.transaction = None
        cr.flush = MagicMock()
        cr.execute = MagicMock(
            side_effect=psycopg.OperationalError("simulated broken connection")
        )

        with self.assertRaises(psycopg.OperationalError):
            _FlushingSavepoint(cr)

        # Depth must remain at 0 — no leaked counter for a savepoint that
        # never actually made it to the server.
        self.assertEqual(
            cr._savepoint_depth, 0, "savepoint_depth leaked after SAVEPOINT SQL failure"
        )

    def test_savepoint_depth_balanced_when_release_fails(self):
        """The mirror of the above: a RELEASE (or ROLLBACK TO) failure on close
        must still balance the +1 back down.  If the decrement is skipped, the
        leaked counter wedges the next commit/rollback on the same
        ``_savepoint_depth`` guard."""

        def execute(sql, *args, **kwargs):
            # SAVEPOINT succeeds (depth -> 1); only RELEASE blows up on close.
            if "RELEASE" in str(sql):
                raise psycopg.OperationalError("simulated RELEASE failure")

        cr = MagicMock()
        cr._savepoint_depth = 0
        cr.transaction = None
        cr.flush = MagicMock()
        cr.execute = MagicMock(side_effect=execute)

        sp = _FlushingSavepoint(cr)
        self.assertEqual(cr._savepoint_depth, 1)
        with self.assertRaises(psycopg.OperationalError):
            sp.close(rollback=False)
        self.assertEqual(
            cr._savepoint_depth, 0, "savepoint_depth leaked after RELEASE failure"
        )


class TestURIMalformedWarning(BaseCase):
    """URIs without a path AND without a username fall back to using the
    hostname as the database name — almost always a misconfiguration.
    The fallback stays for backward compatibility but must warn."""

    def test_hostname_fallback_emits_warning(self):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            db, _info = connection_info_for("postgresql://localhost/")
        self.assertEqual(db, "localhost")
        matched = [w for w in captured if issubclass(w.category, RuntimeWarning)]
        self.assertTrue(
            matched, "Expected a RuntimeWarning for URI without path/username"
        )

    def test_well_formed_uri_no_warning(self):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            db, _info = connection_info_for("postgresql://localhost/mydb")
        self.assertEqual(db, "mydb")
        matched = [w for w in captured if issubclass(w.category, RuntimeWarning)]
        self.assertFalse(
            matched, "Well-formed URI should not trigger the hostname-fallback warning"
        )


class TestClosedCursorAttributeAccess(BaseCase):
    """Accessing ANY attribute on a closed cursor should raise InterfaceError
    cleanly, without emitting a misleading DeprecationWarning about the
    attribute name en route."""

    def test_unknown_attr_on_closed_cursor_raises_cleanly(self):
        cr = registry().cursor()
        cr.close()
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            with self.assertRaises(psycopg.InterfaceError):
                cr.some_nonexistent_attr  # noqa: B018
        dep_warnings = [
            w for w in captured if issubclass(w.category, DeprecationWarning)
        ]
        self.assertEqual(
            dep_warnings,
            [],
            "Closed-cursor attribute access should not emit DeprecationWarning",
        )


class TestCursorCloseWithDeadConnection(BaseCase):
    """Regression: cr.close() must release the pool slot and clean up _obj
    even when the underlying connection died externally (network failure,
    peer drop).  The old close() guarded on the ``closed`` property which
    flips True as soon as _cnx.closed becomes True, silently skipping
    _close() and leaking both the psycopg Cursor object and the
    semaphore slot.
    """

    def test_close_releases_slot_when_cnx_dies_externally(self):
        cr = registry().cursor()
        pool = cr._Cursor__pool
        sem_before = pool._pool_sem._value
        # Simulate the connection dying underneath us.
        cr.connection.close()
        self.assertTrue(cr.closed, "closed property should reflect dead _cnx")
        self.assertFalse(cr._closed, "internal _closed flag must not be set yet")
        cr.close()
        self.assertGreater(
            pool._pool_sem._value,
            sem_before,
            "close() must release the semaphore slot even when _cnx is dead",
        )
        self.assertNotIn(
            "_obj",
            cr.__dict__,
            "close() must delete _obj even when _cnx is dead",
        )


class TestCopyFromIncompatibleOptions(BaseCase):
    """copy_from rejects option combinations that would silently produce
    wrong results:

    - binary=True with on_error='ignore' silently drops on_error because
      binary COPY has no ON_ERROR clause.
    - returning_ids=True with on_error='ignore' returns pre-allocated
      sequence IDs that do NOT correspond to inserted rows.
    """

    def test_binary_with_on_error_raises(self):
        with registry().cursor() as cr:
            with self.assertRaises(ValueError):
                cr.copy_from("t", ["c"], [(1,)], binary=True, on_error="ignore")

    def test_returning_ids_with_ignore_raises(self):
        with registry().cursor() as cr:
            with self.assertRaises(ValueError):
                cr.copy_from("t", ["c"], [(1,)], returning_ids=True, on_error="ignore")


class TestDictFetchoneNoAssert(BaseCase):
    """dictfetchone must not rely on ``assert desc`` — ``python -O``
    strips asserts and a missing description would then blow up with
    AttributeError on None rather than a diagnosable error.
    """

    def test_uses_explicit_raise_not_assert(self):
        src = inspect.getsource(Cursor.dictfetchone)
        self.assertNotIn(
            "assert desc",
            src,
            "dictfetchone must not use `assert` (stripped by python -O)",
        )


class TestReadonlyPropertyCached(BaseCase):
    """Cursor.readonly must return a cached value bound to the cursor, not
    read through ``_cnx.read_only`` post-close — after _close() returns
    the connection to the pool, another cursor may own it and flip the
    state.
    """

    def test_readonly_stable_across_close(self):
        for ro in (False, True):
            with self.subTest(readonly=ro):
                cr = registry().cursor(readonly=ro)
                before = cr.readonly
                cr.close()
                after = cr.readonly
                self.assertEqual(
                    before, after, "readonly must not change after close()"
                )
                self.assertEqual(bool(ro), before)


class TestGetStatsLocked(BaseCase):
    """get_stats must snapshot _pools under the lock to avoid
    ``RuntimeError: dictionary changed size during iteration`` when a
    concurrent borrow() creates a new per-DB pool mid-iteration.
    """

    def test_get_stats_safe_under_churn(self):
        src = inspect.getsource(ConnectionPool.get_stats)
        self.assertIn(
            "with self._lock",
            src,
            "get_stats must snapshot _pools under the lock",
        )


class TestSuppressKnownPoolWarningsNarrow(BaseCase):
    """The warning filter must only swallow ``database "..." does not
    exist`` FATAL lines — role / tablespace / schema errors must reach
    the log so operators can diagnose misconfiguration.
    """

    def test_does_not_swallow_role_does_not_exist(self):
        f = _SuppressKnownPoolWarnings()
        rec = logging.LogRecord(
            "test",
            logging.WARNING,
            "",
            0,
            'FATAL: role "nobody" does not exist',
            (),
            None,
        )
        self.assertTrue(
            f.filter(rec),
            "role-does-not-exist must NOT be suppressed (misconfiguration signal)",
        )


class TestPGAppNameWarningOnce(BaseCase):
    """The ODOO_PGAPPNAME deprecation warning must fire at most once per
    process — it was previously emitted on every connection_info_for call,
    producing thousands of duplicates per request.
    """

    def test_deprecation_warning_is_one_shot(self):
        os.environ["ODOO_PGAPPNAME"] = "test"
        saved = _db_utils._ODOO_PGAPPNAME_WARNED
        _db_utils._ODOO_PGAPPNAME_WARNED = False
        try:
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always")
                for _ in range(5):
                    connection_info_for("mydb")
            pg = [w for w in captured if "ODOO_PGAPPNAME" in str(w.message)]
            self.assertEqual(
                len(pg),
                1,
                f"expected exactly one warning across 5 calls, got {len(pg)}",
            )
        finally:
            del os.environ["ODOO_PGAPPNAME"]
            _db_utils._ODOO_PGAPPNAME_WARNED = saved


class TestExecuteValuesPageSize(BaseCase):
    """execute_values must reject non-positive page_size at the API
    boundary.  The old loop used ``range(0, len(argslist), page_size)``,
    which:

    - Crashes with a cryptic ``ValueError: range() arg 3 must not be
      zero`` for page_size=0.
    - Produces an empty range for page_size<0, silently dropping every
      row the caller asked to insert (confirmed data-loss path).
    """

    def test_zero_page_size_raises(self):
        with registry().cursor() as cr:
            with self.assertRaises(ValueError):
                cr.execute_values("INSERT INTO t VALUES %s", [(1,)], page_size=0)

    def test_negative_page_size_raises(self):
        with registry().cursor() as cr:
            with self.assertRaises(ValueError):
                cr.execute_values("INSERT INTO t VALUES %s", [(1,)], page_size=-1)

    def test_marker_count_validated_even_when_empty(self):
        """A query without exactly one '%s' VALUES marker is malformed
        regardless of batch size.  The validation must run BEFORE the
        empty-argslist short-circuit, so a caller's empty-data test catches
        the bug instead of it surfacing only once real rows arrive."""
        with registry().cursor() as cr:
            # Two markers, empty argslist: must still raise (previously this
            # returned silently because the empty-check short-circuited first).
            with self.assertRaises(ValueError):
                cr.execute_values("INSERT INTO t VALUES %s, %s", [])
            # Zero markers, empty argslist: same.
            with self.assertRaises(ValueError):
                cr.execute_values("INSERT INTO t DEFAULT VALUES", [])
            # Well-formed query with empty argslist still returns cleanly.
            self.assertIsNone(cr.execute_values("INSERT INTO t VALUES %s", []))
            self.assertEqual(
                cr.execute_values("INSERT INTO t VALUES %s", [], fetch=True), []
            )


class TestResetConnectionRestoresPrepare(BaseCase):
    """_reset_connection must restore the prepared-statement tuning set
    by _configure_connection.  Cursor.execute() sets prepare_threshold
    to None in the DDL-fallback path; without this restore the next
    borrower of the connection inherits disabled auto-prepare for up
    to max_lifetime (3600s).
    """

    def test_reset_restores_prepare_threshold(self):
        with registry().cursor() as cr:
            cr.connection.prepare_threshold = None
            cr.connection.prepared_max = 1
            _reset_connection(cr.connection)
            self.assertEqual(cr.connection.prepare_threshold, 2)
            self.assertEqual(cr.connection.prepared_max, 500)


class TestHealthCheckGracePeriod(BaseCase):
    """The per-borrow liveness probe (``_check_connection``) is a server
    round-trip, gated on an idle grace window: a connection released within
    ``_HEALTHCHECK_GRACE_PERIOD`` skips it (provably alive then); a longer-idle
    one is probed so a backend that died while parked (restart, failover,
    ``pg_terminate_backend``) is discarded before reaching a borrower.
    ``configure``/``reset`` stamp freshness; a missing stamp fails safe to probe.
    """

    class _Bare:
        """Plain object whose missing attributes are truly absent — unlike
        MagicMock, which would synthesize a truthy ``_odoo_idle_since``."""

    def test_fresh_connection_skips_probe(self):
        conn = self._Bare()
        setattr(conn, _IDLE_SINCE_ATTR, time.monotonic())
        with patch("odoo.db.pool._PsycopgPool.check_connection") as probe:
            _check_connection(conn)
        probe.assert_not_called()

    def test_idle_connection_is_probed(self):
        conn = self._Bare()
        setattr(
            conn, _IDLE_SINCE_ATTR, time.monotonic() - _HEALTHCHECK_GRACE_PERIOD - 1
        )
        with patch("odoo.db.pool._PsycopgPool.check_connection") as probe:
            _check_connection(conn)
        probe.assert_called_once_with(conn)

    def test_unstamped_connection_fails_safe_to_probe(self):
        conn = self._Bare()  # no _odoo_idle_since at all
        with patch("odoo.db.pool._PsycopgPool.check_connection") as probe:
            _check_connection(conn)
        probe.assert_called_once_with(conn)

    def test_configure_and_reset_stamp_freshness(self):
        conn = MagicMock()
        _configure_connection(conn)
        first = getattr(conn, _IDLE_SINCE_ATTR)
        self.assertIsInstance(first, float)
        time.sleep(0.002)
        _reset_connection(conn)
        self.assertGreater(
            getattr(conn, _IDLE_SINCE_ATTR),
            first,
            "reset() must re-stamp the freshness timestamp on return",
        )


class TestDiscardOnReturn(BaseCase):
    """The ``db_discard_on_return`` config option (env ODOO_DB_DISCARD_ON_RETURN)
    opts into a hard session reset (DISCARD ALL) on connection return, for
    multi-tenant hosts needing isolation between borrows.  Off by default — the
    return path runs the cheap single-round-trip session reset
    (``_RESET_SESSION_STATE_SQL``), closing cross-borrower leaks while keeping
    the auto-prepared-statement/plan caches warm.  Read from config on each
    return (no import-time freeze).
    """

    def _set_discard(self, value):
        from odoo.tools import config

        old = config["db_discard_on_return"]
        config["db_discard_on_return"] = value
        self.addCleanup(config.__setitem__, "db_discard_on_return", old)

    def test_default_runs_cheap_session_reset(self):
        conn = MagicMock()
        seen = []
        # Capture autocommit state AT THE MOMENT execute() runs: DISCARD TEMP
        # (part of the cheap reset) cannot run inside a transaction block, so
        # the reset must be issued in autocommit mode.  prepare=False: psycopg
        # cannot PREPARE a multi-statement string, so auto-prepare is bypassed.
        conn.execute.side_effect = lambda sql, **kw: seen.append(
            (sql, conn.autocommit, kw.get("prepare"))
        )
        self._set_discard(False)
        _reset_connection(conn)
        self.assertEqual(
            seen,
            [(_RESET_SESSION_STATE_SQL, True, False)],
            "default return path must run the cheap session reset "
            "(and never DISCARD ALL)",
        )
        # session settings still restored
        self.assertEqual(conn.prepare_threshold, 2)
        self.assertEqual(conn.prepared_max, 500)
        self.assertFalse(conn.autocommit)

    def test_opt_in_runs_discard_all_in_autocommit(self):
        conn = MagicMock()
        seen = []
        # Capture autocommit state AT THE MOMENT execute() runs: DISCARD ALL
        # cannot run inside a transaction block, so it must be issued in
        # autocommit mode.
        conn.execute.side_effect = lambda sql, **kw: seen.append(
            (sql, conn.autocommit, kw.get("prepare"))
        )
        self._set_discard(True)
        _reset_connection(conn)
        self.assertEqual(seen, [("DISCARD ALL", True, False)])
        # DISCARD ALL deallocated every server-side prepared statement; the
        # client-side prepare cache must be dropped too or the next borrower
        # would EXECUTE a name the server no longer knows.
        conn._prepared.clear.assert_called_once_with()
        # autocommit returned to False and prepare tuning re-applied afterwards
        self.assertFalse(conn.autocommit)
        self.assertEqual(conn.prepare_threshold, 2)
        self.assertEqual(conn.prepared_max, 500)


class TestURIHealthParamsMerge(BaseCase):
    """_HEALTH_PARAMS defaults must NOT override user-specified values
    already present in the URI query string.  Operators who set
    ``?connect_timeout=60`` expect their value to survive.
    """

    def test_uri_connect_timeout_preserved(self):
        uri = "postgresql://u:p@h:5432/db?connect_timeout=60&keepalives_idle=300"
        _, info = connection_info_for(uri)
        # The user's values are in the DSN string and MUST NOT be shadowed
        # by a kwarg at our default.  Presence of a kwarg would override
        # the DSN value per psycopg's precedence rules.
        self.assertNotIn("connect_timeout", info)
        self.assertNotIn("keepalives_idle", info)
        # Other health params we did not specify are still injected.
        self.assertEqual(info.get("keepalives"), "1")


class TestExpDropClosesPoolTwice(BaseCase):
    """``exp_drop`` must call ``odoo.db.close_db`` twice — before and after
    ``DROP DATABASE`` — because cron/HTTP threads can re-create a pool for the
    target database in the window between the first close and the DROP.  Without
    the second close, those pools later reconnect to a dropped database.  This
    upstream invariant had no regression coverage.
    """

    def test_close_db_called_before_and_after_drop(self):
        events: list[tuple[str, str]] = []
        fake_db = "_t_exp_drop_fake"

        def fake_close_db(name: str) -> None:
            events.append(("close_db", name))

        fake_cursor = MagicMock()

        def cursor_execute(query, *_args, **_kwargs):
            if "DROP DATABASE" in str(query):
                events.append(("drop_database", fake_db))

        fake_cursor.execute.side_effect = cursor_execute

        # Shape the context-manager protocol for `with closing(db.cursor())`.
        fake_conn = MagicMock()
        fake_conn.cursor.return_value = fake_cursor
        # `closing(cursor)` calls cursor.close() on exit; the MagicMock
        # already satisfies that.

        # No need to patch config.filestore: exp_drop guards the rmtree with
        # ``if Path(fs).exists()`` and fake_db was never a real database, so that
        # branch is skipped.  database_identifier() needs a real psycopg
        # connection to quote names, so stub it with a static SQL fragment.
        with (
            patch("odoo.service.db.list_dbs", return_value=[fake_db]),
            patch("odoo.modules.registry.Registry.delete"),
            patch("odoo.service.db._drop_conn"),
            patch("odoo.db.close_db", side_effect=fake_close_db),
            patch("odoo.db.db_connect", return_value=fake_conn),
            patch(
                "odoo.service.db.database_identifier",
                return_value=SQL(f'"{fake_db}"'),
            ),
        ):
            result = exp_drop(fake_db)

        self.assertTrue(result, f"exp_drop should return True; events={events}")

        close_indices = [i for i, (k, _) in enumerate(events) if k == "close_db"]
        drop_indices = [i for i, (k, _) in enumerate(events) if k == "drop_database"]

        self.assertEqual(
            len(close_indices),
            2,
            f"close_db must be called exactly twice; events={events}",
        )
        self.assertEqual(
            len(drop_indices),
            1,
            f"DROP DATABASE must be executed exactly once; events={events}",
        )
        self.assertLess(
            close_indices[0],
            drop_indices[0],
            "first close_db must precede DROP DATABASE",
        )
        self.assertGreater(
            close_indices[1],
            drop_indices[0],
            "second close_db must follow DROP DATABASE",
        )


class TestSchemaCachesPerDatabase(BaseCase):
    """Schema caches must be keyed by database and cleared per-database.

    One process serves several databases whose same-named tables may have
    diverging schemas; a cross-DB cache hit poisons binary COPY (wrong
    set_types) persistently — reproduced 2026-06-11 as ProtocolViolation
    "insufficient data left in message" on the second database.
    """

    def test_column_type_cache_key_includes_dbname(self):
        with registry().cursor() as cr:
            key = (cr.dbname, "ir_model_data", ("id", "name"))
            _column_type_cache.pop(key, None)
            try:
                types = cr._get_column_types("ir_model_data", ["id", "name"])
                self.assertEqual(len(types), 2)
                self.assertIn(key, _column_type_cache)
            finally:
                _column_type_cache.pop(key, None)

    def test_id_sequence_cache_key_includes_dbname(self):
        # Permanent table: its name resolves identically for every connection
        # to this database, so caching the sequence is correct and the key must
        # carry the dbname.  (Temp tables are deliberately NOT cached — see
        # test_temp_relation_schema_not_cached.)
        with registry().cursor() as cr:
            cr.execute("CREATE TABLE _test_seqkey (id serial PRIMARY KEY, v text)")
            try:
                cr.copy_from("_test_seqkey", ["v"], [("x",)], returning_ids=True)
                self.assertIn((cr.dbname, "_test_seqkey"), _id_sequence_cache)
            finally:
                _id_sequence_cache.pop((cr.dbname, "_test_seqkey"), None)
                cr.execute("DROP TABLE IF EXISTS _test_seqkey")

    def test_temp_relation_schema_not_cached(self):
        """Temp-table schema lookups must NOT enter the process-global caches.

        Cache keys are name-based ((db, table[, cols])), but a temp table's name
        lives in a session-local pg_temp_* schema; caching one session's temp
        types/sequence would hand them to another session's different table.
        Reproduced as ``'float' object cannot be interpreted as an integer``
        (binary COPY) and ``UndefinedTable`` (returning_ids).
        """
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_tmp_nc (id serial PRIMARY KEY, v int)")
            # returning_ids → id-sequence cache; binary → column-type cache.
            cr.copy_from("_test_tmp_nc", ["v"], [(1,)], returning_ids=True)
            cr.copy_from("_test_tmp_nc", ["v"], [(2,)], binary=True)
            self.assertNotIn((cr.dbname, "_test_tmp_nc"), _id_sequence_cache)
            self.assertEqual(
                [k for k in _column_type_cache if k[1] == "_test_tmp_nc"], []
            )

    def test_clear_schema_caches_per_db(self):
        from odoo.db.cursor import _clear_schema_caches

        _column_type_cache[("dbx", "t", ("a",))] = ["int4"]
        _column_type_cache[("dby", "t", ("a",))] = ["int8"]
        _id_sequence_cache[("dbx", "t")] = "t_id_seq"
        try:
            _clear_schema_caches("dbx")
            self.assertNotIn(("dbx", "t", ("a",)), _column_type_cache)
            self.assertNotIn(("dbx", "t"), _id_sequence_cache)
            self.assertIn(("dby", "t", ("a",)), _column_type_cache)
        finally:
            _clear_schema_caches("dbx")
            _clear_schema_caches("dby")

    def test_close_db_clears_schema_caches(self):
        import odoo.db as db_mod

        fake = "_claude_fake_db_"
        _column_type_cache[(fake, "t", ("a",))] = ["int4"]
        _id_sequence_cache[(fake, "t")] = "t_id_seq"
        # No pools exist for this name — exercises the cache side only.
        db_mod.close_db(fake)
        self.assertNotIn((fake, "t", ("a",)), _column_type_cache)
        self.assertNotIn((fake, "t"), _id_sequence_cache)

    def test_get_column_types_missing_column(self):
        """Unknown column raises a descriptive ValueError, not a KeyError."""
        with registry().cursor() as cr:
            with self.assertRaises(ValueError):
                cr._get_column_types("ir_model_data", ["id", "no_such_column"])

    def test_ddl_invalidates_column_type_cache(self):
        """A local schema change must drop the binary-COPY column-type cache.

        copy_from(binary) caches a table's column types; ALTER COLUMN ... TYPE
        makes that stale but self-heals only on the next drain_*/close_db
        (cross-worker signalling never fires for the worker that ran the DDL).
        Without local invalidation a binary copy_from between ALTER and drain
        feeds set_types() stale types and corrupts the COPY.  Cursor.execute
        clears the schema_cache on schema-changing DDL.
        """
        # A *permanent* table is required: temp tables are deliberately not
        # cached.  CREATE/ALTER are transactional in PostgreSQL, so the whole
        # thing is rolled back at the end — no committed table leaks into the DB.
        tbl = "_test_ddl_inval"
        cr = db_connect(common.get_db_name()).cursor()
        try:
            cr.execute(f"CREATE TABLE {tbl} (x int)")
            cr.copy_from(tbl, ["x"], [(1,)], binary=True)
            self.assertEqual(
                schema_cache.get_column_types(cr.dbname, tbl, ["x"]),
                ["int4"],
                "binary copy_from should have cached the column type",
            )
            cr.execute(f"ALTER TABLE {tbl} ALTER COLUMN x TYPE text")
            self.assertIsNone(
                schema_cache.get_column_types(cr.dbname, tbl, ["x"]),
                "ALTER must invalidate the cached column type",
            )
            # The re-lookup must now reflect the new type, so binary COPY of a
            # text value succeeds instead of raising on stale int4 types.
            cr.copy_from(tbl, ["x"], [("hello",)], binary=True)
            cr.execute(f"SELECT x FROM {tbl} ORDER BY x")
            self.assertEqual(cr.fetchall(), [("1",), ("hello",)])
        finally:
            schema_cache.clear(cr.dbname)
            cr.rollback()  # undo the CREATE TABLE — DDL is transactional
            cr.close()


class TestDrainDb(BaseCase):
    """drain_db must clear schema caches for one database only."""

    def test_drain_db_clears_caches_for_db_only(self):
        from odoo.db import drain_db

        _column_type_cache[("dbx", "t", ("a",))] = ["int4"]
        _column_type_cache[("dby", "t", ("a",))] = ["int8"]
        try:
            drain_db("dbx")
            self.assertNotIn(("dbx", "t", ("a",)), _column_type_cache)
            self.assertIn(("dby", "t", ("a",)), _column_type_cache)
        finally:
            _column_type_cache.pop(("dbx", "t", ("a",)), None)
            _column_type_cache.pop(("dby", "t", ("a",)), None)


class TestCheckSignalingDrains(BaseCase):
    """The registry-reload branch of check_signaling must drain this
    worker's pools: stale auto-prepared statements fail once per statement
    after a type-changing upgrade, and stale schema caches do NOT self-heal.
    (Source tripwire — same pattern as TestGetStatsLocked.)
    """

    def test_check_signaling_calls_drain_db(self):
        src = inspect.getsource(Registry.check_signaling)
        self.assertIn(
            "drain_db",
            src,
            "check_signaling's reload branch must drain_db(self.db_name)",
        )


class TestCopyFromOnErrorWhitelist(BaseCase):
    """on_error is interpolated into the COPY options clause — whitelist it."""

    def test_rejects_arbitrary_on_error(self):
        with registry().cursor() as cr:
            with self.assertRaises(ValueError):
                cr.copy_from("t", ["c"], [(1,)], on_error="ignore, FREEZE")

    def test_accepts_stop(self):
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_oe (v int)")
            cr.copy_from("_test_oe", ["v"], [(1,)], on_error="stop")
            cr.execute("SELECT count(*) FROM _test_oe")
            self.assertEqual(cr.fetchone()[0], 1)


class TestExecuteValuesEscapedPercent(BaseCase):
    """%% escape sequences must not be mistaken for the VALUES marker.

    Naive str.count/str.replace both match the %s inside %%s: a legitimate
    query with a LIKE 'a%%s' literal was falsely rejected (count == 2), and
    with no real marker the replace mangled the literal itself.
    """

    def test_literal_double_percent_accepted(self):
        # NB: temp table name must be unique file-wide — temp tables live
        # on the pooled SESSION and survive cursor close, so a name shared
        # with another test (here: test_execute_values_paging's _test_evp)
        # collides when both tests land on the same pooled connection.
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_evpesc (v text)")
            cr.execute_values(
                "INSERT INTO _test_evpesc (v) SELECT x FROM (VALUES %s) s(x) "
                "WHERE 'abc' NOT LIKE 'a%%s'",
                [("r1",), ("r2",)],
            )
            cr.execute("SELECT count(*) FROM _test_evpesc")
            self.assertEqual(cr.fetchone()[0], 2)

    def test_literal_only_rejected(self):
        """A query whose only %s lives inside a %% escape has no marker."""
        with registry().cursor() as cr:
            with self.assertRaises(ValueError):
                cr.execute_values("SELECT 'a%%s'", [(1,)])


class TestSavepointGuardsSurviveOptimize(BaseCase):
    """commit/rollback inside a savepoint must raise even under python -O
    (explicit RuntimeError, not assert).

    The guard reads the CURSOR-level ``cr._savepoint_depth`` (bumped by every
    savepoint, ORM-attached or bare), so it fires even on a bare
    ``registry().cursor()`` whose ``transaction`` is None — no stub transaction
    is needed.  ``savepoint(flush=False)`` keeps this off the ORM flush path so
    the test exercises the guard in isolation.
    """

    def test_commit_inside_savepoint_raises(self):
        with registry().cursor() as cr:
            self.assertIsNone(cr.transaction)
            with self.assertRaises(RuntimeError):
                with cr.savepoint(flush=False):
                    cr.commit()
            # guard fired BEFORE the SQL COMMIT: the savepoint unwound cleanly
            # and the cursor-level depth is balanced back to 0.
            self.assertEqual(cr._savepoint_depth, 0)

    def test_rollback_inside_savepoint_raises(self):
        with registry().cursor() as cr:
            self.assertIsNone(cr.transaction)
            with self.assertRaises(RuntimeError):
                with cr.savepoint(flush=False):
                    cr.rollback()
            self.assertEqual(cr._savepoint_depth, 0)


class TestFlushingSavepointLayering(BaseCase):
    """The db→ORM layering inversion: the db layer's ``_FlushingSavepoint``
    knows only ``flush()``; the ORM registers a subclass
    (``_OrmFlushingSavepoint``) that restores cache/env state on rollback.
    """

    def test_orm_subclass_is_registered(self):
        """Importing the ORM runtime wires the ORM-aware savepoint onto
        ``BaseCursor`` so ``savepoint(flush=True)`` uses it."""
        from odoo.db.cursor import BaseCursor
        from odoo.db.savepoint import _FlushingSavepoint
        from odoo.orm.runtime.savepoint import _OrmFlushingSavepoint

        self.assertIs(BaseCursor._flushing_savepoint_cls, _OrmFlushingSavepoint)
        self.assertTrue(issubclass(_OrmFlushingSavepoint, _FlushingSavepoint))

    def test_db_layer_does_not_import_orm_helpers(self):
        """The deep ORM reaches moved out of the db layer: the cache helper is
        no longer imported there, and the restore/save hooks are no-ops the ORM
        subclass overrides."""
        from odoo.db import savepoint as db_savepoint
        from odoo.db.savepoint import _FlushingSavepoint
        from odoo.orm.runtime.savepoint import _OrmFlushingSavepoint

        # reset_cached_properties is an ORM cache helper; the db module must no
        # longer import it (it lives in the ORM subclass now).
        self.assertFalse(hasattr(db_savepoint, "reset_cached_properties"))
        # The hooks are defined-but-empty at the db layer and overridden by the
        # ORM subclass — proving the restoration logic lives in the ORM layer.
        self.assertIsNot(
            _OrmFlushingSavepoint._restore_orm_state,
            _FlushingSavepoint._restore_orm_state,
        )
        self.assertIsNot(
            _OrmFlushingSavepoint._save_orm_state,
            _FlushingSavepoint._save_orm_state,
        )

    def test_savepoint_restores_orm_state_on_rollback(self):
        """``cr.savepoint()`` returns the ORM subclass and its rollback restores
        ``default_env`` and clears the transaction cache."""
        from odoo.orm.runtime.savepoint import _OrmFlushingSavepoint

        class _StubTransaction:
            def __init__(self, reg):
                self.default_env = "ENV_BEFORE"
                # A real registry: _restore_orm_state detects reloads by object
                # identity against ``type(registry).registries`` — a MagicMock
                # cannot satisfy that lookup.
                self.registry = reg
                self.envs = []
                self.cleared = 0
                self.was_reset = 0

            def flush(self):
                pass

            def clear(self):
                self.cleared += 1

            def reset(self):
                self.was_reset += 1

        reg = registry()
        with reg.cursor() as cr:
            cr.transaction = _StubTransaction(reg)
            try:
                sp = cr.savepoint()  # flush=True
                self.assertIsInstance(sp, _OrmFlushingSavepoint)
                self.assertEqual(cr._savepoint_depth, 1)
                # mutate ORM state inside the savepoint, then roll back
                cr.transaction.default_env = "ENV_DURING"
                sp.rollback()
                # live registry identity unchanged -> clear() path (not reset())
                self.assertEqual(cr.transaction.default_env, "ENV_BEFORE")
                self.assertEqual(cr.transaction.cleared, 1)
                self.assertEqual(cr.transaction.was_reset, 0)
                sp.close(rollback=True)
                self.assertEqual(cr._savepoint_depth, 0)
            finally:
                cr.transaction = None


class TestFlushNonConvergence(BaseCase):
    """flush() must raise (not warn) when precommit hooks keep generating
    work — committing would silently drop the pending hooks."""

    def test_flush_nonconvergence_raises(self):
        class _EndlessTransaction:
            """Stub whose flush() always queues another precommit hook."""

            def __init__(self, cr):
                self._cr = cr

            def flush(self):
                self._cr.precommit.add(lambda: None)

            def clear(self):
                pass

        with registry().cursor() as cr:
            orig = cr.transaction
            cr.transaction = _EndlessTransaction(cr)
            try:
                with self.assertRaises(RuntimeError):
                    cr.flush()
            finally:
                cr.transaction = orig
                cr.precommit.clear()
                cr.rollback()

    def test_flush_self_requeue_drains_in_single_run(self):
        """A precommit hook that re-queues ITSELF drains inside one
        ``Callbacks.run()`` and never reaches ``_MAX_FLUSH_PASSES`` (which bounds
        cross-pass divergence only).  Pinned with a BOUNDED counter far above the
        budget: it converges via a single run().  An *unconditional* self-re-add
        would hang in ``run()`` rather than raise — this documents that boundary.
        """
        from odoo.db.cursor import BaseCursor

        with registry().cursor() as cr:
            orig = cr.transaction
            cr.transaction = None  # isolate the precommit loop from the ORM
            try:
                remaining = [BaseCursor._MAX_FLUSH_PASSES * 5]

                def hook():
                    remaining[0] -= 1
                    if remaining[0] > 0:
                        cr.precommit.add(hook)

                cr.precommit.add(hook)
                cr.flush()  # converges in one run(), far past the pass budget
                self.assertEqual(remaining[0], 0)
                self.assertFalse(cr.precommit)
            finally:
                cr.transaction = orig
                cr.precommit.clear()
                cr.rollback()

    def test_flush_converges_at_budget(self):
        """A precommit chain that settles on the FINAL allowed pass must
        converge, not raise.  Before the fix the convergence check ran only
        *before* each run(), so the last run()'s effect was never re-examined
        and the effective budget was _MAX_FLUSH_PASSES - 1: a workload needing
        the full budget raised spuriously."""
        from odoo.db.cursor import BaseCursor

        class _BoundedTransaction:
            """flush() queues a hook for its first ``limit`` calls, then goes
            quiet — i.e. the ORM settles after exactly ``limit`` rounds."""

            def __init__(self, cr, limit):
                self._cr = cr
                self.limit = limit
                self.calls = 0

            def flush(self):
                if self.calls < self.limit:
                    self.calls += 1
                    self._cr.precommit.add(lambda: None)

            def clear(self):
                pass

        budget = BaseCursor._MAX_FLUSH_PASSES
        with registry().cursor() as cr:
            orig = cr.transaction
            try:
                cr.transaction = _BoundedTransaction(cr, budget)
                cr.flush()  # settles exactly at the budget -> must NOT raise
                self.assertFalse(cr.precommit)
                cr.transaction = _BoundedTransaction(cr, budget + 1)
                with self.assertRaises(RuntimeError):  # one past -> must raise
                    cr.flush()
            finally:
                cr.transaction = orig
                cr.precommit.clear()
                cr.rollback()


class TestUninitializedCursorClosed(BaseCase):
    """An instance that failed before __init__ set _closed must read as
    closed (class-level default) instead of recursing in __getattr__."""

    def test_uninitialized_cursor_raises_interface_error(self):
        cur = object.__new__(Cursor)
        with self.assertRaises(psycopg.InterfaceError):
            cur.some_attribute  # noqa: B018 — attribute access is the test


class TestCloseDatabaseByName(BaseCase):
    """close_database matches pools on the database component alone, so
    close_db() reaches URI-form pools too."""

    def test_close_database_matches_uri_pools(self):
        pool = ConnectionPool(maxconn=2)
        uri_key = _normalize_dsn_key(
            {"dsn": "postgresql://localhost/dbz?connect_timeout=10"}
        )
        uri_pool = MagicMock()
        uri_pool.closed = False
        other_key = _normalize_dsn_key({"dbname": "other"})
        other_pool = MagicMock()
        other_pool.closed = False
        pool._pools[uri_key] = uri_pool
        pool._pools[other_key] = other_pool

        pool.close_database("dbz")

        self.assertNotIn(uri_key, pool._pools)
        uri_pool.close.assert_called_once()
        self.assertIn(other_key, pool._pools)
        other_pool.close.assert_not_called()


class TestVersionGateInBorrow(BaseCase):
    """The minimum-PG-version check must fail fast in borrow() — raising in
    the configure callback surfaces as a generic 30s PoolTimeout with the
    actionable message buried in psycopg.pool warnings.
    (Source tripwires, same pattern as TestGetStatsLocked.)
    """

    def test_configure_does_not_raise_version_error(self):
        from odoo.db.pool import _configure_connection

        src = inspect.getsource(_configure_connection)
        self.assertNotIn("raise PoolError", src)

    def test_borrow_checks_server_version(self):
        # The gate lives in _check_min_server_version, shared by BOTH borrow
        # paths: _validate_borrowed_conn (pooled) and _borrow_direct
        # (maintenance databases) — still on the borrow path, not in the
        # configure callback.  Pin the gate's logic and its two call sites.
        gate_src = inspect.getsource(ConnectionPool._check_min_server_version)
        self.assertIn("server_version", gate_src)
        self.assertIn("MIN_PG_VERSION", gate_src)
        self.assertIn(
            "_check_min_server_version",
            inspect.getsource(ConnectionPool._validate_borrowed_conn),
        )
        self.assertIn(
            "_check_min_server_version",
            inspect.getsource(ConnectionPool._borrow_direct),
        )
        borrow_src = inspect.getsource(ConnectionPool.borrow)
        self.assertIn("_validate_borrowed_conn", borrow_src)


class TestPsycopgPoolPrivateApi(BaseCase):
    """Pin the private psycopg APIs this package depends on, so a psycopg /
    psycopg_pool upgrade that drops them fails here, not in production:
    putconn() requires conn._pool (set by getconn); execute() clears
    conn._prepared after DDL.  give_back() no longer reads conn._pool itself
    (it uses its own ``_odoo_pool`` marker), but putconn() still checks it."""

    def test_conn_pool_attribute_set_by_getconn(self):
        with registry().cursor() as cr:
            self.assertIsNotNone(getattr(cr._cnx, "_pool", None))

    def test_connection_prepared_attribute_exists(self):
        with registry().cursor() as cr:
            self.assertTrue(hasattr(cr._cnx, "_prepared"))


class TestPoolFailsFastOnMissingDatabase(BaseCase):
    """Connecting to a database that does not exist must fail fast with a
    precise InvalidCatalogName, not block ~30s on psycopg_pool's reconnect
    retry and surface an opaque PoolError. This keeps exp_db_exist (and the
    `db` CLI commands built on it) responsive on a typo'd database name."""

    def test_borrow_missing_db_raises_invalid_catalog_name_fast(self):
        pool = ConnectionPool(maxconn=4)
        self.addCleanup(pool.close_all)
        info = connection_info_for("zzz_missing_db_for_probe_test")[1]
        start = time.monotonic()
        with self.assertRaises(psycopg.errors.InvalidCatalogName):
            pool.borrow(info)
        elapsed = time.monotonic() - start
        # The pre-fix path blocked the full 30s getconn budget; a fast-fail is
        # sub-second. A generous bound keeps the assertion robust under CI load
        # while still catching a regression to the retry-until-timeout path.
        self.assertLess(
            elapsed,
            10,
            msg=f"missing-db connect took {elapsed:.1f}s — fast-fail probe regressed",
        )

    def test_probe_is_wired_into_pool_creation(self):
        # Tripwire: the fast-fail depends on the probe running on the
        # cache-miss path. Guard against a refactor silently dropping it.
        src = inspect.getsource(ConnectionPool._get_or_create_pool)
        self.assertIn("_probe_connectable", src)


class TestBorrowReturnsConnectionOnPostGetconnFailure(BaseCase):
    """borrow() must return the connection to its psycopg pool if anything
    AFTER getconn() raises (e.g. conn.info access on a degraded backend).

    The earlier code released only the semaphore on that path, leaking the
    psycopg-pool slot permanently — over time the per-DSN pool's max_size is
    exhausted and every borrow blocks.  Forcing conn.info to raise reproduces
    the leak; the fix wraps the post-getconn block to putconn on any failure.
    """

    def test_info_failure_returns_connection_and_releases_semaphore(self):
        pool = ConnectionPool(maxconn=4)
        info = connection_info_for("nonexistent_db_test")[1]
        key = _normalize_dsn_key(info)

        class _Info:
            @property
            def server_version(self):
                raise psycopg.OperationalError("simulated degraded backend")

            backend_pid = 1

        conn = MagicMock()
        conn.info = _Info()
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.getconn.return_value = conn
        pool._pools[key] = mock_pool

        sem_before = pool._pool_sem._value
        with self.assertRaises(psycopg.OperationalError):
            pool.borrow(info)

        mock_pool.putconn.assert_called_once_with(conn)
        self.assertEqual(
            pool._pool_sem._value,
            sem_before,
            "semaphore not released — borrow() leak fix regressed",
        )

    def test_min_version_path_also_returns_connection(self):
        pool = ConnectionPool(maxconn=4)
        info = connection_info_for("nonexistent_db_test")[1]
        key = _normalize_dsn_key(info)

        conn = MagicMock()
        conn.info.server_version = 150000  # PG15 < MIN_PG_VERSION
        conn.info.backend_pid = 1
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.getconn.return_value = conn
        pool._pools[key] = mock_pool

        sem_before = pool._pool_sem._value
        with self.assertRaises(PoolError):
            pool.borrow(info)
        mock_pool.putconn.assert_called_once_with(conn)
        self.assertEqual(pool._pool_sem._value, sem_before)


class TestExecutemanyGeneratorParams(BaseCase):
    """executemany() must handle a generator params_seq correctly: an empty
    generator short-circuits like an empty list, and a loaded generator both
    executes every row and records the right metric count (a generator has no
    len(), so the pre-fix code recorded 1 for an N-row batch).
    """

    def test_loaded_generator_executes_and_counts_all_rows(self):
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_em_gen (v int)")
            before = cr.sql_log_count
            cr.executemany(
                "INSERT INTO _test_em_gen(v) VALUES (%s)",
                ((i,) for i in range(3)),
            )
            counted = cr.sql_log_count - before
            cr.execute("SELECT count(*) FROM _test_em_gen")
            self.assertEqual(cr.fetchone()[0], 3)
            self.assertEqual(
                counted, 3, "metric undercount for generator — fix regressed"
            )

    def test_empty_generator_short_circuits(self):
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_em_empty (v int)")
            before = cr.sql_log_count
            cr.executemany("INSERT INTO _test_em_empty(v) VALUES (%s)", (x for x in ()))
            self.assertEqual(
                cr.sql_log_count, before, "empty generator must short-circuit"
            )
            cr.execute("SELECT count(*) FROM _test_em_empty")
            self.assertEqual(cr.fetchone()[0], 0)


class TestRecoverableErrorLogLevel(BaseCase):
    """Recoverable transaction errors (read-only retry, MVCC serialization,
    deadlock, lock-not-available) are part of normal operation under
    contention and are retried by the caller.  execute() must log them at
    WARNING, not ERROR ('bad query'), to avoid flooding the log with false
    faults on every retry.
    """

    def test_readonly_write_logged_as_warning_not_error(self):
        with self.assertLogs("odoo.db.cursor", level="WARNING") as cm:
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                with registry().cursor(readonly=True) as cr:
                    cr.execute(
                        "UPDATE res_users SET login = login WHERE id = %s",
                        (ADMIN_USER_ID,),
                    )
        levels = {r.levelname for r in cm.records}
        self.assertIn("WARNING", levels)
        self.assertNotIn(
            "ERROR", levels, "recoverable error logged at ERROR — fix regressed"
        )

    def test_lock_not_available_logged_as_warning_not_error(self):
        """LockNotAvailable (55P03) was NOT in the old special-case and hit the
        ERROR branch — this is the true old-vs-new differentiator.  Reproduced
        deterministically with FOR UPDATE NOWAIT against a row another cursor
        already holds locked.
        """
        with registry().cursor() as cr_lock:
            cr_lock.execute(
                "SELECT id FROM res_users WHERE id = %s FOR UPDATE",
                (ADMIN_USER_ID,),
            )
            with self.assertLogs("odoo.db.cursor", level="WARNING") as cm:
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    with registry().cursor() as cr_nowait:
                        cr_nowait.execute(
                            "SELECT id FROM res_users WHERE id = %s FOR UPDATE NOWAIT",
                            (ADMIN_USER_ID,),
                        )
        levels = {r.levelname for r in cm.records}
        self.assertIn("WARNING", levels)
        self.assertNotIn(
            "ERROR", levels, "LockNotAvailable logged at ERROR — fix regressed"
        )


class TestDDLDetectionLeadingWhitespace(BaseCase):
    """DDL detection reads the first two non-whitespace chars to gate the regex.
    The gate slice-then-lstrips a 64-char window to keep the hot path off a
    full-query copy, but falls back to a full lstrip when that window holds <2
    keyword chars (leading whitespace >=63).  DDL that begins after leading
    whitespace (Odoo's triple-quoted SQL) must still be detected so its params
    are inlined client-side — otherwise psycopg sends $1 which PostgreSQL
    rejects in a DEFAULT expression — and so the auto-prepared-statement cache
    is invalidated after a result-shape change.
    """

    def test_leading_whitespace_ddl_still_inlines_params(self):
        with registry().cursor() as cr:
            cr.execute(
                "\n            CREATE TEMP TABLE _test_ddl_ws (val int DEFAULT %s)",
                (7,),
            )
            cr.execute(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = '_test_ddl_ws' AND column_name = 'val'"
            )
            self.assertEqual(cr.fetchone()[0], "7")

    def test_deeply_indented_ddl_inlines_params(self):
        """DDL indented past the 64-char window must still inline params.

        With a fixed 64-char lstrip window, >62 chars of leading whitespace
        empties the window, the prefix gate misses the keyword, params are not
        inlined, and psycopg sends ``$1`` into the DEFAULT expression ->
        ``UndefinedParameter: there is no parameter $1``.
        """
        with registry().cursor() as cr:
            cr.execute(
                " " * 70 + "CREATE TEMP TABLE _test_ddl_deep (val int DEFAULT %s)",
                (7,),
            )
            cr.execute(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = '_test_ddl_deep' AND column_name = 'val'"
            )
            self.assertEqual(cr.fetchone()[0], "7")

    def test_deeply_indented_ddl_invalidates_prepared_cache(self):
        """A deeply-indented result-shape change must invalidate auto-prepare.

        ``CREATE``/``ALTER`` are detected so ``Cursor.execute`` clears psycopg's
        auto-prepared-statement cache.  If a deeply-indented ALTER slips past the
        gate, a previously auto-prepared ``SELECT *`` keeps its stale plan and
        the next execution raises ``cached plan must not change result type``.
        """
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_ddl_plan (a int)")
            cr.execute("INSERT INTO _test_ddl_plan VALUES (1)")
            # prepare_threshold=2: auto-prepare the SELECT * by running it 3x.
            for _ in range(3):
                cr.execute("SELECT * FROM _test_ddl_plan")
                cr.fetchall()
            cr.execute(" " * 70 + "ALTER TABLE _test_ddl_plan ADD COLUMN b int")
            cr.execute("SELECT * FROM _test_ddl_plan")
            self.assertEqual(cr.fetchall(), [(1, None)])


class TestResetConnectionClosesSessionGucLeak(BaseCase):
    """_reset_connection (the pool's return hook) runs the cheap session reset
    (``_RESET_SESSION_STATE_SQL``), so a plain ``SET search_path`` left behind
    by a borrower does NOT leak to the next borrower of the same physical
    connection — a multi-tenant isolation requirement.  Within a cursor's own
    life a session SET still survives rollback (the ODOO_FAKETIME_TEST_MODE
    path in Cursor.__init__ relies on that); the reset happens only at pool
    return.
    """

    def test_session_set_cleared_by_return_hook(self):
        cr = db_connect(common.get_db_name()).cursor()
        try:
            conn = cr.connection
            cr.execute("SET search_path = pg_catalog")
            cr.commit()  # close the txn so the SESSION-level SET sticks
            # Within the cursor's life, the session SET survives a rollback
            # (this is what the FAKETIME search_path pinning relies on).
            cr.rollback()
            cr.execute("SHOW search_path")
            self.assertEqual(cr.fetchscalar(), "pg_catalog")
            cr.rollback()  # close the SHOW's txn: the return hook needs no open txn
            # The pool's return hook closes the leak before the next borrower.
            _reset_connection(conn)
            cr.execute("SHOW search_path")
            self.assertNotEqual(
                cr.fetchscalar(),
                "pg_catalog",
                "_reset_connection must clear session GUCs (RESET ALL) so they "
                "cannot leak to the next borrower",
            )
        finally:
            # Hygiene: never return a connection with a mutated search_path to
            # the shared pool — the next borrower (another test) would inherit
            # it if the reset contract ever regresses.
            cr.execute("RESET search_path")
            cr.commit()
            cr.close()


class TestProbeDoesNotBlockOtherDatabases(BaseCase):
    """_get_or_create_pool must run the synchronous pre-flight probe OUTSIDE
    self._lock.  self._lock serializes creation of every per-DSN pool, so a
    slow/unreachable probe for one database held across the lock would stall
    pool creation for every OTHER database.
    """

    def test_slow_probe_for_one_db_does_not_block_another(self):
        pool = ConnectionPool(maxconn=8)
        probe_sleep = 1.0

        class _StubPool:
            closed = False

            def __init__(self, *a, **k):
                pass

            def get_stats(self):
                return {}

            def close(self):
                pass

            @staticmethod
            def check_connection(conn):
                return None

        probe_started = threading.Event()

        def slow_probe(conninfo, kwargs):
            probe_started.set()
            time.sleep(probe_sleep)

        errors = []
        elapsed = {}

        def create(label, info):
            try:
                t0 = time.monotonic()
                pool._get_or_create_pool(frozenset(info.items()), dict(info))
                elapsed[label] = time.monotonic() - t0
            except Exception as e:
                errors.append(f"{label}: {type(e).__name__}: {e}")

        with (
            patch("odoo.db.pool._PsycopgPool", _StubPool),
            patch.object(pool, "_probe_connectable", side_effect=slow_probe),
        ):
            t_a = threading.Thread(target=create, args=("a", {"database": "a"}))
            t_b = threading.Thread(target=create, args=("b", {"database": "b"}))
            start = time.monotonic()
            t_a.start()
            # Only start B once A is confirmed inside the probe; this is the
            # exact interleaving that deadlocked on the shared lock before.
            self.assertTrue(probe_started.wait(5.0), "probe for A never started")
            t_b.start()
            t_a.join()
            t_b.join()
            wall = time.monotonic() - start

        pool.close_all()
        self.assertEqual(errors, [], f"pool creation raised: {errors}")
        # Independent probes => wall ~= probe_sleep.  Serialized by the shared
        # lock => wall ~= 2 * probe_sleep.  1.6x cleanly separates the two.
        self.assertLess(
            wall,
            probe_sleep * 1.6,
            f"pool creation for two different databases serialized "
            f"(wall={wall:.2f}s, probe={probe_sleep}s) — the probe is holding "
            f"the shared _pools lock across its network round-trip",
        )

    def test_probe_uses_short_connect_timeout(self):
        """The throwaway probe must bound itself to _PROBE_CONNECT_TIMEOUT, not
        inherit the 10s connect_timeout that _HEALTH_PARAMS injects into kwargs
        (a ``setdefault`` there would be a silent no-op).
        """
        from odoo.db.pool import _PROBE_CONNECT_TIMEOUT

        pool = ConnectionPool(maxconn=2)
        captured = {}

        def fake_connect(conninfo, **kw):
            captured.update(kw)
            # transient failure => swallowed by _probe_connectable, no raise out
            raise psycopg.OperationalError("connection refused")

        with patch("psycopg.connect", side_effect=fake_connect):
            pool._probe_connectable(
                "", {"dbname": "x", "connect_timeout": "10", "options": "-c jit=off"}
            )
        self.assertEqual(captured.get("connect_timeout"), _PROBE_CONNECT_TIMEOUT)


class TestAdapterIsolationPerConnection(BaseCase):
    """The numeric->float loader is registered per-connection (in the pool's
    configure callback), NOT on the process-global ``psycopg.adapters``.  So a
    pooled Odoo cursor decodes numeric as float, while a raw psycopg connection
    that bypassed the pool decodes it as Decimal.  Locks the fix that stops the
    db package from mutating global psycopg state merely by being imported.
    """

    def test_pooled_cursor_decodes_numeric_as_float(self):
        with registry().cursor() as cr:
            cr.execute("SELECT 1.5::numeric")
            self.assertIsInstance(cr.fetchone()[0], float)

    def test_raw_connection_decodes_numeric_as_decimal(self):
        # Built directly, not via the pool's configure callback -> must NOT
        # inherit Odoo's float loader, proving there is no global side effect.
        _, info = connection_info_for(common.get_db_name())
        conn = psycopg.connect(**info)
        try:
            self.assertIsInstance(
                conn.execute("SELECT 1.5::numeric").fetchone()[0], Decimal
            )
        finally:
            conn.close()


class TestPoolMinconn(BaseCase):
    """db_minconn warms connections per per-DSN pool; it defaults to 0 (lazy
    open, multi-tenant friendly) and is validated against maxconn so the pool
    can never be told to keep more connections warm than it can hand out.
    """

    def test_default_minconn_is_zero(self):
        pool = ConnectionPool(maxconn=4)
        try:
            self.assertEqual(pool._minconn, 0)
        finally:
            pool.close_all()

    def test_minconn_stored(self):
        pool = ConnectionPool(maxconn=4, minconn=2)
        try:
            self.assertEqual(pool._minconn, 2)
        finally:
            pool.close_all()

    def test_minconn_exceeding_maxconn_raises(self):
        with self.assertRaises(ValueError):
            ConnectionPool(maxconn=4, minconn=5)

    def test_negative_minconn_raises(self):
        with self.assertRaises(ValueError):
            ConnectionPool(maxconn=4, minconn=-1)

    def test_maintenance_databases_are_never_pooled(self):
        """postgres/template connections bypass psycopg_pool entirely.

        A per-DSN pool can never keep a maintenance database connection-free:
        psycopg_pool replaces every discarded connection to hold its count
        (regardless of ``min_size``), and the idle replacement blocks
        ``CREATE DATABASE ... TEMPLATE`` with "source database is being
        accessed by other users".  So ``borrow`` must not create a pool at all
        (no worker threads, no replacement race) and ``give_back`` must close
        the connection outright.
        """
        pool = ConnectionPool(maxconn=4, minconn=2)
        _, info = connection_info_for("postgres")
        try:
            conn = pool.borrow(info)
            self.assertEqual(
                pool._pools, {}, "no per-DSN pool may exist for 'postgres'"
            )
            self.assertFalse(conn.closed)
            # Outstanding direct connections are tracked (repr/exhaustion
            # messages) and get the server-side escaped-connection net.
            self.assertEqual(pool._direct_out, 1)
            self.assertEqual(
                conn.execute("SHOW idle_session_timeout").fetchone()[0], "15min"
            )
            conn.rollback()
            pool.give_back(conn)
            self.assertTrue(
                conn.closed, "maintenance-db connection must close on give_back"
            )
            self.assertEqual(pool._direct_out, 0)
            # The semaphore permit was released: maxconn borrows succeed again.
            conns = [pool.borrow(info) for _ in range(4)]
            for c in conns:
                pool.give_back(c)
        finally:
            pool.close_all()

    def test_maintenance_db_double_give_back_is_noop(self):
        """A second give_back of a direct connection must not double-release
        the semaphore permit (the ``_odoo_pool`` marker is cleared first)."""
        pool = ConnectionPool(maxconn=2)
        _, info = connection_info_for("postgres")
        try:
            conn = pool.borrow(info)
            pool.give_back(conn)
            pool.give_back(conn)  # marker cleared -> no-op branch
            a = pool.borrow(info)
            b = pool.borrow(info)
            # a third borrow must still hit the (2-permit) budget
            pool._borrow_timeout = 0.2
            with self.assertRaises(PoolError):
                pool.borrow(info)
            pool.give_back(a)
            pool.give_back(b)
        finally:
            pool.close_all()


class TestPoolSessionGucOptions(BaseCase):
    """_get_or_create_pool appends Odoo's session GUCs to the libpq ``options``
    kwarg.  psycopg gives kwargs per-key precedence over the conninfo string,
    so a URI's own ``?options=`` GUCs must be folded into the kwarg — setting
    ours without merging would silently drop the operator's (e.g. search_path).
    """

    def _created_pool_args(self, connection_info, **pool_kw):
        pool = ConnectionPool(maxconn=2, **pool_kw)
        created = {}

        class _FakePool:
            closed = False

            def __init__(self, conninfo, **kw):
                created["conninfo"] = conninfo
                created.update(kw)

            def close(self):
                pass

            def get_stats(self):
                return {}

        key = _normalize_dsn_key(connection_info)
        with (
            patch.object(pool_module, "_PsycopgPool", _FakePool),
            patch.object(pool, "_probe_connectable"),
        ):
            try:
                pool._get_or_create_pool(key, dict(connection_info))
            finally:
                pool.close_all()
        return created

    def test_uri_options_preserved_alongside_session_gucs(self):
        created = self._created_pool_args(
            {"dsn": "postgresql://u@h/db?options=-csearch_path%3Dfoo"}
        )
        opts = created["kwargs"]["options"]
        self.assertIn("search_path=foo", opts, "URI ?options= GUC was dropped")
        self.assertIn("jit=off", opts)
        self.assertIn("work_mem=16MB", opts)

    def test_keyword_options_preserved(self):
        created = self._created_pool_args(
            {"dbname": "db", "options": "-c statement_timeout=5000"}
        )
        opts = created["kwargs"]["options"]
        self.assertIn("statement_timeout=5000", opts)
        self.assertIn("jit=off", opts)

    def test_pgoptions_env_used_as_fallback(self):
        # libpq would honour PGOPTIONS on its own, but Odoo passes an explicit
        # ``options`` kwarg which overrides the env wholesale — so the env
        # value must be folded in (lowest precedence).
        with patch.dict(os.environ, {"PGOPTIONS": "-c search_path=envpath"}):
            created = self._created_pool_args({"dbname": "db"})
        opts = created["kwargs"]["options"]
        self.assertIn("search_path=envpath", opts)
        self.assertIn("jit=off", opts)

    def test_pgoptions_env_loses_to_explicit_options(self):
        # An explicit kwarg (or URI ?options=) is more specific than the env.
        with patch.dict(os.environ, {"PGOPTIONS": "-c search_path=envpath"}):
            created = self._created_pool_args(
                {"dbname": "db", "options": "-c statement_timeout=5000"}
            )
        opts = created["kwargs"]["options"]
        self.assertIn("statement_timeout=5000", opts)
        self.assertNotIn("envpath", opts)

    def test_idle_session_timeout_default_unchanged(self):
        """Default max_idle (600s) keeps the historical 15-minute server net."""
        created = self._created_pool_args({"dbname": "db"})
        self.assertIn("idle_session_timeout=900000", created["kwargs"]["options"])

    def test_idle_session_timeout_scales_with_max_idle(self):
        """Raising db_conn_max_idle must keep the server-side timeout above the
        pool's idle window, or the server silently kills warm pooled
        connections and every borrow past the grace period pays a reconnect."""
        created = self._created_pool_args({"dbname": "db"}, max_idle=1200)
        self.assertIn("idle_session_timeout=1800000", created["kwargs"]["options"])


class TestCopyFromMetricsQueryLazy(BaseCase):
    """copy_from renders the COPY statement to text for metrics ONLY when a
    thread query hook will consume it; otherwise it passes ``query=None`` to
    skip a wasted SQL render on every bulk insert (copy_from is a hot path).
    """

    def test_no_hook_passes_none(self):
        captured = {}
        orig = Cursor._record_metrics

        def spy(
            self, delay, count=1, *, query=None, params=None, start=0.0, hooks=None
        ):
            captured["query"] = query
            return orig(
                self, delay, count, query=query, params=params, start=start, hooks=hooks
            )

        with patch.object(Cursor, "_record_metrics", spy):
            with registry().cursor() as cr:
                cr.execute("CREATE TEMP TABLE _t_metrics_nh (a int)")
                cr.copy_from("_t_metrics_nh", ["a"], [(1,), (2,)])
        self.assertIsNone(captured["query"])

    def test_hook_receives_rendered_copy_statement(self):
        seen = []
        t = threading.current_thread()
        t.query_hooks = [lambda cr, q, p, s, d: seen.append(q)]
        try:
            with registry().cursor() as cr:
                cr.execute("CREATE TEMP TABLE _t_metrics_h (a int)")
                cr.copy_from("_t_metrics_h", ["a"], [(1,)])
        finally:
            del t.query_hooks
        self.assertTrue(seen)
        self.assertIsInstance(seen[-1], str)
        self.assertTrue(seen[-1].startswith("COPY"))


class TestCopyFromBinaryNumeric(BaseCase):
    """Binary COPY into numeric columns: psycopg's binary numeric dumper rejects
    Python float and requires Decimal, so copy_from converts float->Decimal for
    numeric columns.  The pre-existing suite exercised only integer columns.
    """

    def test_binary_copy_float_into_numeric_roundtrips(self):
        with registry().cursor() as cr:
            cr.execute(
                "CREATE TEMP TABLE _t_bin_num (a int, n numeric(12,2), m numeric)"
            )
            cr.copy_from(
                "_t_bin_num",
                ["a", "n", "m"],
                [(1, 1234.56, 0.1), (2, -7.0, 99999.999)],
                binary=True,
            )
            cr.execute("SELECT a, n, m FROM _t_bin_num ORDER BY a")
            rows = cr.fetchall()
        self.assertEqual(rows[0][0], 1)
        self.assertAlmostEqual(rows[0][1], 1234.56, places=2)
        self.assertAlmostEqual(rows[0][2], 0.1, places=6)
        self.assertAlmostEqual(rows[1][1], -7.0, places=2)


class TestCursorForwardingContract(BaseCase):
    """Lock the cursor's public forwarding surface.  The project runs no static
    type checker, so the __getattr__ DeprecationWarning is the ONLY signal that
    a caller reached a non-forwarded psycopg attribute.  Pin the contract: the
    curated forwards must not warn, and a known non-forwarded attr must.
    """

    FORWARDED = (
        "fetchone",
        "fetchall",
        "fetchmany",
        "description",
        "rowcount",
        "nextset",
        "connection",
        "readonly",
    )

    def test_forwarded_names_do_not_warn(self):
        with registry().cursor() as cr:
            cr.execute("SELECT 1")
            for name in self.FORWARDED:
                with warnings.catch_warnings(record=True) as w:
                    warnings.simplefilter("always")
                    getattr(cr, name)
                offenders = [
                    str(x.message)
                    for x in w
                    if issubclass(x.category, DeprecationWarning)
                    and "Odoo cursor API" in str(x.message)
                ]
                self.assertEqual(offenders, [], f"{name} unexpectedly warned")

    def test_non_forwarded_attr_warns(self):
        with registry().cursor() as cr:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                _ = cr.row_factory  # real psycopg attr, intentionally not forwarded
            msgs = [
                str(x.message)
                for x in w
                if issubclass(x.category, DeprecationWarning)
                and "Odoo cursor API" in str(x.message)
            ]
            self.assertEqual(len(msgs), 1, f"expected one warning, got {msgs}")


class TestBorrowValidationFailureNoLeak(BaseCase):
    """A validation failure AFTER the semaphore is acquired and getconn()
    succeeded must release the permit AND return the connection to its psycopg
    pool — otherwise both the _pool_sem budget and the per-DSN pool slot leak.

    Since #2 replaced the psycopg-``_pool`` tripwire with an Odoo-owned
    ``_odoo_pool`` marker (see TestPoolSemaphoreAccounting), the surviving
    in-borrow validation is the minimum-PostgreSQL-version gate; it exercises
    the same inner-putconn / outer-release recovery path the tripwire used.
    """

    def test_version_gate_failure_releases_semaphore_and_putconn(self):
        pool = ConnectionPool(maxconn=4)
        info = connection_info_for("nonexistent_db_test")[1]
        key = _normalize_dsn_key(info)

        # A reachable server below MIN_PG_VERSION: the version gate raises, so
        # borrow() must release the permit it acquired before getconn() AND hand
        # the connection back to its psycopg pool.
        conn = MagicMock()
        conn.info.server_version = 170000  # 17.x — below the minimum
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.getconn.return_value = conn
        pool._pools[key] = mock_pool

        sem_before = pool._pool_sem._value
        with self.assertRaises(PoolError):
            pool.borrow(info)
        mock_pool.putconn.assert_called_once_with(conn)
        self.assertEqual(
            pool._pool_sem._value,
            sem_before,
            "semaphore leaked when borrow() rejected a connection in validation",
        )


class TestCursorInitCursorFailureReturnsConnection(BaseCase):
    """If ``self._cnx.cursor()`` raises inside ``Cursor.__init__`` right after a
    successful ``borrow()``, the except handler must (a) surface the REAL error
    and (b) still ``give_back()`` the borrowed connection — otherwise the
    connection and its ``_pool_sem`` permit leak for the process life.

    Regression: the handler read ``getattr(self, "_obj", None)``; when
    ``cursor()`` failed ``_obj`` was never set, so that getattr routed through
    ``Cursor.__getattr__`` and raised ``InterfaceError("Cursor already closed")``
    — masking the real error and skipping ``give_back()``.  The fix reads
    ``_obj`` straight from ``__dict__``.
    """

    def test_cursor_failure_propagates_real_error_and_returns_connection(self):
        sentinel = psycopg.OperationalError("simulated cursor() failure")
        conn = MagicMock()
        conn.closed = False
        conn.cursor.side_effect = sentinel
        pool = MagicMock()
        pool.readonly = False
        pool.borrow.return_value = conn

        with self.assertRaises(psycopg.OperationalError) as cm:
            Cursor(pool, "somedb", {"dbname": "somedb"})

        # (a) the genuine error surfaces — NOT a masking InterfaceError.
        self.assertIs(
            cm.exception,
            sentinel,
            "Cursor.__init__ masked the real cursor() failure with a different "
            "exception (the __getattr__-via-getattr regression)",
        )
        # (b) the borrowed connection is handed back — the leak fix.
        pool.give_back.assert_called_once_with(conn)


class TestPasswordRotationEvictsStalePool(BaseCase):
    """A rotated password yields a new pool key (the password fingerprint in
    _normalize_dsn_key differs).  _get_or_create_pool must evict and close the
    OLD per-DSN pool — otherwise its worker threads and idle connections leak in
    self._pools until close_all().  A genuinely different host/port/user keeps
    its own pool (those components ARE part of the key).
    """

    @staticmethod
    def _pool_factory():
        def factory(*args, **kwargs):
            m = MagicMock()
            m.closed = False
            return m

        return factory

    def test_rotation_evicts_and_closes_old_pool(self):
        pool = ConnectionPool(maxconn=4)
        pool._probe_connectable = lambda *a, **k: None
        base = {"dbname": "rotdb", "host": "h", "user": "u"}
        info_old = {**base, "password": "old"}
        info_new = {**base, "password": "new"}
        k_old = _normalize_dsn_key(info_old)
        k_new = _normalize_dsn_key(info_new)
        with patch("odoo.db.pool._PsycopgPool") as PP:
            PP.side_effect = self._pool_factory()
            old_pool = pool._get_or_create_pool(k_old, info_old)
            pool._get_or_create_pool(k_new, info_new)

        self.assertNotIn(k_old, pool._pools, "old-password pool was not evicted")
        self.assertIn(k_new, pool._pools)
        old_pool.close.assert_called_once()

    def test_different_user_pool_is_preserved(self):
        pool = ConnectionPool(maxconn=4)
        pool._probe_connectable = lambda *a, **k: None
        base = {"dbname": "rotdb", "host": "h", "password": "p"}
        info_u1 = {**base, "user": "u1"}
        info_u2 = {**base, "user": "u2"}
        k1 = _normalize_dsn_key(info_u1)
        k2 = _normalize_dsn_key(info_u2)
        with patch("odoo.db.pool._PsycopgPool") as PP:
            PP.side_effect = self._pool_factory()
            pool._get_or_create_pool(k1, info_u1)
            pool._get_or_create_pool(k2, info_u2)

        self.assertIn(k1, pool._pools, "different-user pool must NOT be evicted")
        self.assertIn(k2, pool._pools)


class TestCopyFromRecoverableErrorLogLevel(BaseCase):
    """copy_from() previously hand-rolled ``_logger.error("bad COPY: …")``,
    so a recoverable serialization failure / deadlock / lock-timeout during a
    bulk ``create()`` — which the request's ``retrying`` loop catches and
    retries — logged a false ERROR on every attempt.  It must now log at
    WARNING like execute()/executemany(), via the shared _log_sql_error().

    Reproduced deterministically (no mocks): a second connection holds an
    ACCESS EXCLUSIVE lock on the target table, so COPY's RowExclusiveLock
    acquisition blocks and trips ``lock_timeout`` → LockNotAvailable (55P03),
    a member of PG_RECOVERABLE_EXCEPTIONS.
    """

    def setUp(self):
        super().setUp()
        with registry().cursor() as cr:
            cr.execute("DROP TABLE IF EXISTS _cf_lock")
            cr.execute("CREATE TABLE _cf_lock (v int)")
            cr.commit()
        self.addCleanup(self._drop)

    def _drop(self):
        with registry().cursor() as cr:
            cr.execute("DROP TABLE IF EXISTS _cf_lock")
            cr.commit()

    def test_copy_from_lock_timeout_logged_as_warning_not_error(self):
        with registry().cursor() as cr_lock:
            cr_lock.execute("LOCK TABLE _cf_lock IN ACCESS EXCLUSIVE MODE")
            with self.assertLogs("odoo.db.cursor", level="WARNING") as cm:
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    with registry().cursor() as cr_copy:
                        cr_copy.execute("SET lock_timeout = '250ms'")
                        cr_copy.copy_from("_cf_lock", ["v"], [(1,), (2,)])
        levels = {r.levelname for r in cm.records}
        self.assertIn("WARNING", levels)
        self.assertNotIn(
            "ERROR",
            levels,
            "recoverable COPY error logged at ERROR — copy_from regressed to "
            "its old hand-rolled _logger.error path",
        )
        # the WARNING must name the recoverable error, not a 'bad COPY' fault
        self.assertTrue(
            any("recoverable SQL error" in r.getMessage() for r in cm.records)
        )


class TestConcurrencyErrorTaxonomy(BaseCase):
    """The PG concurrency-retry vocabulary lives once in ``odoo.db.errors``;
    ``odoo.service.transaction`` aliases it as the public ``PG_CONCURRENCY_*``
    names that addons import.  These guards stop the SQLSTATE list, the exception
    list, and the log-level (RECOVERABLE) set from drifting apart again.
    """

    def test_sqlstates_match_exception_classes(self):
        from odoo.db.errors import PG_RETRY_EXCEPTIONS, PG_RETRY_SQLSTATES

        # each retry exception's own .sqlstate must equal the string list, in order
        self.assertEqual(
            tuple(exc.sqlstate for exc in PG_RETRY_EXCEPTIONS),
            PG_RETRY_SQLSTATES,
        )

    def test_recoverable_is_retryable_plus_read_only(self):
        from odoo.db.errors import PG_RECOVERABLE_EXCEPTIONS, PG_RETRY_EXCEPTIONS

        # RECOVERABLE (logged at WARNING) = retryable + read-only-transaction (25006)
        extra = set(PG_RECOVERABLE_EXCEPTIONS) - set(PG_RETRY_EXCEPTIONS)
        self.assertEqual(extra, {psycopg.errors.ReadOnlySqlTransaction})

    def test_public_aliases_are_the_canonical_objects(self):
        from odoo.db import errors as db_errors
        from odoo.service import transaction as svc

        # the names addons import resolve to the single source of truth
        self.assertIs(
            svc.PG_CONCURRENCY_EXCEPTIONS_TO_RETRY, db_errors.PG_RETRY_EXCEPTIONS
        )
        self.assertIs(svc.PG_CONCURRENCY_ERRORS_TO_RETRY, db_errors.PG_RETRY_SQLSTATES)


class TestExecutemanyLogExceptions(BaseCase):
    """executemany() gained the ``log_exceptions`` flag that execute() already
    had — a caller that logs its own message can now silence the batched path
    just like the single-statement one.
    """

    def test_log_exceptions_false_suppresses_error_log(self):
        with self.assertNoLogs("odoo.db.cursor", level="ERROR"):
            with self.assertRaises(psycopg.Error):
                with registry().cursor() as cr:
                    cr.executemany(
                        "INSERT INTO _no_such_table_xyz (v) VALUES (%s)",
                        [(1,)],
                        log_exceptions=False,
                    )

    def test_default_still_logs_error(self):
        with self.assertLogs("odoo.db.cursor", level="ERROR") as cm:
            with self.assertRaises(psycopg.Error):
                with registry().cursor() as cr:
                    cr.executemany(
                        "INSERT INTO _no_such_table_xyz (v) VALUES (%s)",
                        [(1,)],
                    )
        self.assertTrue(any("bad query" in r.getMessage() for r in cm.records))


class TestDictFetchManyNegativeSize(BaseCase):
    """Cursor.dictfetchmany(-1) used to raise psycopg's InterfaceError while
    BaseCursor.dictfetchmany(-1) returned [] — the base contract and its
    production override disagreed on the same invalid input.  They now agree.
    """

    def test_negative_size_returns_empty_and_preserves_rows(self):
        with registry().cursor() as cr:
            cr.execute("SELECT generate_series(1, 3) AS v")
            # negative size short-circuits to [] (matching BaseCursor) without
            # touching the result set...
            self.assertEqual(cr.dictfetchmany(-1), [])
            # ...so a subsequent positive fetch still sees all three rows.
            self.assertEqual(len(cr.dictfetchmany(3)), 3)

    def test_zero_and_oversize_unchanged(self):
        with registry().cursor() as cr:
            cr.execute("SELECT generate_series(1, 3) AS v")
            self.assertEqual(cr.dictfetchmany(0), [])
            # oversize is the normal path and must still return all rows
            self.assertEqual(len(cr.dictfetchmany(10)), 3)


class TestPoolCleanupIsolatesFailures(BaseCase):
    """A single per-DSN pool whose close()/drain() raises must not abort the
    cleanup of its siblings nor propagate out of close_all/close_database/
    drain/drain_database.  These run on the worst paths — the atexit handler
    (close_all) and post-upgrade drain_all — where one bad pool stranding the
    rest (worker threads + idle connections leaked, since _pools is already
    cleared) is exactly the failure to avoid.  Mirrors the isolation already
    present in give_back() and the stale-credential eviction.
    """

    class _FakePool:
        def __init__(self, name, raises=False):
            self.name = name
            self.raises = raises
            self.close_called = False
            self.drain_called = False
            self.closed = False

        def close(self):
            self.close_called = True
            if self.raises:
                raise RuntimeError(f"{self.name}: simulated close failure")

        def drain(self):
            self.drain_called = True
            if self.raises:
                raise RuntimeError(f"{self.name}: simulated drain failure")

        def get_stats(self):
            return {}

    def _make_pool_with(self, *fakes):
        cp = ConnectionPool(maxconn=8)
        cp._pools = {frozenset([("database", fp.name)]): fp for fp in fakes}
        return cp

    def test_close_all_closes_survivors_despite_failure(self):
        a = self._FakePool("A", raises=True)
        b = self._FakePool("B")
        c = self._FakePool("C")
        cp = self._make_pool_with(a, b, c)
        # Must not raise, and every pool must get close()d.
        cp.close_all()
        self.assertTrue(a.close_called and b.close_called and c.close_called)
        self.assertEqual(cp._pools, {})

    def test_close_database_closes_survivors_despite_failure(self):
        a = self._FakePool("db", raises=True)
        b = self._FakePool("db")
        cp = ConnectionPool(maxconn=8)
        cp._pools = {
            frozenset([("database", "db"), ("host", "h1")]): a,
            frozenset([("database", "db"), ("host", "h2")]): b,
        }
        cp.close_database("db")
        self.assertTrue(a.close_called and b.close_called)
        self.assertEqual(cp._pools, {})

    def test_drain_drains_survivors_despite_failure(self):
        a = self._FakePool("A", raises=True)
        b = self._FakePool("B")
        cp = self._make_pool_with(a, b)
        cp.drain()  # must not raise
        self.assertTrue(a.drain_called and b.drain_called)

    def test_drain_database_drains_survivors_despite_failure(self):
        a = self._FakePool("db", raises=True)
        b = self._FakePool("db")
        cp = ConnectionPool(maxconn=8)
        cp._pools = {
            frozenset([("database", "db"), ("host", "h1")]): a,
            frozenset([("database", "db"), ("host", "h2")]): b,
        }
        cp.drain_database("db")
        self.assertTrue(a.drain_called and b.drain_called)


class TestDdlCacheInvalidationNarrowed(BaseCase):
    """Only schema-changing DDL invalidates the binary-COPY column-type cache.

    ``Cursor.execute`` used to clear the schema_cache (and the prepared-statement
    cache) on *any* DDL.  COMMENT / GRANT / REVOKE are DDL for parameter inlining
    but never change a relation's shape, so they must now leave a populated cache
    intact; CREATE / ALTER / DROP / DO still clear it.
    """

    def test_comment_grant_keep_cache_alter_clears_it(self):
        tbl = "_test_ddl_narrow"
        cr = db_connect(common.get_db_name()).cursor()
        try:
            cr.execute(f"CREATE TABLE {tbl} (x int)")
            # Populate the column-type cache via a binary copy_from.
            cr.copy_from(tbl, ["x"], [(1,)], binary=True)
            self.assertEqual(
                schema_cache.get_column_types(cr.dbname, tbl, ["x"]),
                ["int4"],
                "binary copy_from should have cached the column type",
            )
            # COMMENT carries a %s param, so this also proves COMMENT is still
            # detected as DDL (the param is inlined client-side); yet it must
            # NOT clear the cache.
            cr.execute(f"COMMENT ON TABLE {tbl} IS %s", ("narrowing test",))
            self.assertEqual(
                schema_cache.get_column_types(cr.dbname, tbl, ["x"]),
                ["int4"],
                "COMMENT (non-schema-changing DDL) must not clear the cache",
            )
            # REVOKE likewise leaves it intact.
            cr.execute(f"REVOKE ALL ON TABLE {tbl} FROM PUBLIC")
            self.assertEqual(
                schema_cache.get_column_types(cr.dbname, tbl, ["x"]),
                ["int4"],
                "REVOKE (non-schema-changing DDL) must not clear the cache",
            )
            # ALTER changes the shape → cache must be invalidated.
            cr.execute(f"ALTER TABLE {tbl} ALTER COLUMN x TYPE bigint")
            self.assertIsNone(
                schema_cache.get_column_types(cr.dbname, tbl, ["x"]),
                "ALTER (schema-changing DDL) must clear the cache",
            )
        finally:
            schema_cache.clear(cr.dbname)
            cr.rollback()  # CREATE TABLE is transactional — nothing leaks
            cr.close()


class TestDdlInvalidatesPreparedPlan(BaseCase):
    """A schema-changing DDL must drop psycopg's auto-prepared-statement cache on
    the connection that ran it.  Otherwise a later ``SELECT *`` reusing a plan
    prepared against the old shape raises PostgreSQL's
    ``cached plan must not change result type`` (FeatureNotSupported) — a real
    failure path (reproduced: ``ALTER TABLE ... ADD COLUMN`` after the plan was
    cached).  ``Cursor._invalidate_caches_after_ddl`` clears it via the private
    ``_cnx._prepared.clear()`` (no public psycopg API exists).  This guards that
    half end-to-end against a live backend; the binary-COPY ``schema_cache`` half
    is covered by :class:`TestDdlCacheInvalidationNarrowed`.
    """

    def test_alter_after_prepared_select_star_does_not_raise(self):
        tbl = "_test_prepared_plan"
        cr = db_connect(common.get_db_name()).cursor()
        try:
            cr.execute(f"DROP TABLE IF EXISTS {tbl}")
            cr.execute(f"CREATE TABLE {tbl} (a int)")
            cr.execute(f"INSERT INTO {tbl} VALUES (1)")
            # Auto-prepare "SELECT *": _configure_connection sets
            # prepare_threshold=2, so a handful of identical executions caches
            # the plan together with its (old) result descriptor.
            for _ in range(5):
                cr.execute(f"SELECT * FROM {tbl}")
                cr.fetchall()
            # Schema-changing DDL on the SAME connection invalidates that plan;
            # _invalidate_caches_after_ddl must drop it (queues DEALLOCATE ALL).
            cr.execute(f"ALTER TABLE {tbl} ADD COLUMN b int")
            try:
                cr.execute(f"SELECT * FROM {tbl}")
                rows = cr.fetchall()
            except psycopg.errors.FeatureNotSupported as e:
                self.fail(
                    "prepared-statement cache not invalidated after schema-"
                    f"changing DDL: {e}"
                )
            # New column visible -> the plan was re-prepared against the new shape.
            self.assertEqual(rows, [(1, None)])
        finally:
            cr.rollback()  # DROP/CREATE/ALTER are transactional — nothing leaks
            cr.close()


class TestReplicaConnectionInfo(BaseCase):
    """A read-only replica overrides only host/port (the registered
    ``db_replica_*`` options); user/password/sslmode are inherited from the
    primary ``db_*`` config, since no ``db_replica_user`` (etc.) option exists.
    """

    def test_readonly_overrides_host_port_inherits_credentials(self):
        from odoo.tools import config

        keys = (
            "db_host",
            "db_port",
            "db_user",
            "db_password",
            "db_sslmode",
            "db_replica_host",
            "db_replica_port",
        )
        saved = {k: config[k] for k in keys}
        try:
            config["db_host"] = "primary.example"
            config["db_port"] = 5432
            config["db_user"] = "primary_user"
            config["db_password"] = "primary_pw"
            config["db_sslmode"] = "require"
            config["db_replica_host"] = "replica.example"
            config["db_replica_port"] = 5433

            _, ro = connection_info_for("mydb", readonly=True)
            self.assertEqual(ro["host"], "replica.example")
            self.assertEqual(ro["port"], 5433)
            # credentials inherited from the primary (no per-replica options)
            self.assertEqual(ro["user"], "primary_user")
            self.assertEqual(ro["password"], "primary_pw")
            self.assertEqual(ro["sslmode"], "require")

            # the read/write path keeps the primary host/port
            _, rw = connection_info_for("mydb", readonly=False)
            self.assertEqual(rw["host"], "primary.example")
            self.assertEqual(rw["port"], 5432)
        finally:
            for k, v in saved.items():
                config[k] = v
