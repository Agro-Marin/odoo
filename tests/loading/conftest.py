from __future__ import annotations

import subprocess
import sys
import uuid

import pytest

from .._pg import (
    dependency_plugin,
    dropdb_path,
    pg_reachable,
    psql_path,
    repo_root,
)

REPO_ROOT = repo_root()

requires_pg = pytest.mark.requires_pg
requires_psql = pytest.mark.requires_psql

REQUIREMENTS = {
    "requires_pg": (pg_reachable, "no reachable PostgreSQL (loading suite needs one)"),
    "requires_psql": (lambda: psql_path() is not None, "psql not on PATH"),
}

pytest_configure, _skip_without_dependencies = dependency_plugin(REQUIREMENTS)


@pytest.fixture(scope="session", autouse=True)
def odoo_config(tmp_path_factory):
    from odoo.tools import config

    config.parse_config(
        [
            "--addons-path",
            f"{REPO_ROOT / 'odoo' / 'addons'},{REPO_ROOT / 'addons'}",
            "--data-dir",
            str(tmp_path_factory.mktemp("datadir")),
        ],
        setup_logging=False,
    )
    return config


@pytest.fixture(scope="session")
def base_db(odoo_config):
    if not pg_reachable():
        pytest.skip("no reachable PostgreSQL")
    if dropdb_path() is None:
        pytest.skip("dropdb not on PATH")
    name = f"odoo_loading_{uuid.uuid4().hex[:12]}"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "odoo-bin"),
            "--addons-path",
            f"{REPO_ROOT / 'odoo' / 'addons'},{REPO_ROOT / 'addons'}",
            "-d",
            name,
            "-i",
            "base",
            "--stop-after-init",
            "--log-level",
            "warn",
        ],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if proc.returncode != 0:
        subprocess.run([dropdb_path(), "--if-exists", "--force", name], check=False)
        pytest.fail(
            f"could not install base:\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}"
        )
    try:
        yield name
    finally:
        subprocess.run(
            [dropdb_path(), "--if-exists", "--force", name],
            check=False,
            capture_output=True,
        )
