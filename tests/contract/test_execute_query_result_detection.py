import psycopg
import pytest

from .conftest import requires_pg


@requires_pg
class TestNoResultSetIsSignalledWithoutASqlstate:
    @pytest.mark.parametrize(
        "statement",
        [
            "CREATE TABLE probe_ddl (id int)",
            "INSERT INTO probe_ddl VALUES (1)",
            "UPDATE probe_ddl SET id = 2",
        ],
    )
    def test_a_statement_with_no_result_set_raises_without_a_sqlstate(
        self, scratch_cursor, statement
    ):
        cr = scratch_cursor
        if not statement.startswith("CREATE"):
            cr.execute("CREATE TABLE IF NOT EXISTS probe_ddl (id int)")
        cr.execute(statement)
        with pytest.raises(psycopg.ProgrammingError) as caught:
            cr.fetchall()
        assert caught.value.sqlstate is None

    def test_a_real_server_error_carries_one(self, scratch_cursor):
        with pytest.raises(psycopg.errors.UndefinedTable) as caught:
            scratch_cursor.execute("SELECT * FROM no_such_table_at_all")
        assert caught.value.sqlstate == "42P01"

    def test_an_empty_select_is_not_the_same_thing(self, scratch_cursor):
        scratch_cursor.execute("SELECT 1 WHERE false")
        assert scratch_cursor.fetchall() == []


@requires_pg
class TestDescriptionIsNotASubstituteInsideAPipeline:
    def test_outside_a_pipeline_description_agrees_with_fetchall(self, scratch_cursor):
        scratch_cursor.execute("SELECT 1 AS a")
        assert scratch_cursor.description is not None
        assert scratch_cursor.fetchall() == [(1,)]

    def test_inside_a_pipeline_description_is_none_while_rows_exist(
        self, scratch_cursor
    ):
        cr = scratch_cursor
        with cr.pipeline():
            cr.execute("SELECT 1 AS a")
            cr.execute("SELECT 2 AS b")
            assert cr.description is None, (
                "if this ever becomes non-None, the pipeline caveat in "
                "Environment.execute_query can be revisited"
            )
            assert cr.fetchall() == [(2,)]
