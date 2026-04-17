from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tools.sql import SQL

# ---------------------------------------------------------------------------
# Test fixtures — tiny reports defined in-process (NOT registered in a module)
# ---------------------------------------------------------------------------
# We build them by subclassing directly from the abstract mixin and accessing
# the build method — this lets us unit-test registry composition without
# needing a physical view in the database.


class _Harness:
    """Helper producing a throwaway model-like object bound to sql.report.mixin."""

    def __init__(
        self,
        env,
        select=None,
        from_=None,
        where=None,
        group_by=None,
        order_by=None,
        cte=None,
    ):
        self._env = env
        self._select = select or {}
        self._from = from_ or []
        self._where = where or []
        self._group = group_by or []
        self._order = order_by or []
        self._cte = cte

    def __call__(self):
        m = self._env["sql.report.mixin"]
        # Patch the registry hooks in-place for this instance's method resolution
        return m, self


def _build_with_registries(env, **registries):
    """Call _build_table_query on sql.report.mixin with patched registry hooks.

    Pass registry return values directly (dicts, lists, SQL objects).  The
    helper wraps them into bound methods on the class for the duration of the
    call, then restores the originals.
    """
    mixin = env["sql.report.mixin"]
    cls = type(mixin)
    original = {name: getattr(cls, name) for name in registries}
    try:
        for name, value in registries.items():
            setattr(cls, name, lambda self, _v=value: _v)
        return mixin._build_table_query()
    finally:
        for name, method in original.items():
            setattr(cls, name, method)


class TestRegistryComposition(TransactionCase):
    """Core registry-assembly behaviour."""

    def test_select_and_from_assemble(self):
        sql = _build_with_registries(
            self.env,
            _get_select_fields={"id": "u.id", "login": "u.login"},
            _get_from_tables=[("res_users", "u", None, None)],
        )
        self.assertIn("SELECT", sql.code)
        self.assertIn('u.id AS "id"', sql.code)
        self.assertIn('u.login AS "login"', sql.code)
        self.assertIn("FROM", sql.code)
        self.assertIn("res_users u", sql.code)

    def test_with_cte_preserved(self):
        sql = _build_with_registries(
            self.env,
            _get_select_fields={"id": "c.id"},
            _get_from_tables=[("my_cte", "c", None, None)],
            _with_cte=SQL("my_cte AS (SELECT 1 AS id)"),
        )
        self.assertIn("WITH", sql.code)
        self.assertIn("my_cte AS (SELECT 1 AS id)", sql.code)

    def test_where_joins_with_AND(self):
        sql = _build_with_registries(
            self.env,
            _get_select_fields={"id": "u.id"},
            _get_from_tables=[("res_users", "u", None, None)],
            _get_where_conditions=["u.active = TRUE", "u.id > 0"],
        )
        self.assertIn("WHERE", sql.code)
        self.assertIn("AND", sql.code)

    def test_where_accepts_SQL_objects_for_params(self):
        sql = _build_with_registries(
            self.env,
            _get_select_fields={"id": "u.id"},
            _get_from_tables=[("res_users", "u", None, None)],
            _get_where_conditions=[SQL("u.login = %s", "admin")],
        )
        self.assertEqual(sql.params, ("admin",))

    def test_empty_select_raises(self):
        with self.assertRaises(NotImplementedError) as cm:
            _build_with_registries(
                self.env,
                _get_select_fields={},
                _get_from_tables=[("res_users", "u", None, None)],
            )
        self.assertIn("_get_select_fields", str(cm.exception))

    def test_empty_from_raises(self):
        with self.assertRaises(NotImplementedError) as cm:
            _build_with_registries(
                self.env,
                _get_select_fields={"id": "1"},
                _get_from_tables=[],
            )
        self.assertIn("_get_from_tables", str(cm.exception))


class TestPercentEscaping(TransactionCase):
    """Registry strings must escape ``%`` as ``%%``; enforce with a clear error."""

    def test_unescaped_percent_in_select_raises_value_error(self):
        with self.assertRaises(ValueError) as cm:
            _build_with_registries(
                self.env,
                _get_select_fields={
                    "id": "u.id",
                    "adm": "CASE WHEN u.login LIKE 'adm%' THEN 1 ELSE 0 END",
                },
                _get_from_tables=[("res_users", "u", None, None)],
            )
        self.assertIn("%%", str(cm.exception))
        self.assertIn("adm", str(cm.exception))

    def test_escaped_percent_pair_accepted(self):
        # The SQL class preserves '%%' verbatim in .code (psycopg collapses
        # to '%' at execution time).  What matters is that construction
        # doesn't raise TypeError — which was the whole point of the
        # escaping requirement.
        sql = _build_with_registries(
            self.env,
            _get_select_fields={
                "id": "u.id",
                "adm": "CASE WHEN u.login LIKE 'adm%%' THEN 1 ELSE 0 END",
            },
            _get_from_tables=[("res_users", "u", None, None)],
        )
        self.assertIn("adm%%", sql.code)
        self.env.cr.execute(sql)  # must not raise — round-trip through psycopg

    def test_unescaped_percent_in_where_raises(self):
        with self.assertRaises(ValueError):
            _build_with_registries(
                self.env,
                _get_select_fields={"id": "u.id"},
                _get_from_tables=[("res_users", "u", None, None)],
                _get_where_conditions=["u.login LIKE 'x%'"],
            )


class TestMaterializedMarkerInteraction(TransactionCase):
    """The _materialized marker flips _table_query's return value.

    Regression fence for the C1 bug: without this behaviour, models that
    inherit both ``sql.report.mixin`` and ``materialized.view.mixin`` have a
    physical MV that the ORM never reads.
    """

    def _with_hooks(self, materialized):
        """Return the _table_query value for a harness with given marker."""
        mixin = self.env["sql.report.mixin"]
        cls = type(mixin)
        orig_select = cls._get_select_fields
        orig_from = cls._get_from_tables
        cls._get_select_fields = lambda self: {"id": "u.id"}
        cls._get_from_tables = lambda self: [("res_users", "u", None, None)]
        marker_patch = patch.object(cls, "_materialized", materialized, create=True)
        try:
            marker_patch.start()
            return mixin._table_query
        finally:
            marker_patch.stop()
            cls._get_select_fields = orig_select
            cls._get_from_tables = orig_from

    def test_non_materialized_returns_sql(self):
        # The abstract mixin itself defines no fields, so we need to patch
        # marker explicitly to False for this path.
        tq = self._with_hooks(materialized=False)
        self.assertIsInstance(tq, SQL)
        self.assertTrue(bool(tq))

    def test_materialized_returns_none(self):
        tq = self._with_hooks(materialized=True)
        self.assertIsNone(tq)
