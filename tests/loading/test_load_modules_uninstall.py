from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

pytestmark = pytest.mark.requires_pg

VICTIM = "test_uninstall"


def _psql(dbname: str, sql: str) -> str:
    proc = subprocess.run(
        ["psql", "-d", dbname, "-tAc", sql],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def db_with_victim(base_db):
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
        check=False,
    )
    assert proc.returncode == 0, (
        f"install failed:\n{proc.stdout[-3000:]}{proc.stderr[-3000:]}"
    )


def _state(dbname: str) -> str:
    return _psql(dbname, f"SELECT state FROM ir_module_module WHERE name='{VICTIM}'")


def _mark_to_remove(dbname: str) -> None:
    _psql(
        dbname, f"UPDATE ir_module_module SET state='to remove' WHERE name='{VICTIM}'"
    )


def _run_update(dbname: str):
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
    assert _state(db_with_victim) == "installed"


def test_a_module_marked_to_remove_is_uninstalled(db_with_victim):
    _mark_to_remove(db_with_victim)
    _run_update(db_with_victim)
    assert _state(db_with_victim) == "uninstalled"


def test_the_uninstall_path_re_enters_registry_new(db_with_victim):
    _mark_to_remove(db_with_victim)
    new_calls, _ = _run_update(db_with_victim)
    assert len(new_calls) == 2, new_calls
    assert new_calls == [db_with_victim, db_with_victim]


def test_no_recursion_when_nothing_is_being_removed(db_with_victim):
    new_calls, _ = _run_update(db_with_victim)
    assert len(new_calls) == 1, new_calls


def test_the_tail_phases_run_via_the_recursion(db_with_victim):
    _mark_to_remove(db_with_victim)
    _, tail_calls = _run_update(db_with_victim)
    assert tail_calls == ["check_null_constraints"], tail_calls
