"""``Registry.delete`` is a rebuild hook; ``Registry.forget`` is a teardown one.

Three module-level maps in ``orm/runtime/registry.py`` are keyed by database
name and outlive a :class:`Registry` instance:

===========================  =========================================
``Registry.registries``      the registries themselves (an ``LRU(42)``)
``_UnaccentTables.by_db``    ~1500-entry accent-folding table, ~180 kB
``_ASSERTION_REPORTS``       the ``--test-enable`` result per database
===========================  =========================================

Only the first was bounded.  The other two grew for the life of the process,
one entry per database ever served, and nothing pruned them --
``doc/architecture/data.md`` requires per-database caches be invalidated per
database.

The obvious fix -- prune them in ``delete`` -- is wrong, and that is what these
tests pin.  ``Registry.new`` calls ``cls.delete(db_name)`` on **every** registry
build, so pruning there would discard the assertion report on every reload and
re-introduce the exit-code defect recorded in ``_ASSERTION_REPORTS``' own
docstring (a run logs its failures and still exits 0), and would re-probe 12 352
codepoints through ``unaccent()`` on every rebuild.
"""

import pytest

from odoo.orm.runtime import registry as reg_mod
from odoo.orm.runtime.registry import Registry

DB = "test_registry_forget_db"


@pytest.fixture
def seeded():
    """Seed all three per-database maps, and clean up whatever the test leaves."""
    reg_mod._UnaccentTables.by_db[DB] = {0xE9: "e"}
    reg_mod._ASSERTION_REPORTS[DB] = object()
    try:
        yield
    finally:
        reg_mod._UnaccentTables.by_db.pop(DB, None)
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
    assert DB in reg_mod._UnaccentTables.by_db, (
        "Registry.delete dropped the unaccent fold table. Rebuilding it costs a "
        "12 352-codepoint probe query, paid on every registry rebuild."
    )


def test_forget_drops_every_per_database_map(seeded):
    Registry.forget(DB)

    assert DB not in reg_mod._UnaccentTables.by_db
    assert DB not in reg_mod._ASSERTION_REPORTS
    assert DB not in Registry.registries


def test_forget_is_idempotent(seeded):
    Registry.forget(DB)
    Registry.forget(DB)  # must not raise on the second pass


def test_delete_all_clears_the_per_database_maps(seeded):
    Registry.delete_all()

    assert not reg_mod._UnaccentTables.by_db
    assert not reg_mod._ASSERTION_REPORTS
    assert not Registry.registries


def test_teardown_call_sites_use_forget_not_delete():
    """The three places a database is genuinely gone must call ``forget``.

    ``Registry.delete`` remains correct inside ``Registry.new`` (a rebuild) and
    nowhere else; a new ``delete`` call outside this module is almost certainly
    a missed ``forget``.
    """
    import pathlib

    root = pathlib.Path(reg_mod.__file__).resolve().parents[3]
    expected = {
        # _drop_database, _rename_database (old name); both live in the
        # lifecycle module since service/db.py became a package.
        "odoo/service/db/lifecycle.py": 2,
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
