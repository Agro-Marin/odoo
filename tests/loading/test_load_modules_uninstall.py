"""The uninstall path of ``load_modules`` — the branch nothing else drives.

``load_modules`` lines 789-813 handle modules in state ``to remove``. It is the
only branch that **re-enters** the function: it uninstalls, commits, calls
``Registry.new(...)`` — which calls ``load_modules`` again — and then ``return``s
from the middle, skipping the ~45 lines after it (manual-field checks,
custom-view validation, ``_register_hook``, ``check_null_constraints``, the
``partially_updated_database`` flag).

Before this file there was **no test of that branch anywhere**: the DB-backed
integration job (ADR-0007) installs ``base`` and runs its suite, which never
puts a module into ``to remove``. So the single most intricate control flow in
the module loader — recursion plus an early return out of a 332-line function —
was unverified.

These tests pin what it does *today*, including the consequence that reads like
a bug and may not be one (see ``test_the_tail_phases_run_via_the_recursion``).
That question should be answered deliberately before the function is
decomposed, not silently preserved or silently changed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytestmark = pytest.mark.requires_pg

#: Depends on ``base`` alone, has no dependents, and exists precisely to be
#: uninstalled — so removing it cannot cascade into unrelated schema work.
VICTIM = "test_uninstall"


def _psql(dbname: str, sql: str) -> str:
    proc = subprocess.run(
        ["psql", "-U", "marin", "-d", dbname, "-tAc", sql],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def db_with_victim(base_db):
    """``base_db`` with :data:`VICTIM` installed, restored to that state after.

    Function-scoped over the session-scoped ``base_db``: each test drives a real
    uninstall, so the module has to be put back or the second test would find
    nothing to remove.
    """
    _install_victim(base_db)
    try:
        yield base_db
    finally:
        _install_victim(base_db)


def _install_victim(dbname: str) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "odoo-bin"),
            "--addons-path",
            f"{REPO_ROOT / 'odoo' / 'addons'},{REPO_ROOT / 'addons'}",
            "-d",
            dbname,
            "-i",
            VICTIM,
            "--stop-after-init",
            "--log-level",
            "warn",
        ],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,  # asserted below, so the captured output reaches the report
    )
    assert proc.returncode == 0, (
        f"install failed:\n{proc.stdout[-3000:]}{proc.stderr[-3000:]}"
    )


def _state(dbname: str) -> str:
    return _psql(dbname, f"SELECT state FROM ir_module_module WHERE name='{VICTIM}'")


def _mark_to_remove(dbname: str) -> None:
    _psql(dbname, f"UPDATE ir_module_module SET state='to remove' WHERE name='{VICTIM}'")


def _run_update(dbname: str):
    """Run the update cycle, returning (registry_new_calls, tail_phase_calls)."""
    from odoo.modules.registry import Registry

    Registry.delete(dbname)

    new_calls: list[str] = []
    tail_calls: list[str] = []
    real_new = Registry.new

    def traced_new(db_name, *args, **kwargs):
        new_calls.append(db_name)
        return real_new(db_name, *args, **kwargs)

    real_null_check = Registry.check_null_constraints

    def traced_null_check(self, cr):
        tail_calls.append("check_null_constraints")
        return real_null_check(self, cr)

    with (
        mock.patch.object(Registry, "new", staticmethod(traced_new)),
        mock.patch.object(Registry, "check_null_constraints", traced_null_check),
    ):
        Registry.new(dbname, update_module=True)
    return new_calls, tail_calls


def test_the_victim_is_installed_to_begin_with(db_with_victim):
    """Guard the guard: if setup silently failed, every test below is vacuous."""
    assert _state(db_with_victim) == "installed"


def test_a_module_marked_to_remove_is_uninstalled(db_with_victim):
    _mark_to_remove(db_with_victim)
    _run_update(db_with_victim)
    assert _state(db_with_victim) == "uninstalled"


def test_the_uninstall_path_re_enters_registry_new(db_with_victim):
    """The recursion: the branch rebuilds the registry rather than continuing.

    Two calls, not one — the outer build plus the reload the uninstall branch
    performs after committing. This is the property that makes the early
    ``return`` safe today, and the one an
    ``UninstallRequiresReload``-style refactor has to preserve.
    """
    _mark_to_remove(db_with_victim)
    new_calls, _ = _run_update(db_with_victim)
    assert len(new_calls) == 2, new_calls
    assert new_calls == [db_with_victim, db_with_victim]


def test_no_recursion_when_nothing_is_being_removed(db_with_victim):
    """The contrast case, so the assertion above is about the branch."""
    new_calls, _ = _run_update(db_with_victim)
    assert len(new_calls) == 1, new_calls


def test_the_tail_phases_run_via_the_recursion(db_with_victim):
    """The behavioural question the decomposition must answer explicitly.

    The uninstall branch ``return``s before ``check_null_constraints`` (and the
    other tail phases). They are not skipped overall — the *recursive*
    ``Registry.new`` runs them on the way through — so the observable outcome is
    "they ran once", the same as a normal update.

    That is a real invariant and it is entirely implicit: it holds only because
    the recursion happens to occur before the tail rather than after it. Nothing
    in the source says so, and a decomposition that replaced the early return
    with a signal handled by the caller could easily run the tail twice, or not
    at all, while every other test here still passed. Hence this one.
    """
    _mark_to_remove(db_with_victim)
    _, tail_calls = _run_update(db_with_victim)
    assert tail_calls == ["check_null_constraints"], tail_calls
