import pytest

from odoo.orm.runtime import _registry_capabilities as cap_mod
from odoo.orm.runtime import registry as reg_mod
from odoo.orm.runtime.registry import Registry

DB = "test_registry_forget_db"


@pytest.fixture
def seeded():
    cap_mod._UnaccentTables.by_db[DB] = {0xE9: "e"}
    reg_mod._ASSERTION_REPORTS[DB] = object()
    try:
        yield
    finally:
        cap_mod._UnaccentTables.by_db.pop(DB, None)
        reg_mod._ASSERTION_REPORTS.pop(DB, None)
        Registry.registries.pop(DB, None)


def test_delete_keeps_what_must_survive_a_rebuild(seeded):
    Registry.delete(DB)

    assert DB in reg_mod._ASSERTION_REPORTS, (
        "Registry.delete dropped the assertion report. It runs inside "
        "Registry.new on every rebuild, so this makes a registry reload discard "
        "every failure recorded before it and exit 0 -- the defect "
        "_ASSERTION_REPORTS was introduced to fix."
    )
    assert DB in cap_mod._UnaccentTables.by_db, (
        "Registry.delete dropped the unaccent fold table. Rebuilding it costs a "
        "12 352-codepoint probe query, paid on every registry rebuild."
    )


def test_forget_drops_every_per_database_map(seeded):
    Registry.forget(DB)

    assert DB not in cap_mod._UnaccentTables.by_db
    assert DB not in reg_mod._ASSERTION_REPORTS
    assert DB not in Registry.registries


def test_forget_is_idempotent(seeded):
    Registry.forget(DB)
    Registry.forget(DB)  # must not raise on the second pass


def test_delete_all_clears_the_per_database_maps(seeded):
    Registry.delete_all()

    assert not cap_mod._UnaccentTables.by_db
    assert not reg_mod._ASSERTION_REPORTS
    assert not Registry.registries


def test_teardown_call_sites_use_forget_not_delete():
    import pathlib

    root = pathlib.Path(reg_mod.__file__).resolve().parents[3]
    expected = {
        # ADR-0014 split service/db.py into a package; the two teardown calls
        # live with the DDL that performs them. This test read the old path and
        # broke on FileNotFoundError when that landed -- caught late, because
        # that change verified `tests/service` and Tier 1 but not Tier 2, which
        # is the "pass all three paths" trap odoo/CLAUDE.md names.
        "odoo/service/db/lifecycle.py": 2,  # _drop_database, _rename_database
        "odoo/http/_serve.py": 1,  # db_absent after a RegistryError
    }
    for rel, count in expected.items():
        text = (root / rel).read_text()
        assert text.count("Registry.forget(") == count, (
            f"{rel} should call Registry.forget {count}x"
        )
        assert "Registry.delete(" not in text, (
            f"{rel} calls Registry.delete; a database that is gone must be "
            f"forgotten, or its unaccent table and assertion report leak for "
            f"the life of the process"
        )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
