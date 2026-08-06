"""Mechanical checks for the invariants ``odoo/db/README.md`` states in prose.

Every rule here is one the package already documents and depends on, but that
nothing enforced — so violating it produced a silent behaviour change rather
than a failing test.  That gap is not hypothetical: the savepoint seam's guard
read ``_restores_orm_state`` off a class that never declared it, ``copy_from``
resolved one table name two incompatible ways, and ``binary=True`` was
documented as "faster" while being 2-3x slower on numeric-heavy rows.

The checks are deliberately structural (what calls what, what a pure function
guarantees) rather than behavioural — behaviour is covered by the rest of the
tier-1 suite and by ``odoo/addons/base/tests/test_db_cursor.py``.  A structural
check fails on the edit that breaks the invariant, not three layers away at
runtime, which is the whole point.
"""

import ast
import inspect
import pathlib
import textwrap
import unittest

from odoo.db import bulk, cursor, ddl, dsn, pool, schema_cache

_DB_PACKAGE = pathlib.Path(pool.__file__).parent


def _callees(func) -> set[str]:
    """Names referenced in *func*'s body (attribute and global names)."""
    return set(func.__code__.co_names)


def _calls_on(func, receiver: str) -> set[str]:
    """Methods invoked on ``self.<receiver>`` inside *func*.

    ``co_names`` is too coarse here: ``discard_cached_plans`` calls ``.clear()``
    on both the prepared-statement cache and (formerly) the schema cache, so
    only the attribute chain distinguishes them.
    """
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
    """Names assigned to ``self`` anywhere in *cls*'s own methods."""
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
    """Methods of *cls* whose body references *name*."""
    found = set()
    for attr in dir(cls):
        member = inspect.getattr_static(cls, attr, None)
        member = getattr(member, "__func__", member)
        code = getattr(member, "__code__", None)
        if code is not None and name in code.co_names:
            found.add(attr)
    return found


class TestBudgetAccounting(unittest.TestCase):
    """ "Semaphore accounting lives ENTIRELY in borrow/_borrow_direct/give_back."

    The permit is taken on the two borrow paths, released there on failure, and
    otherwise travels with the connection to be released exactly once by
    ``give_back``.  A helper that took or released one would make the permit
    leak or double-release, which a bounded semaphore only reports at the moment
    of imbalance — far from the edit that caused it.
    """

    def test_only_the_borrow_paths_acquire_a_permit(self):
        acquirers = {
            m
            for m in _methods_calling(pool.ConnectionPool, "acquire")
            if not m.startswith("__")
        }
        self.assertEqual(acquirers, {"borrow", "_borrow_direct"})

    def test_only_the_borrow_paths_and_give_back_release_a_permit(self):
        releasers = {
            m
            for m in _methods_calling(pool.ConnectionPool, "release")
            if not m.startswith("__")
        }
        self.assertEqual(releasers, {"borrow", "_borrow_direct", "give_back"})

    def test_the_getconn_helpers_never_touch_the_budget(self):
        for helper in ("_getconn_with_retry", "_validate_borrowed_conn"):
            with self.subTest(helper=helper):
                self.assertNotIn(
                    "_budget", _callees(getattr(pool.ConnectionPool, helper))
                )


class TestMaintenanceDatabasesAreNeverPooled(unittest.TestCase):
    """ "borrow routes them to _borrow_direct; give_back closes them outright."

    One idle connection to a template blocks ``CREATE DATABASE ... TEMPLATE``,
    and a psycopg_pool structurally cannot keep a database connection-free: it
    replaces every discarded connection to hold its count.
    """

    def test_borrow_consults_is_maintenance_db_and_diverts(self):
        names = _callees(pool.ConnectionPool.borrow)
        self.assertIn("is_maintenance_db", names)
        self.assertIn("_borrow_direct", names)

    def test_give_back_recognises_the_direct_marker(self):
        self.assertIn("_DIRECT_CONNECTION", _callees(pool.ConnectionPool.give_back))


class TestPasswordNeverReachesAPoolKey(unittest.TestCase):
    """ "pool keys carry only a BLAKE2s fingerprint."

    A URI stores its secret inside the ``dsn`` string rather than under a
    ``password`` key, so a bare ``pop("password")`` leaks it into whatever logs
    the key.
    """

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
    """ "Every DSN consumer routes through dsn._expand_conninfo."

    Skipping it is exactly what leaks a URI's password into a pool key or a log,
    so the raw psycopg parser must have a single caller.
    """

    def test_conninfo_to_dict_is_imported_only_by_dsn(self):
        importers = []
        for path in sorted(_DB_PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                names = ()
                if isinstance(node, ast.ImportFrom):
                    names = tuple(a.name for a in node.names)
                if "conninfo_to_dict" in names:
                    importers.append(path.name)
        self.assertEqual(importers, ["dsn.py"])


class TestLibpqTimeoutNeverLeaksZero(unittest.TestCase):
    """ "0 means skip this connect, never a value to hand libpq."

    libpq reads ``connect_timeout=0`` as *wait indefinitely*, so passing a
    shrinking budget through would make the tail of a deadline unbounded — the
    exact overrun the clamp exists to prevent.
    """

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
    """ "The cache holds two lifetimes."

    DDL invalidates the memoized catalog reads but not the ``ROW EXCLUSIVE``
    lock, which PostgreSQL holds to the end of a transaction that DDL does not
    end.  ``ROLLBACK TO SAVEPOINT`` *does* release it, so that path clears both.
    """

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
    """ "_changes_schema scans EVERY statement, not just the leading one."

    ``BEGIN; ALTER TABLE t ...; COMMIT`` leads with ``BEGIN``, so a
    leading-keyword test misses it and the next ``SELECT *`` on a cached plan
    raises ``FeatureNotSupported`` — sqlstate 0A000, not retryable, so the RPC
    loop turns it into a 500.
    """

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
    """The mixins declare the host surface they need; ``Cursor`` must have it.

    ``cursor.py`` asserts this for a type checker, which only helps when mypy is
    run.  Checking it at import time turns drift into a failing test instead of
    a latent ``AttributeError`` on a bulk path that only some deployments reach.
    """

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


class TestEveryCheckoutIsTracked(unittest.TestCase):
    """ "What is left in the tracker is by definition still out."

    The saturation error and the leak warning both read the tracker, so an
    untracked borrow makes a connection invisible to both, and an unreleased
    return makes a healthy pool look leaky.  Both mistakes are silent — the
    numbers simply drift — so the wiring is pinned rather than trusted.
    """

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
        """``give_back`` has three exits (untracked, direct, pooled); the
        release must precede the first, or a direct connection stays counted."""
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
    """ "db_maxconn is the cap for one PostgreSQL server."

    The cap has been wrong in both directions — per-pool let one server be
    handed ``2 * db_maxconn``, shared-across-pools bounded the sum of two — so
    what matters structurally is that the discriminator is the *resolved
    endpoint* and never the mere presence of ``db_replica_host``.  The
    behavioural coverage is in ``test_budget_endpoints.py``.
    """

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
