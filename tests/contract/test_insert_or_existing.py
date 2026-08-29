import pytest

from .conftest import requires_pg


@pytest.fixture
def ioe(scratch_cursor):
    scratch_cursor.execute(
        "CREATE TEMP TABLE ioe (k text PRIMARY KEY, v int) ON COMMIT DROP"
    )
    return scratch_cursor


def _insert(cr, k, v):
    def do():
        cr.execute("INSERT INTO ioe (k, v) VALUES (%s, %s)", (k, v))
        return (k, v)

    return do


def _find(cr, k):
    def do():
        cr.execute("SELECT k, v FROM ioe WHERE k = %s", (k,))
        row = cr.fetchone()
        return tuple(row) if row else None

    return do


@requires_pg
class TestInsertOrExisting:
    def test_no_conflict_creates_and_flags_created(self, ioe):
        from odoo.db import insert_or_existing

        row, created = insert_or_existing(
            ioe, _insert(ioe, "a", 1), _find(ioe, "a"), conflict="k=a"
        )
        assert created is True
        assert row == ("a", 1)
        assert _find(ioe, "a")() == ("a", 1), "the row was really written"

    def test_conflict_returns_the_existing_row_not_created(self, ioe):
        from odoo.db import insert_or_existing

        ioe.execute("INSERT INTO ioe (k, v) VALUES ('a', 99)")
        row, created = insert_or_existing(
            ioe, _insert(ioe, "a", 1), _find(ioe, "a"), conflict="k=a"
        )
        assert created is False
        assert row == ("a", 99), "the pre-existing value, not the insert's"

    def test_conflict_with_invisible_row_raises_concurrency_error(self, ioe):
        from odoo.db import insert_or_existing
        from odoo.exceptions import ConcurrencyError

        ioe.execute("INSERT INTO ioe (k, v) VALUES ('a', 99)")
        with pytest.raises(ConcurrencyError):
            insert_or_existing(ioe, _insert(ioe, "a", 1), lambda: None, conflict="k=a")

    def test_a_rejected_insert_leaves_the_transaction_usable(self, ioe):
        from odoo.db import insert_or_existing

        ioe.execute("INSERT INTO ioe (k, v) VALUES ('a', 99)")
        insert_or_existing(ioe, _insert(ioe, "a", 1), _find(ioe, "a"), conflict="k=a")
        ioe.execute("INSERT INTO ioe (k, v) VALUES ('b', 2)")
        assert _find(ioe, "b")() == ("b", 2)

    def test_the_insert_side_is_not_run_again_on_conflict(self, ioe):
        from odoo.db import insert_or_existing

        calls = {"insert": 0}

        def counting_insert():
            calls["insert"] += 1
            ioe.execute("INSERT INTO ioe (k, v) VALUES ('a', 1)")
            return ("a", 1)

        ioe.execute("INSERT INTO ioe (k, v) VALUES ('a', 99)")
        insert_or_existing(ioe, counting_insert, _find(ioe, "a"), conflict="k=a")
        assert calls["insert"] == 1, "insert must run exactly once"
