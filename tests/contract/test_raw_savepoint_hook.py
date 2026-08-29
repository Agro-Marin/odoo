import pytest

from .conftest import requires_pg


@pytest.fixture
def hook_spy(scratch_cursor):
    calls = {"n": 0}
    original = scratch_cursor._on_rollback_to_savepoint

    def spy():
        calls["n"] += 1
        original()

    scratch_cursor._on_rollback_to_savepoint = spy
    return scratch_cursor, calls


@requires_pg
class TestRawSavepointRollbackHook:
    def test_raw_rollback_to_savepoint_fires_the_hook(self, hook_spy):
        cr, calls = hook_spy
        cr.execute("SAVEPOINT sp_ct")
        cr.execute("ROLLBACK TO SAVEPOINT sp_ct")
        assert calls["n"] == 1, "raw ROLLBACK TO SAVEPOINT must re-arm the hook"

    def test_optional_savepoint_keyword_form_also_fires(self, hook_spy):
        cr, calls = hook_spy
        cr.execute("SAVEPOINT sp_ct")
        cr.execute("ROLLBACK TO sp_ct")
        assert calls["n"] == 1

    def test_ordinary_statements_and_release_do_not_fire(self, hook_spy):
        cr, calls = hook_spy
        cr.execute("SELECT 1")
        cr.execute("SAVEPOINT sp_ct")
        cr.execute("RELEASE SAVEPOINT sp_ct")
        assert calls["n"] == 0
