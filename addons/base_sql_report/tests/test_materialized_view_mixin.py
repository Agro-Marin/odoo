from unittest.mock import patch

import psycopg

from odoo.tests.common import TransactionCase
from odoo.tools.sql import SQL

from odoo.addons.base_sql_report.models import sql_materialized_mixin


class TestIntrospection(TransactionCase):
    """Schema-scoped pg_class lookups (H3, H4 regression fences)."""

    def setUp(self):
        super().setUp()
        self.mixin = self.env["materialized.view.mixin"]
        self.env.cr.execute("CREATE SCHEMA IF NOT EXISTS test_bsr_schema")
        self.env.cr.execute("""
            DROP MATERIALIZED VIEW IF EXISTS test_bsr_schema.test_bsr_mv CASCADE
        """)
        self.env.cr.execute("""
            CREATE MATERIALIZED VIEW test_bsr_schema.test_bsr_mv AS SELECT 1 AS id
        """)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.env.cr.execute(
            "DROP MATERIALIZED VIEW IF EXISTS test_bsr_schema.test_bsr_mv CASCADE"
        )
        self.env.cr.execute("DROP SCHEMA IF EXISTS test_bsr_schema CASCADE")

    def test_view_exists_is_schema_scoped(self):
        # MV lives in test_bsr_schema, not public. Lookup for the unqualified
        # name from the public-schema cursor must not match.
        self.assertFalse(self.mixin._view_exists("test_bsr_mv"))

    def test_is_populated_returns_bool_for_missing(self):
        r = self.mixin._is_populated("obviously_missing_relation_xyz")
        self.assertIs(type(r), bool)
        self.assertFalse(r)

    def test_relkind_returns_char_or_none(self):
        self.assertIsNone(self.mixin._relkind("obviously_missing_relation_xyz"))


class TestRefreshGuards(TransactionCase):
    """refresh() behaviour under adverse conditions (M1 regression fence)."""

    def setUp(self):
        super().setUp()
        self.mixin = self.env["materialized.view.mixin"]
        self.env.cr.execute("DROP MATERIALIZED VIEW IF EXISTS test_bsr_refresh CASCADE")
        self.env.cr.execute(
            "CREATE MATERIALIZED VIEW test_bsr_refresh AS SELECT 1 AS id"
        )
        self.env.cr.execute("CREATE UNIQUE INDEX ON test_bsr_refresh (id)")
        self.addCleanup(
            lambda: self.env.cr.execute(
                "DROP MATERIALIZED VIEW IF EXISTS test_bsr_refresh CASCADE"
            ),
        )

    def test_refresh_returns_false_for_missing_view(self):
        cls = type(self.mixin)
        with patch.object(cls, "_table", "totally_missing_xyz", create=True):
            self.assertFalse(self.mixin.refresh())

    def test_refresh_propagates_programming_errors(self):
        # Inject a non-transient error — must not be swallowed.
        cls = type(self.mixin)
        with (
            patch.object(cls, "_table", "test_bsr_refresh", create=True),
            patch.object(cls, "_is_populated", side_effect=KeyError("bug")),
        ):
            with self.assertRaises(KeyError):
                self.mixin.refresh()

    def test_refresh_recovers_transaction_on_transient_error(self):
        """A swallowed transient error must not leave the transaction aborted.

        Regression fence: a populated MV without a UNIQUE index makes REFRESH
        CONCURRENTLY raise (and abort the PG transaction).  When that error is
        classified transient, refresh() must return False AND leave the cursor
        usable — otherwise a loop-over-many-MVs cron dies after the first hiccup
        with InFailedSqlTransaction.
        """
        cls = type(self.mixin)
        self.env.cr.execute("DROP MATERIALIZED VIEW IF EXISTS test_bsr_noidx CASCADE")
        self.env.cr.execute("CREATE MATERIALIZED VIEW test_bsr_noidx AS SELECT 1 AS id")
        self.addCleanup(
            lambda: self.env.cr.execute(
                "DROP MATERIALIZED VIEW IF EXISTS test_bsr_noidx CASCADE"
            ),
        )
        transient = (psycopg.errors.ObjectNotInPrerequisiteState,)
        with (
            patch.object(cls, "_table", "test_bsr_noidx", create=True),
            patch.object(
                sql_materialized_mixin, "_TRANSIENT_REFRESH_ERRORS", transient
            ),
        ):
            self.assertFalse(self.mixin.refresh())
        # Transaction must still be healthy after the swallowed failure.
        self.env.cr.execute("SELECT 1")
        self.assertEqual(self.env.cr.fetchone()[0], 1)


class TestDependentHandling(TransactionCase):
    """Creation-time dependency handling (H2 + H5 regression fence)."""

    def setUp(self):
        super().setUp()
        self.mixin = self.env["materialized.view.mixin"]
        self.env.cr.execute("DROP TABLE IF EXISTS test_bsr_collision CASCADE")
        self.env.cr.execute("CREATE TABLE test_bsr_collision (id integer, name text)")
        self.addCleanup(
            lambda: self.env.cr.execute(
                "DROP TABLE IF EXISTS test_bsr_collision CASCADE"
            ),
        )

    def test_relkind_r_detected(self):
        self.assertEqual(self.mixin._relkind("test_bsr_collision"), "r")

    def test_dependent_relations_listed(self):
        # Build a dependent view on top of another MV
        self.env.cr.execute(
            "DROP MATERIALIZED VIEW IF EXISTS test_bsr_dep_target CASCADE"
        )
        self.env.cr.execute(
            "CREATE MATERIALIZED VIEW test_bsr_dep_target AS SELECT 1 AS id"
        )
        self.env.cr.execute("DROP VIEW IF EXISTS test_bsr_dep_child")
        self.env.cr.execute(
            "CREATE VIEW test_bsr_dep_child AS SELECT * FROM test_bsr_dep_target"
        )
        try:
            deps = self.mixin._dependent_relations("test_bsr_dep_target")
            names = {row[0] for row in deps}
            self.assertIn("test_bsr_dep_child", names)
        finally:
            self.env.cr.execute("DROP VIEW IF EXISTS test_bsr_dep_child")
            self.env.cr.execute(
                "DROP MATERIALIZED VIEW IF EXISTS test_bsr_dep_target CASCADE"
            )


class TestCreation(TransactionCase):
    """_create_materialized_view: index shapes and the default init() hook."""

    def setUp(self):
        super().setUp()
        self.mixin = self.env["materialized.view.mixin"]
        self.env.cr.execute("DROP MATERIALIZED VIEW IF EXISTS test_bsr_create CASCADE")
        self.addCleanup(
            lambda: self.env.cr.execute(
                "DROP MATERIALIZED VIEW IF EXISTS test_bsr_create CASCADE"
            ),
        )

    def _index_columns(self):
        """Return the ordered column names of id_test_bsr_create, if any."""
        self.env.cr.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_class ic ON ic.oid = i.indexrelid
            JOIN pg_attribute a ON a.attrelid = i.indrelid
                AND a.attnum = ANY(i.indkey)
            WHERE ic.relname = 'id_test_bsr_create'
            ORDER BY array_position(i.indkey, a.attnum)
            """
        )
        return [row[0] for row in self.env.cr.fetchall()]

    def test_composite_index_field(self):
        cls = type(self.mixin)
        with (
            patch.object(cls, "_table", "test_bsr_create", create=True),
            patch.object(
                cls,
                "_build_table_query",
                lambda self: SQL("SELECT 1 AS a, 2 AS b"),
                create=True,
            ),
        ):
            self.mixin._create_materialized_view(index_field=["a", "b"])
            # The composite unique index must exist, and CONCURRENTLY refresh
            # (which requires such an index) must succeed against it.
            self.assertEqual(self._index_columns(), ["a", "b"])
            self.assertTrue(self.mixin.refresh())

    def test_empty_index_field_raises(self):
        cls = type(self.mixin)
        with (
            patch.object(cls, "_table", "test_bsr_create", create=True),
            patch.object(
                cls,
                "_build_table_query",
                lambda self: SQL("SELECT 1 AS a"),
                create=True,
            ),
        ):
            with self.assertRaises(ValueError):
                self.mixin._create_materialized_view(index_field=[])

    def test_default_init_uses_mv_index_field(self):
        cls = type(self.mixin)
        with (
            patch.object(cls, "_table", "test_bsr_create", create=True),
            patch.object(cls, "_mv_index_field", "a", create=True),
            # init() no-ops on abstract models; emulate a concrete subclass.
            patch.object(cls, "_abstract", False, create=True),
            patch.object(
                cls,
                "_build_table_query",
                lambda self: SQL("SELECT 1 AS a"),
                create=True,
            ),
        ):
            self.mixin.init()
            self.assertEqual(self._index_columns(), ["a"])

    def test_init_noop_on_abstract_model(self):
        # The mixin itself is abstract and has no table: init() must not try
        # to build an MV (which would fail resolving _query()).
        self.assertTrue(self.mixin._abstract)
        self.mixin.init()  # must not raise
        self.assertEqual(self._index_columns(), [])


class TestRebuildSkipAndDeferral(TransactionCase):
    """init() rebuild policy: hash-based skip and end-of-load deferral."""

    TABLE = "test_bsr_skip"

    def setUp(self):
        super().setUp()
        self.mixin = self.env["materialized.view.mixin"]
        self.env.cr.execute(f"DROP MATERIALIZED VIEW IF EXISTS {self.TABLE} CASCADE")
        self.addCleanup(
            lambda: self.env.cr.execute(
                f"DROP MATERIALIZED VIEW IF EXISTS {self.TABLE} CASCADE"
            ),
        )

    def _concrete(self, query_code="SELECT 1 AS id", loaded=True):
        """Patches emulating a concrete MV model over ``self.TABLE``.

        ``loaded`` pins ``registry.loaded`` for the duration (at_install runs
        execute inside module loading where it is still False; these tests
        exercise both states explicitly).  The original value is restored.
        """
        cls = type(self.mixin)
        return (
            patch.object(cls, "_table", self.TABLE, create=True),
            patch.object(cls, "_abstract", False, create=True),
            patch.object(
                cls,
                "_build_table_query",
                lambda self, code=query_code: SQL(code),
                create=True,
            ),
            patch.object(self.env.registry, "loaded", loaded),
        )

    def _mv_oid(self):
        self.env.cr.execute(
            "SELECT oid FROM pg_class WHERE relname = %s AND relkind = 'm'",
            (self.TABLE,),
        )
        row = self.env.cr.fetchone()
        return row[0] if row else None

    def test_init_skips_rebuild_when_definition_unchanged(self):
        p1, p2, p3, p4 = self._concrete()
        with p1, p2, p3, p4:
            self.mixin.init()
            oid = self._mv_oid()
            self.assertIsNotNone(oid)
            # unchanged definition: the MV must not be dropped/recreated
            self.mixin.init()
            self.assertEqual(self._mv_oid(), oid)

    def test_init_rebuilds_when_query_changes(self):
        p1, p2, p3, p4 = self._concrete()
        with p1, p2, p3, p4:
            self.mixin.init()
            oid = self._mv_oid()
        p1, p2, p3, p4 = self._concrete("SELECT 2 AS id")
        with p1, p2, p3, p4:
            self.mixin.init()
            self.assertNotEqual(self._mv_oid(), oid)
            self.env.cr.execute(f"SELECT id FROM {self.TABLE}")
            self.assertEqual(self.env.cr.fetchone()[0], 2)

    def test_legacy_mv_without_hash_is_rebuilt(self):
        self.env.cr.execute(f"CREATE MATERIALIZED VIEW {self.TABLE} AS SELECT 1 AS id")
        oid = self._mv_oid()
        p1, p2, p3, p4 = self._concrete()
        with p1, p2, p3, p4:
            self.assertTrue(self.mixin._mv_needs_rebuild())
            self.mixin.init()
            self.assertNotEqual(self._mv_oid(), oid)
            # rebuilt MV is stamped: a second init() now skips
            oid = self._mv_oid()
            self.mixin.init()
            self.assertEqual(self._mv_oid(), oid)

    def test_init_defers_to_register_hook_while_loading(self):
        registry = self.env.registry
        self.addCleanup(
            lambda: getattr(registry, "_pending_materialized_views", {}).pop(
                self.mixin._name, None
            )
        )
        p1, p2, p3, p4 = self._concrete()
        with p1, p2, p3, p4:
            self.mixin.init()  # first creation is never deferred
            oid = self._mv_oid()
            self.assertIsNotNone(oid)
        p1, p2, p3, p4 = self._concrete("SELECT 2 AS id", loaded=False)
        with p1, p2, p3, p4:
            self.mixin.init()
            # deferred: nothing rebuilt yet, request recorded
            self.assertEqual(self._mv_oid(), oid)
            self.assertIn(self.mixin._name, registry._pending_materialized_views)
        p1, p2, p3, p4 = self._concrete("SELECT 2 AS id")
        with p1, p2, p3, p4:
            self.mixin._register_hook()
            self.assertNotEqual(self._mv_oid(), oid)
            self.assertNotIn(
                self.mixin._name,
                getattr(registry, "_pending_materialized_views", {}),
            )
            # hook is idempotent once consumed
            oid = self._mv_oid()
            self.mixin._register_hook()
            self.assertEqual(self._mv_oid(), oid)


class TestQueryBridge(TransactionCase):
    """_query() resolution order (C2 + stand-alone regression fence)."""

    def test_query_falls_back_to_table_query_attribute(self):
        mixin = self.env["materialized.view.mixin"]
        cls = type(mixin)
        with patch.object(cls, "_table_query", SQL("SELECT 1 AS id"), create=True):
            # Ensure no _build_table_query is visible
            with patch.object(cls, "_build_table_query", None, create=True):
                q = mixin._query()
                self.assertIsInstance(q, SQL)
                self.assertEqual(q.code, "SELECT 1 AS id")

    def test_query_accepts_str_table_query(self):
        mixin = self.env["materialized.view.mixin"]
        cls = type(mixin)
        with patch.object(cls, "_table_query", "SELECT 1 AS id", create=True):
            with patch.object(cls, "_build_table_query", None, create=True):
                q = mixin._query()
                self.assertIsInstance(q, SQL)
                self.assertEqual(q.code, "SELECT 1 AS id")

    def test_query_raises_when_no_source(self):
        mixin = self.env["materialized.view.mixin"]
        cls = type(mixin)
        with patch.object(cls, "_table_query", None, create=True):
            with patch.object(cls, "_build_table_query", None, create=True):
                with self.assertRaises(NotImplementedError):
                    mixin._query()
