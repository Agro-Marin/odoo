import pytest

from .conftest import requires_pg


@requires_pg
class TestRawSavepointRollbackHook:
    def _cursor_with_hook_spy(self, scratch_db):
        import odoo.db

        cr = odoo.db.db_connect(scratch_db).cursor()
        calls = {"n": 0}
        original = cr._on_rollback_to_savepoint

        def spy():
            calls["n"] += 1
            original()

        cr._on_rollback_to_savepoint = spy
        return cr, calls

    def test_raw_rollback_to_savepoint_fires_the_hook(self, scratch_db):
        cr, calls = self._cursor_with_hook_spy(scratch_db)
        try:
            cr.execute("SAVEPOINT sp_ct")
            cr.execute("ROLLBACK TO SAVEPOINT sp_ct")
            assert calls["n"] == 1, "raw ROLLBACK TO SAVEPOINT must re-arm the hook"
        finally:
            cr.rollback()
            cr.close()

    def test_optional_savepoint_keyword_form_also_fires(self, scratch_db):
        cr, calls = self._cursor_with_hook_spy(scratch_db)
        try:
            cr.execute("SAVEPOINT sp_ct")
            cr.execute("ROLLBACK TO sp_ct")
            assert calls["n"] == 1
        finally:
            cr.rollback()
            cr.close()

    def test_ordinary_statements_and_release_do_not_fire(self, scratch_db):
        cr, calls = self._cursor_with_hook_spy(scratch_db)
        try:
            cr.execute("SELECT 1")
            cr.execute("SAVEPOINT sp_ct")
            cr.execute("RELEASE SAVEPOINT sp_ct")
            assert calls["n"] == 0
        finally:
            cr.rollback()
            cr.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
