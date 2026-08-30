import ast
import inspect
import pathlib
import textwrap
import unittest

import psycopg

from odoo.db import (
    breaker,
    bulk,
    cursor,
    ddl,
    dsn,
    endpoints,
    errors,
    lag,
    leaks,
    pool,
    probe,
    schema_cache,
)

_DB_PACKAGE = pathlib.Path(pool.__file__).parent


def _callees(func) -> set[str]:
    # unwrap first: a @contextmanager's attribute is contextlib's helper, and
    # its co_names are contextlib's rather than the decorated function's.
    return set(inspect.unwrap(func).__code__.co_names)


def _calls_on(func, receiver: str) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if (
            isinstance(owner, ast.Attribute)
            and owner.attr == receiver
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"
        ):
            found.add(node.func.attr)
    return found


def _instance_attrs(cls) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    found = set()
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for t in targets:
            if (
                isinstance(t, ast.Attribute)
                and isinstance(t.value, ast.Name)
                and t.value.id == "self"
            ):
                found.add(t.attr)
    return found


def _methods_calling(cls, name: str) -> set[str]:
    found = set()
    for attr in dir(cls):
        member = inspect.getattr_static(cls, attr, None)
        member = getattr(member, "__func__", member)
        code = getattr(member, "__code__", None)
        if code is not None and name in code.co_names:
            found.add(attr)
    return found


class TestBudgetAccounting(unittest.TestCase):
    def test_only_the_borrow_paths_acquire_a_permit(self):
        acquirers = {
            m
            for m in _methods_calling(pool.ConnectionPool, "acquire")
            if not m.startswith("__")
        }
        self.assertEqual(acquirers, {"borrow", "_borrow_direct"})

    def test_exactly_one_release_site_per_outcome(self):
        releasers = {
            m
            for m in _methods_calling(pool.ConnectionPool, "release")
            if not m.startswith("__")
        }
        self.assertEqual(
            releasers,
            {"give_back", "_unwind_failed_borrow"},
            "a borrow ends exactly two ways and each has one release site: "
            "give_back for a connection that reached the caller, "
            "_unwind_failed_borrow for one that did not. They used to be three "
            "-- borrow and _borrow_direct released inline -- which is how the "
            "post-acquisition bookkeeping ended up outside the guard and "
            "leaked a permit per failure.",
        )

    def test_the_getconn_helpers_never_touch_the_budget(self):
        for helper in ("_getconn_with_retry", "_validate_borrowed_conn"):
            with self.subTest(helper=helper):
                self.assertNotIn(
                    "_budget", _callees(getattr(pool.ConnectionPool, helper))
                )


class TestStalePlanIsRetriedAtTheRequestLayer(unittest.TestCase):
    def test_the_one_failure_seam_marks_it(self):
        self.assertIn(
            "_note_stale_cached_plan",
            _callees(cursor.Cursor._statement_failed),
            "nothing else can tell a recoverable 0A000 from a permanent one",
        )

    def test_every_statement_entry_point_routes_through_that_seam(self):
        import inspect as _inspect

        for owner, name in (
            (cursor.Cursor, "execute"),
            (cursor.Cursor, "executemany"),
            (cursor.Cursor, "copy"),
            (bulk._BulkAccessMixin, "copy_from"),
        ):
            fn = _inspect.unwrap(getattr(owner, name))
            for seam in ("_statement_failed", "_statement_done"):
                with self.subTest(entry_point=name, seam=seam):
                    self.assertIn(
                        seam,
                        fn.__code__.co_names,
                        "each entry point used to carry its own copy of the "
                        "envelope: executemany's had dropped the stale-plan "
                        "mark, copy_from's the failed-statement count, and "
                        "cr.copy()'s the timing and the error log entirely",
                    )

    def test_the_marker_requires_prepared_statements(self):
        src = inspect.getsource(cursor.Cursor._note_stale_cached_plan)
        self.assertIn("_prepared", src)
        self.assertIn("_names", src)
        self.assertIn(
            "PG_STALE_PLAN_EXCEPTIONS",
            src,
            "the family must come from errors.py, not be re-listed here",
        )

    def test_it_clears_the_plans_so_the_retry_re_prepares(self):
        """Behavioural, because the call it used to grep for moved.

        This asserted `"clear()" in src`, which stopped being true when the
        three copies of the `_prepared` contract were unified behind
        `lifecycle.clear_prepared_cache`. The property was never about the
        spelling: what matters is that the marker empties the cache, so the
        replay `service.transaction.retrying` performs re-prepares against the
        new plan instead of reusing the stale one.
        """

        class _Prepared:
            def __init__(self):
                self._names = {"_pg3_0": b"stmt"}

            def clear(self):
                self._names.clear()

        class _Cnx:
            def __init__(self):
                self._prepared = _Prepared()

        cr = cursor.Cursor.__new__(cursor.Cursor)
        cr._cnx = _Cnx()
        cr._schema_cache = schema_cache.TransactionSchemaCache()
        cr._schema_cache.set_id_sequence("t", "t_id_seq")

        exc = psycopg.errors.FeatureNotSupported("cached plan must not change")
        self.assertTrue(cr._note_stale_cached_plan(exc))
        self.assertFalse(
            cr._cnx._prepared._names, "the cache must be empty after the mark"
        )
        self.assertIsNone(
            cr._schema_cache.get_id_sequence("t"),
            "catalog facts learned under the old plan must go too",
        )
        self.assertTrue(errors.is_stale_cached_plan(exc))

    def test_the_marker_issues_no_sql(self):
        src = inspect.getsource(cursor.Cursor._note_stale_cached_plan)
        self.assertNotIn(
            "DEALLOCATE",
            src,
            "the transaction is already aborted here; issuing SQL would raise "
            "InFailedSqlTransaction on top of the error being reported",
        )
        self.assertNotIn("self.execute", src)

    def test_the_family_is_exported_for_the_request_layer(self):
        from odoo.db import errors as err

        self.assertTrue(err.PG_STALE_PLAN_EXCEPTIONS)
        self.assertTrue(callable(err.is_stale_cached_plan))


class TestAFailedBorrowNeverKeepsItsPermit(unittest.TestCase):
    def _borrow_body(self):
        return textwrap.dedent(inspect.getsource(pool.ConnectionPool.borrow))

    def test_the_bookkeeping_is_inside_the_guard(self):
        tree = ast.parse(self._borrow_body())
        fn = tree.body[0]
        guarded = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Try):
                for sub in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if isinstance(sub, ast.Call) and isinstance(
                        sub.func, ast.Attribute
                    ):
                        guarded.add(sub.func.attr)
        for name in ("track", "_warn_about_leaks", "record_borrow"):
            with self.subTest(call=name):
                self.assertIn(
                    name,
                    guarded,
                    f"{name}() runs outside the try that releases the permit; "
                    f"if it raises, the permit and the connection are gone for "
                    f"the life of the process",
                )

    def test_nothing_follows_the_guard(self):
        fn = ast.parse(self._borrow_body()).body[0]
        self.assertIsInstance(
            fn.body[-1],
            ast.Try,
            "borrow must end with the guarded block; a statement after it is "
            "by definition outside the release path",
        )

    def test_both_paths_unwind_through_one_helper(self):
        for path in ("borrow", "_borrow_direct"):
            with self.subTest(path=path):
                self.assertIn(
                    "_unwind_failed_borrow",
                    _callees(getattr(pool.ConnectionPool, path)),
                )

    def test_the_unwind_distinguishes_a_marked_connection(self):
        src = inspect.getsource(pool.ConnectionPool._unwind_failed_borrow)
        self.assertIn("_odoo_pool", src)
        self.assertIn("give_back", src)
        self.assertIn("release", src)


class TestMaintenanceDatabasesAreNeverPooled(unittest.TestCase):
    def test_borrow_consults_is_maintenance_db_and_diverts(self):
        names = _callees(pool.ConnectionPool.borrow)
        self.assertIn("is_maintenance_db", names)
        self.assertIn("_borrow_direct", names)

    def test_give_back_recognises_the_direct_marker(self):
        self.assertIn("_DIRECT_CONNECTION", _callees(pool.ConnectionPool.give_back))


class TestPasswordNeverReachesAPoolKey(unittest.TestCase):
    SECRET = "s3cr3t-do-not-log"

    def _assert_absent(self, key):
        self.assertNotIn(self.SECRET, repr(key))
        self.assertNotIn(self.SECRET, str(dict(key)))

    def test_keyword_password_is_fingerprinted(self):
        key = dsn._normalize_dsn_key({"dbname": "d", "password": self.SECRET})
        self._assert_absent(key)
        self.assertIn("password_fp", dict(key))

    def test_uri_embedded_password_is_fingerprinted(self):
        key = dsn._normalize_dsn_key({"dsn": f"postgresql://u:{self.SECRET}@h/d"})
        self._assert_absent(key)

    def test_a_rotated_password_changes_the_key(self):
        base = {"dbname": "d", "user": "u"}
        first = dsn._normalize_dsn_key({**base, "password": "one"})
        second = dsn._normalize_dsn_key({**base, "password": "two"})
        self.assertNotEqual(first, second, "rotation must not reuse the cached pool")

    def test_the_fingerprint_is_stable_for_one_password(self):
        made = {"dbname": "d", "password": self.SECRET}
        self.assertEqual(dsn._normalize_dsn_key(made), dsn._normalize_dsn_key(made))


class TestEveryDsnConsumerExpandsConninfo(unittest.TestCase):
    def test_conninfo_to_dict_is_imported_only_by_dsn(self):
        importers = []
        for path in sorted(_DB_PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                names: tuple[str, ...] = ()
                if isinstance(node, ast.ImportFrom):
                    names = tuple(a.name for a in node.names)
                if "conninfo_to_dict" in names:
                    importers.append(path.name)
        self.assertEqual(importers, ["dsn.py"])


class TestLibpqTimeoutNeverLeaksZero(unittest.TestCase):
    """libpq reads `connect_timeout=0` as "wait forever", not "give up now".

    The helper and two of its three call sites moved to `probe.py` with the
    reachability prober; `_borrow_direct` kept the third. The guard is a
    property of every call site wherever it lives, so this scans both modules
    rather than whichever one happens to hold the function today.
    """

    def test_it_returns_zero_or_at_least_one_never_between(self):
        now = probe.monotonic()
        for offset in (-5, -1, -0.5, 0, 0.2, 0.9, 1.0, 1.5, 3, 10, 900):
            with self.subTest(offset=offset):
                got = probe.libpq_connect_timeout(now + offset, 5)
                self.assertTrue(
                    got == 0 or got >= 1, f"{got} would be read as 'wait forever'"
                )
                self.assertLessEqual(got, 5, "must never exceed the cap")

    def test_no_deadline_passes_the_cap_through(self):
        self.assertEqual(probe.libpq_connect_timeout(None, 5), 5)

    def test_every_call_site_guards_the_zero(self):
        guarded = 0
        skip_tests = 0
        for module in (pool, probe):
            source = inspect.getsource(module)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    fn = node.value.func
                    if getattr(fn, "id", None) == "libpq_connect_timeout":
                        guarded += 1
            skip_tests += source.count("if not probe_timeout")
            skip_tests += source.count("if not connect_timeout")
        self.assertGreaterEqual(
            guarded, 3, "call sites must bind the result so they can test it"
        )
        self.assertEqual(
            skip_tests,
            guarded,
            "every libpq_connect_timeout result must be tested for the skip case",
        )


class TestSchemaCacheClearsHaveDistinctCallSites(unittest.TestCase):
    def test_ddl_invalidation_keeps_the_lock_ledger(self):
        self.assertEqual(
            _calls_on(cursor.Cursor.discard_cached_plans, "_schema_cache"),
            {"clear_catalog_facts"},
            "DDL does not end the transaction, so the ROW EXCLUSIVE lock this "
            "cursor already took is still held",
        )

    def test_transaction_boundaries_and_savepoint_rollback_clear_everything(self):
        for method in ("commit", "_do_rollback", "_on_rollback_to_savepoint"):
            with self.subTest(method=method):
                self.assertEqual(
                    _calls_on(getattr(cursor.Cursor, method), "_schema_cache"),
                    {"clear"},
                )

    def test_both_clears_exist_and_differ(self):
        cache = schema_cache.TransactionSchemaCache()
        self.assertNotEqual(
            inspect.getsource(cache.clear_catalog_facts),
            inspect.getsource(cache.clear),
        )


class TestDdlDetectionCannotMissAHiddenStatement(unittest.TestCase):
    HIDDEN = (
        "BEGIN; ALTER TABLE t ADD COLUMN c int; COMMIT",
        "SELECT 1; CREATE TABLE t (a int)",
        "SET x = 1; DROP TABLE t",
        "SELECT 1;\n  ALTER TABLE t DROP COLUMN c",
        "SELECT 1; DO $$ BEGIN END $$",
    )
    INNOCENT = (
        "SELECT * FROM t",
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a = 1",
        "SELECT 'CREATE TABLE' AS label",
    )

    def test_hidden_ddl_is_reported(self):
        for qs in self.HIDDEN:
            with self.subTest(qs=qs):
                self.assertTrue(ddl._changes_schema(qs, ddl._ddl_keyword(qs)))

    def test_ordinary_statements_are_not(self):
        for qs in self.INNOCENT:
            with self.subTest(qs=qs):
                self.assertFalse(ddl._changes_schema(qs, ddl._ddl_keyword(qs)))

    def test_over_reporting_is_the_only_allowed_error(self):
        qs = "SELECT 'a;CREATE' FROM t"
        self.assertTrue(
            ddl._changes_schema(qs, ddl._ddl_keyword(qs)),
            "a semicolon in a literal may over-report; that costs a cache drop, "
            "which is safe, and is the documented direction of the trade",
        )


class TestCursorSatisfiesItsMixinContracts(unittest.TestCase):
    def _protocol_members(self, name):
        source = inspect.getsource(bulk)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                return {n.name for n in node.body if isinstance(n, ast.FunctionDef)} | {
                    t.target.id
                    for t in node.body
                    if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)
                }
        raise AssertionError(f"{name} not found in odoo.db.bulk")

    def test_cursor_provides_every_bulk_host_member(self):
        required = self._protocol_members("_CursorInternals")
        self.assertTrue(required, "the Protocol declared nothing — check the parse")
        provided = (
            set(dir(cursor.Cursor))
            | set(cursor.Cursor.__annotations__)
            | _instance_attrs(cursor.Cursor)
            | _instance_attrs(cursor.BaseCursor)
        )
        self.assertEqual(sorted(required - provided), [])


class TestSchemaChangeDrainsAtCommit(unittest.TestCase):
    def test_ddl_arms_the_flag_rather_than_draining_inline(self):
        src = inspect.getsource(cursor.Cursor._invalidate_caches_after_ddl)
        self.assertIn("_schema_changed", src)
        self.assertNotIn(
            "_drain_sibling_connections",
            src,
            "draining per statement closes and reopens every idle connection "
            "once per DDL statement — ~1000 times during a module install — "
            "and an uncommitted schema change is invisible to the connections "
            "it would be healing.",
        )

    def test_commit_is_the_only_thing_that_drains(self):
        self.assertIn(
            "_drain_sibling_connections",
            _callees(cursor.Cursor.commit),
            "commit is the moment the schema change becomes visible to other "
            "connections, so it is the moment they must be drained",
        )
        for name in ("_do_rollback", "_on_rollback_to_savepoint", "_close"):
            with self.subTest(method=name):
                self.assertNotIn(
                    "_drain_sibling_connections",
                    _callees(getattr(cursor.Cursor, name)),
                    f"{name} must not drain: nothing it undoes ever became "
                    f"visible to another connection",
                )

    def test_rollback_disarms_the_flag(self):
        self.assertIn(
            "_schema_changed",
            _instance_attrs(cursor.Cursor),
            "the flag must be reset on rollback, or a rolled-back schema "
            "change drains on the next unrelated commit",
        )
        self.assertIn("_schema_changed", inspect.getsource(cursor.Cursor._do_rollback))


class TestOneConnectionOptionsAssembler(unittest.TestCase):
    def test_both_borrow_paths_use_it(self):
        for path in ("_get_or_create_pool", "_borrow_direct"):
            with self.subTest(path=path):
                self.assertIn(
                    "_connection_options",
                    _callees(getattr(pool.ConnectionPool, path)),
                    "the two paths built the same libpq options string twice; "
                    "one assembler, or the exemption goes back to being an "
                    "accident nobody can see.",
                )

    def test_the_assembler_renders_the_session_gucs_by_default(self):
        self.assertIn("_session_gucs", _callees(pool._connection_options))
        self.assertIn(
            "-c idle_session_timeout=",
            inspect.getsource(pool._connection_options),
        )

    def test_only_the_maintenance_path_opts_out(self):
        self.assertIn(
            "session_gucs=False",
            inspect.getsource(pool.ConnectionPool._borrow_direct),
        )
        self.assertNotIn(
            "session_gucs",
            inspect.getsource(pool.ConnectionPool._get_or_create_pool),
        )


class TestEveryCheckoutIsTracked(unittest.TestCase):
    def test_both_borrow_paths_track(self):
        for path in ("borrow", "_borrow_direct"):
            with self.subTest(path=path):
                self.assertIn(
                    "track",
                    _calls_on(getattr(pool.ConnectionPool, path), "_checkouts"),
                )

    def test_give_back_releases(self):
        self.assertIn("release", _calls_on(pool.ConnectionPool.give_back, "_checkouts"))

    def test_give_back_releases_before_it_can_return_early(self):
        tree = ast.parse(
            textwrap.dedent(inspect.getsource(pool.ConnectionPool.give_back))
        )
        release_lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "release"
            and getattr(node.func.value, "attr", None) == "_checkouts"
        ]
        return_lines = [
            node.lineno for node in ast.walk(tree) if isinstance(node, ast.Return)
        ]
        self.assertTrue(release_lines, "give_back never releases the checkout")
        self.assertTrue(return_lines, "give_back has no early exit to guard")
        self.assertLess(min(release_lines), min(return_lines))

    def test_the_leak_warning_uses_its_own_throttle(self):
        names = _callees(pool.ConnectionPool._warn_about_leaks)
        self.assertIn("due_for_report", names)
        self.assertNotIn(
            "_reaper",
            names,
            "sharing the reaper's slot would let a leak warning silence a sweep",
        )

    def test_saturation_errors_name_the_holders(self):
        self.assertIn(
            "describe",
            _calls_on(pool.ConnectionPool._budget_exhausted, "_checkouts"),
            "a budget-exhausted error must say who is holding the permits",
        )

    def test_both_borrow_paths_raise_the_one_saturation_error(self):
        for path in ("borrow", "_borrow_direct"):
            with self.subTest(path=path):
                self.assertIn(
                    "_budget_exhausted",
                    _callees(getattr(pool.ConnectionPool, path)),
                    "the two copies of this message had already drifted apart; "
                    "a path that builds its own can drop the holders again",
                )


class TestBudgetBelongsToAServer(unittest.TestCase):
    """The registry moved out of `odoo/db/__init__.py` into `EndpointRegistry`.

    These pin the keying, not where it lives, so they follow it to the class.
    """

    def test_the_key_is_the_resolved_endpoint(self):
        names = _callees(endpoints.EndpointRegistry.budget_for)
        self.assertIn("endpoint_of", names)
        self.assertNotIn(
            "db_replica_host",
            names,
            "keying on 'is a replica configured' hands one server two budgets "
            "whenever the replica resolves back to the primary",
        )

    def test_the_endpoint_comes_from_the_resolved_connection_info(self):
        self.assertIn(
            "connection_info_for", _callees(endpoints.EndpointRegistry.endpoint_of)
        )

    def test_the_replica_ceiling_is_gated_on_the_endpoint_differing(self):
        self.assertIn("endpoint_of", _callees(endpoints.EndpointRegistry.maxconn_for))

    def test_budgets_are_kept_per_endpoint_not_as_one_global(self):
        registry = endpoints.EndpointRegistry()
        self.assertIsInstance(registry._budgets, dict)
        self.assertFalse(
            hasattr(registry, "_budget"),
            "the single process-wide budget was replaced by a per-endpoint map",
        )

    def test_the_package_no_longer_carries_the_registry_as_module_state(self):
        import odoo.db as package

        for gone in ("_pools", "_budgets", "_pool_lock"):
            with self.subTest(name=gone):
                self.assertFalse(
                    hasattr(package, gone),
                    "the registry is an object so a test can build an isolated "
                    "one; leaving the globals behind keeps the old seam alive",
                )
        self.assertIsInstance(package.registry, endpoints.EndpointRegistry)


class TestPipelineModeCannotBypassTheFailureSeam(unittest.TestCase):
    def test_the_pipeline_exit_routes_the_deferred_error_through_the_seam(self):
        self.assertIn(
            "_statement_failed",
            _callees(cursor.Cursor.pipeline),
            "the ExitStack exit is where psycopg finally raises a pipelined "
            "statement's error; nothing else can hand it to the seam",
        )

    def test_it_only_takes_errors_that_reached_the_server(self):
        self.assertIn(
            "reached_the_server",
            _callees(cursor.Cursor.pipeline),
            "the same except also sees whatever the caller's block raised; a "
            "plain Python error carries no SQLSTATE and is not the seam's",
        )

    def test_only_the_outermost_block_hooks_the_sync(self):
        fn = ast.parse(
            textwrap.dedent(inspect.getsource(inspect.unwrap(cursor.Cursor.pipeline)))
        ).body[0]
        nested = next(node for node in fn.body if isinstance(node, ast.If))
        self.assertNotIn(
            "_statement_failed",
            {
                node.func.attr
                for node in ast.walk(nested)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            },
            "a nested block syncs nothing, so it can observe no deferred error",
        )

    def test_the_seam_short_circuits_before_it_does_any_work(self):
        fn = ast.parse(
            textwrap.dedent(inspect.getsource(cursor.Cursor._statement_failed))
        ).body[0]
        body = [n for n in fn.body if not isinstance(n, ast.Expr)]
        self.assertIsInstance(
            body[0],
            ast.If,
            "the idempotence check must be the first thing the seam does",
        )
        self.assertIsInstance(
            body[0].test,
            ast.Call,
            "the guard must be the bare question, not a condition that can be "
            "disabled beside it",
        )
        self.assertEqual(
            getattr(body[0].test.func, "id", None),
            "is_handled_by_seam",
            "the guard must be the bare question, not a condition that can be "
            "disabled beside it",
        )
        self.assertIsInstance(
            body[0].body[-1], ast.Return, "the check must actually short-circuit"
        )
        self.assertIn(
            "mark_handled_by_seam",
            _callees(cursor.Cursor._statement_failed),
            "a seam that never marks can never short-circuit",
        )

    def test_execute_values_hands_its_own_failures_to_the_seam(self):
        called = _callees(bulk._BulkAccessMixin.execute_values)
        self.assertIn("_statement_failed", called)
        self.assertNotIn(
            "_log_sql_error",
            called,
            "logging alone was a third of the seam: it left the stale-plan "
            "mark off every pipelined execute_values, and the ORM's bulk "
            "writers reach this path",
        )
        self.assertIn(
            "reached_the_server",
            called,
            "a client-side rejection never reached the wire and is not the "
            "seam's, as in Cursor.pipeline",
        )


class TestASavepointIsNeverOpenedInsideAPipeline(unittest.TestCase):
    """A queued ROLLBACK TO SAVEPOINT is discarded with the rest of the batch.

    Measured on a live cursor: the same UniqueViolation under the same
    savepoint left the transaction usable outside a pipeline and
    `InFailedSqlTransaction` inside one -- silently, because the caller's
    `except` ran exactly as written.
    """

    def test_savepoint_refuses_pipeline_mode(self):
        src = inspect.getsource(cursor.BaseCursor.savepoint)
        self.assertIn("in_pipeline", src)
        self.assertIn("RuntimeError", src)

    def test_it_asks_through_getattr_so_a_test_cursor_forwards(self):
        self.assertIn(
            "getattr",
            _callees(cursor.BaseCursor.savepoint),
            "odoo.tests.cursor.TestCursor forwards by __getattr__, which runs "
            "only for names the class does not have: a BaseCursor default "
            "would answer False for a test cursor that is pipelining",
        )

    def test_the_refusal_matches_the_precedent_copy_from_set(self):
        self.assertIn("in_pipeline", inspect.getsource(bulk._validate_copy_args))


class TestEveryFailedBorrowIsCounted(unittest.TestCase):
    """Both borrow paths end in one guard, and that guard counts.

    `_borrow_direct` used to have four exits and only the last of them called
    `record_borrow_failed`, so `borrows_failed` read 0 for a maintenance
    endpoint refusing every connect while the pooled path counted the same
    failure as 1. `db_connect("postgres")` is the cron's heartbeat, so an
    unreachable maintenance DB is exactly what `db.pool_health()` is read to
    find, and it was the one failure the figure could not show.
    """

    def _final_guard(self, name):
        fn = ast.parse(
            textwrap.dedent(inspect.getsource(getattr(pool.ConnectionPool, name)))
        ).body[0]
        self.assertIsInstance(
            fn.body[-1],
            ast.Try,
            f"{name} must end with the guarded block; a statement after it is "
            f"by definition outside the release path",
        )
        return {
            node.func.attr
            for handler in fn.body[-1].handlers
            for node in ast.walk(handler)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

    def test_both_paths_count_and_unwind_in_the_same_handler(self):
        for name in ("borrow", "_borrow_direct"):
            with self.subTest(path=name):
                handler_calls = self._final_guard(name)
                self.assertIn("record_borrow_failed", handler_calls)
                self.assertIn("_unwind_failed_borrow", handler_calls)

    def test_the_direct_path_takes_its_permit_before_that_guard(self):
        fn = ast.parse(
            textwrap.dedent(inspect.getsource(pool.ConnectionPool._borrow_direct))
        ).body[0]
        guard = fn.body[-1]
        self.assertNotIn(
            "acquire",
            {
                node.func.attr
                for node in ast.walk(ast.Module(body=guard.body, type_ignores=[]))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            },
            "a permit taken inside the guard would be released by a handler "
            "that never took one",
        )


class TestOneDecodeOfAStatementsText(unittest.TestCase):
    def test_both_entry_points_read_the_text_through_one_function(self):
        for name in ("_resolve_ddl", "executemany"):
            with self.subTest(entry_point=name):
                self.assertIn(
                    "_statement_text",
                    _callees(getattr(cursor.Cursor, name)),
                    "executemany used to spell it str(query), which turns a "
                    "bytes DDL statement into the repr b'CREATE …' and hides "
                    "it from classify_statement",
                )

    def test_it_decodes_bytes_rather_than_repring_them(self):
        self.assertEqual(
            cursor._statement_text(b"CREATE TABLE t (a int)"), "CREATE TABLE t (a int)"
        )
        self.assertEqual(cursor._statement_text(b"\xff\xfe"), "")
        self.assertEqual(cursor._statement_text("SELECT 1"), "SELECT 1")


class TestCursorConstructionNeverLeaksAPermit(unittest.TestCase):
    """`Cursor.__init__` owns a borrowed connection before `_closed` is False.

    `__del__` short-circuits on `_closed`, so nothing else can ever return it:
    measured with a KeyboardInterrupt injected at `_cnx.cursor()`, an
    `except Exception` handler left `budget_in_use=1, checked_out=1` for the
    life of the process, and `maxconn` of those leave every later borrow
    timing out on "connection budget reached".
    """

    def _init_handlers(self):
        fn = ast.parse(textwrap.dedent(inspect.getsource(cursor.Cursor.__init__))).body[
            0
        ]
        return [
            h
            for node in ast.walk(fn)
            if isinstance(node, ast.Try)
            for h in node.handlers
        ]

    def test_the_construction_guard_catches_baseexception(self):
        types = {
            h.type.id for h in self._init_handlers() if isinstance(h.type, ast.Name)
        }
        self.assertIn(
            "BaseException",
            types,
            "an Exception-only guard misses the interrupt and the watchdog's "
            "SystemExit, which is the window where the leak is unrecoverable",
        )

    def test_it_gives_the_connection_back_on_the_same_terms_as_close(self):
        handler_calls = {
            node.func.attr
            for h in self._init_handlers()
            for node in ast.walk(h)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("give_back", handler_calls)
        self.assertIn(
            "_connection_is_clean",
            handler_calls,
            "a connection whose setup raised after a statement sits in a "
            "failed transaction; handing it back as warm passes it on",
        )


class TestTheBreakerLockIsNotReentrant(unittest.TestCase):
    """`allow` holds a plain `threading.Lock`, so it must not call `closed`.

    Demonstrated: giving the `closed` property that lock leaves `allow()` hung
    past a 2 s join. The trap is that `closed` looks exactly like the read
    `allow` wants, so the lock-held path reads `_open` directly instead.
    """

    def test_allow_does_not_go_through_the_property(self):
        self.assertNotIn(
            "closed",
            _callees(breaker.CircuitBreaker.allow),
            "the lock-held path must read _open directly",
        )

    def test_the_cooldown_maths_exists_once(self):
        members = {
            "cooldown_remaining": breaker.CircuitBreaker.cooldown_remaining.fget,
            "snapshot": breaker.CircuitBreaker.snapshot,
        }
        for name, fn in members.items():
            with self.subTest(method=name):
                self.assertIn(
                    "_cooldown_remaining_locked",
                    _callees(fn),
                    "two copies of the same expression drifted apart once "
                    "already in this package",
                )

    def test_the_locked_helper_does_not_take_the_lock(self):
        self.assertNotIn(
            "_lock",
            _callees(breaker.CircuitBreaker._cooldown_remaining_locked),
            "it is called from inside the lock; taking it again deadlocks",
        )


class TestThePairedGaugesArePublishedTogether(unittest.TestCase):
    def test_recording_a_lag_sample_takes_the_lock(self):
        self.assertIn("_lock", _callees(lag.ReplicaLagGate.record))

    def test_rendering_them_takes_it_too(self):
        self.assertIn("_lock", _callees(lag.ReplicaLagGate.snapshot))

    def test_the_per_cursor_read_stays_lock_free(self):
        self.assertNotIn(
            "_lock",
            _callees(lag.ReplicaLagGate.allows),
            "allows() runs per read-only cursor and reads ONE flag; a single "
            "bool is never torn and the pair has its own guarded readers",
        )

    def test_the_leak_throttle_owns_a_lock(self):
        self.assertIn("_report_lock", _callees(leaks.CheckoutTracker.due_for_report))

    def test_tracking_and_release_stay_lock_free(self):
        for name in ("track", "release"):
            with self.subTest(method=name):
                self.assertNotIn(
                    "_report_lock",
                    _callees(getattr(leaks.CheckoutTracker, name)),
                    "single dict operations; the throttle's lock is not theirs",
                )


class TestTheSaturationErrorReadsOneConsistentPair(unittest.TestCase):
    def test_both_counters_come_from_one_acquisition(self):
        src = inspect.getsource(pool.ConnectionPool._budget_exhausted)
        self.assertIn("with self._lock:", src)
        head, _, tail = src.partition("with self._lock:")
        self.assertNotIn("len(self._pools)", head)
        self.assertNotIn("self._direct_out", head)
        body = tail[: tail.index("return PoolError")]
        self.assertIn("len(self._pools)", body)
        self.assertIn("self._direct_out", body)


class TestTheProbeAsksItsQuestionOnce(unittest.TestCase):
    def test_the_proof_and_the_inflight_map_share_one_acquisition(self):
        src = inspect.getsource(probe.ReachabilityProbe.ensure_connectable)
        self.assertEqual(
            src.count("with self._lock:"),
            1,
            "two acquisitions left a window in which a key proven between "
            "them started a second probe -- a full extra connect on the path "
            "whose purpose is to avoid one",
        )
        self.assertNotIn(
            "is_proven",
            _callees(probe.ReachabilityProbe.ensure_connectable),
            "is_proven takes the lock itself; that is the second acquisition",
        )

    def test_only_the_connect_is_classified(self):
        src = inspect.getsource(probe.ReachabilityProbe.probe_connectable)
        tree = ast.parse(textwrap.dedent(src)).body[0]
        tries = [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
        self.assertEqual(len(tries), 1, "one classifying try, no more")
        block = tries[0]

        def calls(nodes):
            mod = ast.Module(body=list(nodes), type_ignores=[])
            return {
                n.func.attr
                for n in ast.walk(mod)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            }

        # AST, not source text: a `.close()` named in a COMMENT explaining the
        # shape this replaces is not a call, and matching on text says it is.
        self.assertIn("connect", calls(block.body))
        self.assertNotIn(
            "close",
            calls(block.body),
            "a connection that opened proves the DSN reachable; closing it is "
            "not part of that question and must not be able to fail it -- "
            "`psycopg.connect(...).close()` filed a reachable DSN as a "
            "transient probe failure whenever the close raised",
        )
        self.assertIn(
            "close",
            calls(block.orelse),
            "the close belongs in the else, where only a successful connect reaches it",
        )


class TestNoSelfLockIsTakenTwice(unittest.TestCase):
    """`threading.Lock` is not reentrant, so a nested acquisition hangs.

    Two instances of this trap have been found in this package -- `allow`
    reading through the `closed` property, and `_budget_exhausted` growing an
    acquisition while its callers might have held one. Both were checked by
    hand; this checks the whole class each time.

    The rule enforced is narrow and mechanical: within one class, a method that
    is called from inside a `with self._lock:` block must not itself contain
    `with self._lock:`. It reads the AST rather than the text, so a lock named
    in a comment or a docstring is not a call.
    """

    LOCKED_CLASSES = (
        pool.ConnectionPool,
        probe.ReachabilityProbe,
        breaker.CircuitBreaker,
        lag.ReplicaLagGate,
    )

    @staticmethod
    def _takes_self_lock(node) -> bool:
        for sub in ast.walk(node):
            if not isinstance(sub, ast.With):
                continue
            for item in sub.items:
                ctx = item.context_expr
                if (
                    isinstance(ctx, ast.Attribute)
                    and ctx.attr.endswith("lock")
                    and isinstance(ctx.value, ast.Name)
                    and ctx.value.id == "self"
                ):
                    return True
        return False

    @staticmethod
    def _self_calls_inside_locks(node) -> set[str]:
        found = set()
        for sub in ast.walk(node):
            if not isinstance(sub, ast.With):
                continue
            locked = any(
                isinstance(i.context_expr, ast.Attribute)
                and i.context_expr.attr.endswith("lock")
                for i in sub.items
            )
            if not locked:
                continue
            for reached in ast.walk(ast.Module(body=sub.body, type_ignores=[])):
                # Both shapes reach a method body: `self.x()` is a Call, and
                # `self.x` on a PROPERTY is a bare Attribute. Collecting only
                # calls is what let `allow()`'s read of the `closed` property
                # -- the very trap this class exists for -- pass the check.
                if (
                    isinstance(reached, ast.Attribute)
                    and isinstance(reached.value, ast.Name)
                    and reached.value.id == "self"
                ):
                    found.add(reached.attr)
        return found

    def test_no_method_called_under_a_lock_takes_that_lock(self):
        for cls in self.LOCKED_CLASSES:
            tree = ast.parse(textwrap.dedent(inspect.getsource(cls))).body[0]
            methods = {
                n.name: n
                for n in tree.body
                if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            }
            called_under_lock = set()
            for node in methods.values():
                called_under_lock |= self._self_calls_inside_locks(node)
            for name in sorted(called_under_lock & methods.keys()):
                with self.subTest(cls=cls.__name__, method=name):
                    self.assertFalse(
                        self._takes_self_lock(methods[name]),
                        f"{cls.__name__}.{name} is called from inside a "
                        f"`with self._lock:` block and takes the lock itself; "
                        f"threading.Lock is not reentrant, so that hangs",
                    )

    def test_the_check_can_see_a_violation(self):
        """A structural pin that cannot fail is not a pin."""
        src = textwrap.dedent("""
            class Bad:
                def outer(self):
                    with self._lock:
                        if self.prop:          # a property READ, not a call
                            return self.inner()

                @property
                def prop(self):
                    with self._lock:
                        return True

                def inner(self):
                    with self._lock:
                        return 1
        """)
        tree = ast.parse(src).body[0]
        methods = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        under_lock = self._self_calls_inside_locks(methods["outer"])
        for name in ("inner", "prop"):
            with self.subTest(reached_as=name):
                self.assertIn(name, under_lock)
                self.assertTrue(self._takes_self_lock(methods[name]))


if __name__ == "__main__":
    unittest.main()
