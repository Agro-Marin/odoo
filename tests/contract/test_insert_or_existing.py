import pytest

from .conftest import requires_pg


@requires_pg
class TestInsertOrExisting:
    def _cursor(self, scratch_db):
        import odoo.db

        cr = odoo.db.db_connect(scratch_db).cursor()
        cr.execute("CREATE TEMP TABLE ioe (k text PRIMARY KEY, v int) ON COMMIT DROP")
        return cr

    def _insert(self, cr, k, v):
        def do():
            cr.execute("INSERT INTO ioe (k, v) VALUES (%s, %s)", (k, v))
            return (k, v)

        return do

    def _find(self, cr, k):
        def do():
            cr.execute("SELECT k, v FROM ioe WHERE k = %s", (k,))
            row = cr.fetchone()
            return tuple(row) if row else None

        return do

    def test_no_conflict_creates_and_flags_created(self, scratch_db):
        from odoo.db import insert_or_existing

        cr = self._cursor(scratch_db)
        try:
            row, created = insert_or_existing(
                cr, self._insert(cr, "a", 1), self._find(cr, "a"), conflict="k=a"
            )
            assert created is True
            assert row == ("a", 1)
            assert self._find(cr, "a")() == ("a", 1), "the row was really written"
        finally:
            cr.rollback()
            cr.close()

    def test_conflict_returns_the_existing_row_not_created(self, scratch_db):
        from odoo.db import insert_or_existing

        cr = self._cursor(scratch_db)
        try:
            cr.execute("INSERT INTO ioe (k, v) VALUES ('a', 99)")
            row, created = insert_or_existing(
                cr, self._insert(cr, "a", 1), self._find(cr, "a"), conflict="k=a"
            )
            assert created is False
            assert row == ("a", 99), "the pre-existing value, not the insert's"
        finally:
            cr.rollback()
            cr.close()

    def test_conflict_with_invisible_row_raises_concurrency_error(self, scratch_db):
        from odoo.db import insert_or_existing
        from odoo.exceptions import ConcurrencyError

        cr = self._cursor(scratch_db)
        try:
            cr.execute("INSERT INTO ioe (k, v) VALUES ('a', 99)")
            with pytest.raises(ConcurrencyError):
                insert_or_existing(
                    cr,
                    self._insert(cr, "a", 1),
                    lambda: None,
                    conflict="k=a",
                )
        finally:
            cr.rollback()
            cr.close()

    def test_a_rejected_insert_leaves_the_transaction_usable(self, scratch_db):
        from odoo.db import insert_or_existing

        cr = self._cursor(scratch_db)
        try:
            cr.execute("INSERT INTO ioe (k, v) VALUES ('a', 99)")
            insert_or_existing(
                cr, self._insert(cr, "a", 1), self._find(cr, "a"), conflict="k=a"
            )
            cr.execute("INSERT INTO ioe (k, v) VALUES ('b', 2)")
            assert self._find(cr, "b")() == ("b", 2)
        finally:
            cr.rollback()
            cr.close()

    def test_the_insert_side_is_not_run_again_on_conflict(self, scratch_db):
        from odoo.db import insert_or_existing

        cr = self._cursor(scratch_db)
        calls = {"insert": 0}

        def counting_insert():
            calls["insert"] += 1
            cr.execute("INSERT INTO ioe (k, v) VALUES ('a', 1)")
            return ("a", 1)

        try:
            cr.execute("INSERT INTO ioe (k, v) VALUES ('a', 99)")
            insert_or_existing(cr, counting_insert, self._find(cr, "a"), conflict="k=a")
            assert calls["insert"] == 1, "insert must run exactly once"
        finally:
            cr.rollback()
            cr.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
