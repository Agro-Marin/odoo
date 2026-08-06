"""A raw ``ROLLBACK TO SAVEPOINT`` must re-arm the catalog-cache hook.

``Cursor._on_rollback_to_savepoint`` drops the transaction-scoped schema-cache
facts a partial rollback invalidates (see ``odoo/db/cursor.py``). Code that opens
savepoints through ``cr.savepoint()`` fires it via the ``Savepoint`` class; code
that issues the raw ``ROLLBACK TO SAVEPOINT`` SQL — some addons still do —
bypassed it, leaving ``schema_cache`` describing a schema that was rolled back,
the stale-OID hazard a later binary ``COPY`` encodes against.

This drives the *real* ``Cursor.execute`` against a real PostgreSQL connection
(the detection logic itself is unit-tested DB-free in ``odoo/db/tests/test_ddl.py``);
the wiring — that ``execute`` actually calls the hook for the raw statement and
only for it — needs a live cursor, so it lives in the contract suite.
"""

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
            cr.execute("ROLLBACK TO sp_ct")  # SAVEPOINT keyword omitted
            assert calls["n"] == 1
        finally:
            cr.rollback()
            cr.close()

    def test_ordinary_statements_and_release_do_not_fire(self, scratch_db):
        cr, calls = self._cursor_with_hook_spy(scratch_db)
        try:
            cr.execute("SELECT 1")
            cr.execute("SAVEPOINT sp_ct")
            cr.execute("RELEASE SAVEPOINT sp_ct")  # merges, undoes nothing
            assert calls["n"] == 0
        finally:
            cr.rollback()
            cr.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
