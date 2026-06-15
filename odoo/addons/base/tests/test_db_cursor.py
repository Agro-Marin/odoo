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
from odoo.db import utils as _db_utils
from odoo.db.cursor import (
    Cursor,
    _find_value_markers,
    _FlushingSavepoint,
    _id_sequence_cache,
    _inline_ddl_params,
)
from odoo.db.pool import (
    ConnectionPool,
    PoolError,
    _normalize_dsn_key,
    _reset_connection,
    _SuppressKnownPoolWarnings,
    _translate_connect_error,
)
from odoo.db.utils import categorize_query, connection_info_for
from odoo.modules.registry import Registry
from odoo.service.db import exp_drop
from odoo.tests import common
from odoo.tests.common import BaseCase, HttpCase
from odoo.tests.test_cursor import TestCursor
from odoo.tools import SQL

ADMIN_USER_ID = common.ADMIN_USER_ID


def registry():
    return Registry(common.get_db_name())


class TestRealCursor(BaseCase):
    def test_execute_bad_params(self):
        """
        Try to use iterable but non-list or int params in query parameters.
        """
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

        # a generic patcher to check if the method was called with a readonly cursor or not.
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
        # make the registry in test mode
        self.registry_enter_test_mode()
        # now we make a test cursor for self.cr
        self.cr = self.registry.cursor()
        self.addCleanup(self.cr.close)
        self.env = api.Environment(self.cr, api.SUPERUSER_ID, {})
        self.record = self.env["res.partner"].create({"name": "Foo"})

    def write(self, record, value):
        record.ref = value

    def flush(self, record):
        record.flush_model(["ref"])

    def check(self, record, value):
        # make sure to fetch the field from the database
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
        time, so on a non-UTC host every test-created create_date/write_date
        landed hours off production semantics (invisible under UTC CI).
        """
        self.assertIsInstance(self.cr, TestCursor)
        self.cr.commit()  # drop any timestamp cached during setUp
        self.assertIsNone(self.cr._now)

        t = self.cr.now()
        self.assertIsNone(t.tzinfo, "now() must be naive")
        utc_naive = datetime.now(UTC).replace(tzinfo=None)
        # 600s tolerance is generous for slow CI yet still catches the ~6h
        # local-vs-UTC skew on a non-UTC host (e.g. America/Mexico_City).
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

        fetchscalar is defined on BaseCursor while fetchone is not, so
        TestCursor forwards fetchone via __getattr__ but resolves fetchscalar
        straight to the base.  When the base body was ``raise
        NotImplementedError`` this made ``test_cursor.fetchscalar()`` raise
        under integration tests while working in production.  The base now
        implements it over self.fetchone() so every subclass inherits a
        working version.
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
        """If test cursors are retrieved independently it becomes possible for
        the savepoint operations to be interleaved (especially as some are lazy
        e.g. the request cursor, so cursors might be semantically nested but
        technically interleaved), and for them to commit one another:

        .. code-block:: sql

            SAVEPOINT A
            SAVEPOINT B
            RELEASE SAVEPOINT A
            RELEASE SAVEPOINT B -- "savepoint b does not exist"
        """
        a = self.registry.cursor()
        b = self.registry.cursor()
        # This forces the savepoint to be created
        a._check_savepoint()
        b._check_savepoint()
        # `a` should warn that it found un-closed cursor `b` when trying to close itself
        with self.assertLogs("odoo.db.cursor", level=logging.WARNING) as cm:
            a.close()
        [msg] = cm.output
        self.assertIn("WARNING:odoo.db.cursor:Found different un-closed cursor", msg)
        # avoid a warning on teardown (when self.cr finds a still on the stack)
        # as well as ensure the stack matches our expectations
        with self.assertRaises(psycopg.errors.InvalidSavepointSpecification):
            with self.assertLogs("odoo.db.cursor", level=logging.WARNING) as cm:
                b.close()

    def test_borrow_connection(self):
        """Tests the behavior of the postgresql connection pool recycling/borrowing.

        With psycopg_pool, connections are managed per-database. Each
        ``getconn()`` returns a raw psycopg.Connection wrapped in a new
        ``psycopg.Connection``, so we compare backend PIDs (the PostgreSQL
        process ID) rather than Python object identity.
        """
        cursors = []
        try:
            connection = db_connect(self.cr.dbname)

            # Case #1: 2 cursors, both opened/used, do not recycle/borrow.
            # The 2nd cursor must not use the connection of the 1st cursor as it's used (not closed).
            cursors.extend((connection.cursor(), connection.cursor()))
            # Check that both cursors got different underlying connections.
            pid0 = cursors[0].connection.info.backend_pid
            pid1 = cursors[1].connection.info.backend_pid
            self.assertNotEqual(pid0, pid1)

            # Case #2: Close 1st cursor, open 3rd cursor, must recycle/borrow.
            # The 3rd must recycle/borrow the connection of the 1st one.
            cursors[0].close()
            cursors.append(connection.cursor())
            # Check the 3rd cursor reuses the backend connection from the 1st.
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

        now() is the transaction start timestamp (snapshot isolation keeps it
        stable for the whole transaction), so _now is reset only by
        commit()/rollback(), never by savepoint churn.  assertIs proves the
        value is the same cached object, i.e. it was not recomputed.
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
        """now() returns now()==transaction_timestamp() at UTC, i.e. the
        transaction start time, not the per-statement clock_timestamp().
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

    Standalone test helper — extracted from Cursor to keep the production
    API surface minimal.
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

    def test_copy_from_empty_returning(self):
        """copy_from with empty rows and returning_ids returns empty list."""
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_cpe (id serial PRIMARY KEY, val text)")
            ids = cr.copy_from("_test_cpe", ["val"], [], returning_ids=True)
            self.assertEqual(ids, [])

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

    def test_update_without_from(self):
        qtype, table = categorize_query("UPDATE res_users SET name='x'")
        self.assertEqual(qtype, "other")
        self.assertIsNone(table)

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

        This fallback emits a RuntimeWarning by design (see
        ``TestURIMalformedWarning.test_hostname_fallback_emits_warning``
        for the assertion).  Suppress it here so the test log stays
        clean — the warning is expected and already verified elsewhere.
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


class TestNormalizeDsnKey(BaseCase):
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

    def test_pool_maxconn_rejects_non_positive(self):
        """Pool maxconn <= 0 raises instead of silently coercing to 1.

        The old max(maxconn, 1) clamp turned a misconfigured db_maxconn=0
        (or an empty db_maxconn_gevent override) into a single-slot pool
        that wedged the server under trivial load.  Fail fast instead.
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

        # The dead pool must have been removed from _pools
        self.assertNotIn(key, pool._pools)
        # And close() must have been called on it
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

        # Pool should still be in _pools for non-timeout errors
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
        # Build a minimal registry shell and inject it into the LRU.
        # No real DB needed — we mock the cursor to simulate failure.
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

        # The stale registry must have been removed from the LRU
        self.assertNotIn(self.DB_NAME, Registry.registries)

    def test_check_signaling_cleans_up_after_pool_error(self):
        """check_signaling() must also handle PoolError (raised by borrow()
        when the pool times out, e.g. after a database drop).
        """
        reg = object.__new__(Registry)
        reg.db_name = self.DB_NAME
        reg._db_readonly = None
        Registry.registries[self.DB_NAME] = reg
        self.addCleanup(Registry.delete, self.DB_NAME)

        with patch.object(
            type(reg),
            "cursor",
            side_effect=PoolError("couldn't get a connection after 30.00 sec"),
        ):
            with self.assertRaises(PoolError):
                reg.check_signaling()

        self.assertNotIn(self.DB_NAME, Registry.registries)

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
    """_FlushingSavepoint must not leak savepoint_depth if the SAVEPOINT SQL
    raises — otherwise the next commit/rollback hits the ``savepoint_depth
    == 0`` assertion and wedges the transaction.
    """

    def test_savepoint_depth_unchanged_on_sql_failure(self):
        class BrokenCursor(MagicMock):
            pass

        txn = MagicMock()
        txn.savepoint_depth = 0
        txn.default_env = "env"
        txn.registry.registry_sequence = 0

        cr = MagicMock()
        cr.transaction = txn
        cr.flush = MagicMock()
        cr.execute = MagicMock(
            side_effect=psycopg.OperationalError("simulated broken connection")
        )

        with self.assertRaises(psycopg.OperationalError):
            _FlushingSavepoint(cr)

        # Depth must remain at 0 — no leaked counter for a savepoint that
        # never actually made it to the server.
        self.assertEqual(
            txn.savepoint_depth, 0, "savepoint_depth leaked after SAVEPOINT SQL failure"
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


class TestNormalizeDsnKeyPassword(BaseCase):
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
    """``exp_drop`` must call ``odoo.db.close_db`` twice — once to flush
    pools before ``DROP DATABASE`` and once after, because cron and
    HTTP threads can re-create a pool for the target database in the
    brief window between the first close and the DROP statement.
    Without the second close, those new pools would later try to
    reconnect to a database that no longer exists.

    This invariant is load-bearing (inherited from upstream) and had
    no regression coverage — any refactor of ``exp_drop`` that collapsed
    the two close_db calls into one would silently break production
    under concurrent load.
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

        # Note: not patching odoo.tools.config.filestore — exp_drop guards
        # the rmtree with ``if Path(fs).exists()`` and the fake_db name
        # was never used by any real Odoo, so the path doesn't exist and
        # the rmtree branch is skipped harmlessly.
        # database_identifier() requires a real psycopg connection to
        # quote names, so stub it with a static SQL fragment for the test.
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
        from odoo.db.cursor import _column_type_cache

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
        with registry().cursor() as cr:
            cr.execute("CREATE TEMP TABLE _test_seqkey (id serial PRIMARY KEY, v text)")
            try:
                cr.copy_from("_test_seqkey", ["v"], [("x",)], returning_ids=True)
                self.assertIn((cr.dbname, "_test_seqkey"), _id_sequence_cache)
            finally:
                _id_sequence_cache.pop((cr.dbname, "_test_seqkey"), None)

    def test_clear_schema_caches_per_db(self):
        from odoo.db.cursor import _clear_schema_caches, _column_type_cache

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
        from odoo.db.cursor import _column_type_cache

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


class TestDrainDb(BaseCase):
    """drain_db must clear schema caches for one database only."""

    def test_drain_db_clears_caches_for_db_only(self):
        from odoo.db import drain_db
        from odoo.db.cursor import _column_type_cache

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

    NB: the guard reads ``cr.transaction.savepoint_depth`` — a bare
    ``registry().cursor()`` has ``transaction = None`` (only Environment
    creation attaches one), so the guard never fires on it and commit()
    would really COMMIT, destroying the savepoint.  Attach a stub
    transaction so the depth bookkeeping (and the guard) engage.
    """

    class _StubTransaction:
        """Minimal Transaction stand-in for _FlushingSavepoint bookkeeping."""

        def __init__(self):
            self.savepoint_depth = 0
            self.default_env = None
            self.registry = MagicMock(registry_sequence=1)
            self.envs = []

        def flush(self):
            pass

        def clear(self):
            pass

        def reset(self):
            pass

    def test_commit_inside_savepoint_raises(self):
        with registry().cursor() as cr:
            cr.transaction = self._StubTransaction()
            try:
                with self.assertRaises(RuntimeError):
                    with cr.savepoint():
                        cr.commit()
                # guard fired BEFORE the SQL COMMIT: the savepoint unwound
                # cleanly and the depth counter is balanced
                self.assertEqual(cr.transaction.savepoint_depth, 0)
            finally:
                cr.transaction = None

    def test_rollback_inside_savepoint_raises(self):
        with registry().cursor() as cr:
            cr.transaction = self._StubTransaction()
            try:
                with self.assertRaises(RuntimeError):
                    with cr.savepoint():
                        cr.rollback()
                self.assertEqual(cr.transaction.savepoint_depth, 0)
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
                self.savepoint_depth = 0

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


class TestUninitializedCursorClosed(BaseCase):
    """An instance that failed before __init__ set _closed must read as
    closed (class-level default) instead of recursing in __getattr__."""

    def test_uninitialized_cursor_raises_interface_error(self):
        cur = object.__new__(Cursor)
        with self.assertRaises(psycopg.InterfaceError):
            cur.some_attribute  # noqa: B018 — attribute access is the test


class TestNormalizeDsnKeyUriExpansion(BaseCase):
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
        src = inspect.getsource(ConnectionPool.borrow)
        self.assertIn("server_version", src)
        self.assertIn("MIN_PG_VERSION", src)


class TestPsycopgPoolPrivateApi(BaseCase):
    """Pin the private psycopg APIs this package depends on, so a psycopg /
    psycopg_pool upgrade that drops them fails here instead of in
    production: give_back() reads conn._pool (set by psycopg_pool.getconn),
    execute() clears conn._prepared after DDL."""

    def test_conn_pool_attribute_set_by_getconn(self):
        with registry().cursor() as cr:
            self.assertIsNotNone(getattr(cr._cnx, "_pool", None))

    def test_connection_prepared_attribute_exists(self):
        with registry().cursor() as cr:
            self.assertTrue(hasattr(cr._cnx, "_prepared"))


class TestConnectErrorTranslation(BaseCase):
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


class TestSchemaCacheClearConcurrency(BaseCase):
    """_clear_schema_caches() iterates the module-global schema cache while
    copy_from() populates it from other threads.  Iterating a live dict while
    another thread inserts raises 'dictionary changed size during iteration'.
    The fix snapshots the keys via list(cache) before filtering.
    """

    def test_clear_does_not_race_concurrent_populate(self):
        from odoo.db.cursor import _clear_schema_caches

        cache = _id_sequence_cache
        cache.clear()
        self.addCleanup(cache.clear)
        errors = []
        stop = threading.Event()

        def populate():
            i = 0
            while not stop.is_set():
                cache[("otherdb", f"t{i}")] = "seq"
                i += 1
                if i % 5000 == 0:
                    cache.clear()

        def clear_loop():
            while not stop.is_set():
                try:
                    _clear_schema_caches("targetdb")
                except RuntimeError as e:
                    errors.append(str(e))
                    return

        threads = [
            threading.Thread(target=populate),
            threading.Thread(target=clear_loop),
        ]
        for t in threads:
            t.start()
        time.sleep(1.0)
        stop.set()
        for t in threads:
            t.join()

        self.assertEqual(
            errors, [], "_clear_schema_caches raced the cache dict — fix regressed"
        )


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
    """DDL detection reads the first non-space chars; the fix bounds lstrip()
    to the first 64 chars (avoiding a full-query copy on the hot path).  DDL
    that begins after leading whitespace (Odoo's triple-quoted SQL) must still
    be detected so its params are inlined client-side — otherwise psycopg sends
    $1 which PostgreSQL rejects in a DEFAULT expression.
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


class TestResetConnectionLeavesSessionGuc(BaseCase):
    """_reset_connection (the pool's return hook) resets ONLY
    autocommit/isolation_level/read_only and the prepared-statement tuning —
    never arbitrary session GUCs.  A plain ``SET search_path`` therefore
    survives the pool return and leaks to the next borrower; callers needing
    short-lived overrides must use ``SET LOCAL``.  This pins the documented
    contract so a future ``RESET ALL`` in _reset_connection does not silently
    change it (the ODOO_FAKETIME_TEST_MODE path in Cursor.__init__ relies on
    a session SET persisting across rollback).
    """

    def test_session_set_survives_reset_local_does_not(self):
        cr = db_connect(common.get_db_name()).cursor()
        try:
            conn = cr.connection
            cr.execute("SET search_path = pg_catalog")
            cr.commit()  # close the txn so the SESSION-level SET sticks
            _reset_connection(conn)  # the pool's return hook — no open txn here
            cr.execute("SHOW search_path")
            self.assertEqual(
                cr.fetchscalar(),
                "pg_catalog",
                "_reset_connection reset a session GUC — the documented leak "
                "contract changed (was a RESET ALL added?)",
            )
            # Contrast: SET LOCAL is transaction-scoped and must NOT persist.
            cr.execute("SET LOCAL search_path = information_schema")
            cr.rollback()
            cr.execute("SHOW search_path")
            self.assertEqual(cr.fetchscalar(), "pg_catalog")
        finally:
            # Hygiene: never return a connection with a mutated search_path to
            # the shared pool — the next borrower (another test) would inherit
            # it.  This is exactly the leak the test documents.
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


class TestInlineDdlParams(BaseCase):
    """_inline_ddl_params splices params into DDL as client-side quoted
    literals (DDL rejects server-side $N parameters).  Extracted from
    Cursor.execute() so the %%-escape-aware splice — the trickiest bit of
    the cursor — is unit-testable without a DDL round-trip.  ``quote`` runs
    with a null adapter context, so these need no database connection.
    """

    def test_positional_inlines_and_quotes(self):
        self.assertEqual(_inline_ddl_params("DEFAULT %s", (7,), None), "DEFAULT 7")
        # strings are single-quoted and internal quotes doubled
        self.assertEqual(
            _inline_ddl_params("c = %s", ("o'reilly",), None), "c = 'o''reilly'"
        )

    def test_named_dict_params(self):
        self.assertEqual(_inline_ddl_params("a = %(x)s", {"x": "v"}, None), "a = 'v'")

    def test_literal_percent_is_unescaped_around_marker(self):
        # `%%` is a literal percent, not a marker; it must survive as a single
        # `%`, while the real `%s` is replaced.  Naive `qs % params` raises here.
        self.assertEqual(
            _inline_ddl_params("IS '50%% done' DEFAULT %s", ("v",), None),
            "IS '50% done' DEFAULT 'v'",
        )

    def test_double_percent_only_no_marker(self):
        self.assertEqual(
            _inline_ddl_params("COMMENT IS '100%% sure'", (), None),
            "COMMENT IS '100% sure'",
        )

    def test_marker_count_mismatch_raises(self):
        with self.assertRaises(ValueError):
            _inline_ddl_params("%s %s", ("only-one",), None)
        with self.assertRaises(ValueError):
            _inline_ddl_params("DEFAULT %s", (1, 2), None)

    def test_multiple_positional_in_order(self):
        self.assertEqual(
            _inline_ddl_params("(%s, %s, %s)", (1, 2, 3), None), "(1, 2, 3)"
        )


class TestFindValueMarkers(BaseCase):
    """_find_value_markers locates real ``%s`` placeholders and skips ``%%``
    escapes — the escape-aware scan that execute_values and _inline_ddl_params
    both rely on.  A naive str.count/replace would mis-handle ``%%s``.
    """

    def test_basic_and_escapes(self):
        self.assertEqual(_find_value_markers("%s and %s"), [0, 7])
        # %% is a literal percent, not a marker
        self.assertEqual(_find_value_markers("LIKE 'a%%s'"), [])
        # the space at index 11 means the second marker starts at 12, not 11
        self.assertEqual(_find_value_markers("x %s y %% z %s"), [2, 12])
        self.assertEqual(_find_value_markers("%%"), [])
        self.assertEqual(_find_value_markers("ends %s"), [5])


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


class TestCopyFromMetricsQueryLazy(BaseCase):
    """copy_from renders the COPY statement to text for metrics ONLY when a
    thread query hook will consume it; otherwise it passes ``query=None`` to
    skip a wasted SQL render on every bulk insert (copy_from is a hot path).
    """

    def test_no_hook_passes_none(self):
        captured = {}
        orig = Cursor._record_metrics

        def spy(self, delay, count=1, *, query=None, params=None, start=0.0):
            captured["query"] = query
            return orig(self, delay, count, query=query, params=params, start=start)

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


class TestBorrowPoolGuardExplicitRaise(BaseCase):
    """borrow()'s `_pool` back-reference guard must use an explicit raise, not
    `assert`.  It protects the _pool_sem accounting invariant whose failure
    mode is a slow production hang — give_back() would take its non-pool branch
    and leak a permit on every return — exactly the deployment where
    ``python -O`` (which strips asserts) is plausible.  Mirrors
    TestDictFetchoneNoAssert / TestSavepointGuardsSurviveOptimize for the pool.
    """

    def test_guard_uses_explicit_raise_not_assert(self):
        src = inspect.getsource(ConnectionPool.borrow)
        self.assertNotIn(
            'assert getattr(conn, "_pool"',
            src,
            "borrow() must guard the _pool invariant with an explicit raise "
            "(assert is stripped by python -O)",
        )
        self.assertIn(
            'if getattr(conn, "_pool", None) is None:',
            src,
            "borrow() must explicitly check the _pool back-reference",
        )

    def test_untagged_conn_raises_and_releases_semaphore(self):
        pool = ConnectionPool(maxconn=4)
        info = connection_info_for("nonexistent_db_test")[1]
        key = _normalize_dsn_key(info)

        # A connection psycopg_pool failed to tag with a `_pool` back-reference
        # (the future-driver scenario the guard defends).  borrow() must reject
        # it loudly AND release the permit it acquired before getconn().
        conn = MagicMock()
        conn._pool = None
        conn.info.server_version = 180000  # would otherwise pass the version gate
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
            "semaphore leaked when borrow() rejected an untagged connection",
        )


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
