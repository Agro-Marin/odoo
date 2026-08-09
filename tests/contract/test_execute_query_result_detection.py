"""How ``Environment.execute_query`` tells "no result set" from "no rows".

``execute_query`` calls ``cr.fetchall()`` and treats a ``ProgrammingError``
whose ``sqlstate`` is ``None`` as "the statement returned no result set" (a DDL,
or a DML without RETURNING). That is an assumption about psycopg's *client-side*
error signalling: the driver raises this one itself rather than relaying a
server error, so it carries no sqlstate, and a real server error always does.

The assumption was pinned by nothing until 2026-08-09, when an attempt to
replace it with the declarative-looking ``if cr.description is None: return []``
shipped a silent wrong-result bug. Both halves are pinned here, because both are
load-bearing and neither is obvious:

1. ``sqlstate is None`` really does separate the two cases (a mock cannot show
   this -- it would encode the same belief).
2. ``cr.description`` is **not** a substitute, because inside ``cr.pipeline()``
   psycopg has not synced when it is read: ``description`` is ``None`` for a
   perfectly good SELECT while ``fetchall()`` forces the sync and returns rows.
   That is why the exception form stays.
"""

import psycopg
import pytest

from .conftest import requires_pg


@requires_pg
class TestNoResultSetIsSignalledWithoutASqlstate:
    def _cursor(self, scratch_db):
        import odoo.db

        return odoo.db.db_connect(scratch_db).cursor()

    @pytest.mark.parametrize(
        "statement",
        [
            "CREATE TABLE probe_ddl (id int)",
            "INSERT INTO probe_ddl VALUES (1)",
            "UPDATE probe_ddl SET id = 2",
        ],
    )
    def test_a_statement_with_no_result_set_raises_without_a_sqlstate(
        self, scratch_db, statement
    ):
        cr = self._cursor(scratch_db)
        try:
            if not statement.startswith("CREATE"):
                cr.execute("CREATE TABLE IF NOT EXISTS probe_ddl (id int)")
            cr.execute(statement)
            with pytest.raises(psycopg.ProgrammingError) as caught:
                cr.fetchall()
            assert caught.value.sqlstate is None
        finally:
            cr.close()

    def test_a_real_server_error_carries_one(self, scratch_db):
        """The discriminator only works because the other case always has one."""
        cr = self._cursor(scratch_db)
        try:
            with pytest.raises(psycopg.errors.UndefinedTable) as caught:
                cr.execute("SELECT * FROM no_such_table_at_all")
            assert caught.value.sqlstate == "42P01"
        finally:
            cr.rollback()
            cr.close()

    def test_an_empty_select_is_not_the_same_thing(self, scratch_db):
        """Zero rows is a result set: it must return [], never raise."""
        cr = self._cursor(scratch_db)
        try:
            cr.execute("SELECT 1 WHERE false")
            assert cr.fetchall() == []
        finally:
            cr.close()


@requires_pg
class TestDescriptionIsNotASubstituteInsideAPipeline:
    """Why ``execute_query`` may not be rewritten as a ``description`` check.

    Outside a pipeline the two agree, which is exactly what makes the rewrite
    look safe -- it passed both DB-free pytest tiers. Inside one they disagree,
    and the failure is silent: ``[]`` returned for a real result set.
    """

    def _cursor(self, scratch_db):
        import odoo.db

        return odoo.db.db_connect(scratch_db).cursor()

    def test_outside_a_pipeline_description_agrees_with_fetchall(self, scratch_db):
        cr = self._cursor(scratch_db)
        try:
            cr.execute("SELECT 1 AS a")
            assert cr.description is not None
            assert cr.fetchall() == [(1,)]
        finally:
            cr.close()

    def test_inside_a_pipeline_description_is_none_while_rows_exist(self, scratch_db):
        cr = self._cursor(scratch_db)
        try:
            with cr.pipeline():
                cr.execute("SELECT 2 AS b")
                assert cr.description is None, (
                    "if this ever becomes non-None, the pipeline caveat in "
                    "Environment.execute_query can be revisited"
                )
                assert cr.fetchall() == [(2,)]
        finally:
            cr.close()
