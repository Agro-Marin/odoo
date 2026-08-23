import ast
import inspect
import pathlib
import textwrap
import unittest

from odoo.db import bulk, cursor, ddl, dsn, pool, schema_cache

_DB_PACKAGE = pathlib.Path(pool.__file__).parent


def _callees(func) -> set[str]:
    return set(func.__code__.co_names)


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
    """A stale cached plan aborts the transaction, so it cannot be retried in
    place.  Measured: `transaction_status` is INERROR after the failure, and
    both a bare retry and a `discard_cached_plans()` + retry raise
    `InFailedSqlTransaction`.  Recovering inside `Cursor.execute` would need a
    savepoint per statement — two extra round trips on every query in core — so
    the retry belongs where the rollback already happens: `retrying()`.

    The cursor's job is only to *name* the condition, because it is the one
    place that can: it saw the failure on a connection holding auto-prepared
    statements.
    """

    def test_the_cursor_marks_it_on_the_execute_path(self):
        self.assertIn(
            "_note_stale_cached_plan",
            _callees(cursor.Cursor.execute),
            "nothing else can tell a recoverable 0A000 from a permanent one",
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
        src = inspect.getsource(cursor.Cursor._note_stale_cached_plan)
        self.assertIn("clear()", src)
        self.assertNotIn(
            "DEALLOCATE",
            src,
            "the transaction is already aborted here; issuing SQL would raise "
            "InFailedSqlTransaction on top of the error being reported",
        )

    def test_the_family_is_exported_for_the_request_layer(self):
        from odoo.db import errors as err

        self.assertTrue(err.PG_STALE_PLAN_EXCEPTIONS)
        self.assertTrue(callable(err.is_stale_cached_plan))
        # that `retrying()` actually names both is pinned in the integration
        # suite -- odoo/db/tests runs under sys.modules stubs and must not
        # import odoo.service.


class TestAFailedBorrowNeverKeepsItsPermit(unittest.TestCase):
    """Every step after the permit is taken must be inside the release guard.

    The bookkeeping that follows a successful getconn — the checkout tracker,
    the leak warning, the borrow-wait histogram — used to sit AFTER the
    try/except that releases the permit.  Anything raising there burned a
    permit and leaked the connection, permanently: after `maxconn` such
    failures every later borrow times out with "connection budget reached" and
    only a process restart recovers it.

    It is not hypothetical bookkeeping: `_warn_about_leaks` reads
    `tools.config["db_leak_detection"]` on EVERY borrow, and `odoo.db` is
    documented as importable without `odoo.init` (standalone scripts, tools),
    where that key may not be registered.  Injected as a KeyError, four
    borrows against `maxconn=4` killed the pool.
    """

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
    def test_it_returns_zero_or_at_least_one_never_between(self):
        now = pool.monotonic()
        for offset in (-5, -1, -0.5, 0, 0.2, 0.9, 1.0, 1.5, 3, 10, 900):
            with self.subTest(offset=offset):
                got = pool._libpq_connect_timeout(now + offset, 5)
                self.assertTrue(
                    got == 0 or got >= 1, f"{got} would be read as 'wait forever'"
                )
                self.assertLessEqual(got, 5, "must never exceed the cap")

    def test_no_deadline_passes_the_cap_through(self):
        self.assertEqual(pool._libpq_connect_timeout(None, 5), 5)

    def test_every_call_site_guards_the_zero(self):
        source = inspect.getsource(pool)
        tree = ast.parse(source)
        guarded = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                fn = node.value.func
                if getattr(fn, "id", None) == "_libpq_connect_timeout":
                    guarded += 1
        self.assertGreaterEqual(
            guarded, 2, "call sites must bind the result so they can test it"
        )
        self.assertEqual(
            source.count("if not probe_timeout")
            + source.count("if not connect_timeout"),
            guarded,
            "every _libpq_connect_timeout result must be tested for the skip case",
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
    """A committed schema change must heal this process's other connections.

    ``discard_cached_plans`` only heals the connection that ran the DDL; a
    sibling pooled connection keeps a plan built against the old schema and
    raises ``FeatureNotSupported: cached plan must not change result type``.
    The behaviour itself is pinned in the integration suite
    (``TestDdlDrainsSiblingConnections``); these are the structural rules that
    keep the seam where it belongs.
    """

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
    """One assembler, and the maintenance exemption is stated rather than implied.

    The exemption is deliberate, not drift: `db_session_gucs` is tuned for
    application queries, and `statement_timeout` — the commonest thing to put
    there — kills `CREATE DATABASE … TEMPLATE`. Measured in
    `TestMaintenanceConnectionOptions`. What the duplication cost was the
    ability to see that, so the assembler is shared and the opt-out is a
    keyword at the call site.
    """

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
        for path in ("borrow", "_borrow_direct"):
            with self.subTest(path=path):
                self.assertIn(
                    "describe",
                    _calls_on(getattr(pool.ConnectionPool, path), "_checkouts"),
                    "a budget-exhausted error must say who is holding the permits",
                )


class TestBudgetBelongsToAServer(unittest.TestCase):
    def _package(self):
        import odoo.db as package

        return package

    def test_the_key_is_the_resolved_endpoint(self):
        package = self._package()
        names = _callees(package._budget_for)
        self.assertIn("_endpoint_of", names)
        self.assertNotIn(
            "db_replica_host",
            names,
            "keying on 'is a replica configured' hands one server two budgets "
            "whenever the replica resolves back to the primary",
        )

    def test_the_endpoint_comes_from_the_resolved_connection_info(self):
        package = self._package()
        self.assertIn("connection_info_for", _callees(package._endpoint_of))

    def test_the_replica_ceiling_is_gated_on_the_endpoint_differing(self):
        package = self._package()
        self.assertIn("_endpoint_of", _callees(package._maxconn_for))

    def test_budgets_are_kept_per_endpoint_not_as_one_global(self):
        package = self._package()
        self.assertIsInstance(package._budgets, dict)
        self.assertFalse(
            hasattr(package, "_budget"),
            "the single process-wide budget was replaced by a per-endpoint map",
        )


if __name__ == "__main__":
    unittest.main()
