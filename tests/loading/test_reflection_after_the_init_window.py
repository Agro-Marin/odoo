from __future__ import annotations

import subprocess
import sys

import pytest

from .._pg import psql_path, repo_root

REPO_ROOT = repo_root()

pytestmark = [pytest.mark.requires_pg, pytest.mark.requires_psql]

SECOND_MODULE = "test_uninstall"


def _psql(dbname: str, sql: str) -> str:
    proc = subprocess.run(
        [psql_path(), "-d", dbname, "-tAc", sql],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _odoo_bin(dbname: str, flag: str, module: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "odoo-bin"),
            "--addons-path",
            f"{REPO_ROOT / 'odoo' / 'addons'},{REPO_ROOT / 'addons'}",
            "-d",
            dbname,
            flag,
            module,
            "--stop-after-init",
            "--log-level",
            "warn",
        ],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )


@pytest.fixture
def db_with_second_module(base_db):
    proc = _odoo_bin(base_db, "-i", SECOND_MODULE)
    assert proc.returncode == 0, (
        f"install failed:\n{proc.stdout[-3000:]}{proc.stderr[-3000:]}"
    )
    return base_db


def test_updating_one_module_restores_a_lost_reflection_row_of_another(
    db_with_second_module,
):
    dbname = db_with_second_module
    before = int(_psql(dbname, "SELECT count(*) FROM ir_model_inherit"))
    victim = _psql(
        dbname,
        "DELETE FROM ir_model_inherit WHERE id = ("
        "  SELECT i.id FROM ir_model_inherit i"
        "  JOIN ir_model m ON m.id = i.model_id"
        "  WHERE m.model = 'res.partner' ORDER BY i.id LIMIT 1"
        ") RETURNING id",
    )
    assert victim, "base must reflect at least one _inherit of res.partner"
    assert int(_psql(dbname, "SELECT count(*) FROM ir_model_inherit")) == before - 1

    proc = _odoo_bin(dbname, "-u", SECOND_MODULE)

    assert "RuntimeError" not in proc.stderr, proc.stderr[-3000:]
    assert proc.returncode == 0, (
        f"-u {SECOND_MODULE} failed:\n{proc.stdout[-3000:]}{proc.stderr[-3000:]}"
    )
    after = int(_psql(dbname, "SELECT count(*) FROM ir_model_inherit"))
    assert after == before, (
        "the whole-registry reflection pass runs after every init_models() "
        "window has closed; it must open its own, or a row it needs to write "
        f"for a model outside the updated module is lost ({after} != {before})"
    )


def test_updating_one_module_survives_a_parent_that_has_no_ir_model_row_yet(
    db_with_second_module,
):
    dbname = db_with_second_module
    parent = _psql(
        dbname,
        "DELETE FROM ir_model WHERE id = ("
        "  SELECT DISTINCT p.id FROM ir_model_inherit i"
        "  JOIN ir_model p ON p.id = i.parent_id"
        "  WHERE NOT EXISTS ("
        "    SELECT 1 FROM pg_tables t"
        "     WHERE t.tablename = replace(p.model, '.', '_')"
        "  ) ORDER BY p.id LIMIT 1"
        ") RETURNING model",
    )
    assert parent, "base must reflect at least one parent row that can be dropped"

    proc = _odoo_bin(dbname, "-u", SECOND_MODULE)

    assert "Cannot reflect inheritance" not in proc.stderr, proc.stderr[-3000:]
    assert proc.returncode == 0, (
        "a model that is in the registry but has no ir_model row yet -- a new "
        f"mixin in a module this load does not update -- must not fail -u of an "
        f"unrelated module:\n{proc.stdout[-3000:]}{proc.stderr[-3000:]}"
    )
