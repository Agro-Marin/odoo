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
