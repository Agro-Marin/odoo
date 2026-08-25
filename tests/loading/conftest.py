"""Harness for the module-loading suite (needs a real PostgreSQL).

``odoo/modules/loading.py::load_modules`` is the procedure that decides schema
migration, install/upgrade ordering and registry setup — 332 lines and 70
branches, the densest function in the core. It is exercised end to end by the
DB-backed integration job (ADR-0007) only in the sense that *installing base
runs it*; nothing asserts anything about **what it does, in what order**, so a
refactor of it has no safety net beyond "base still installs".

This suite supplies that net. It runs the real thing against a disposable
database and records the sequence of collaborator calls, which is the closest
observable proxy for "the phases ran in this order" while the phases are still
anonymous blocks inside one function.

Like ``tests/contract`` it skips rather than fails without PostgreSQL, and like
that suite it must not be *silently* skipped in CI —
``test_dependencies_are_present`` is the canary.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from .._pg import dependency_plugin, pg_reachable

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

requires_pg = pytest.mark.requires_pg

REQUIREMENTS = {
    "requires_pg": (pg_reachable, "no reachable PostgreSQL (loading suite needs one)"),
}

pytest_configure, _skip_without_dependencies = dependency_plugin(REQUIREMENTS)


@pytest.fixture(scope="session", autouse=True)
def odoo_config(tmp_path_factory):
    """Initialise ``odoo.tools.config`` with a real addons path.

    Unlike ``tests/contract``, an empty argv will not do: ``load_modules``
    resolves the module graph off ``addons_path``, so without it ``base`` cannot
    be found and every test here would fail for a reason unrelated to loading.
    The data dir is per-session so a run leaves no filestore behind.
    """
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
    """A disposable database with ``base`` installed, dropped afterwards.

    Built by a real ``odoo-bin -i base`` subprocess rather than in-process:
    installing base mutates a great deal of process-global state (the registry
    cache, the addons import hook, ``sys.modules['odoo.addons.base']``), and a
    later in-process ``Registry.new`` in the same interpreter is what these
    tests are *measuring*. Starting from a clean process for the setup keeps the
    measurement from being contaminated by its own fixture.
    """
    if not pg_reachable():
        pytest.skip("no reachable PostgreSQL")
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
        check=False,  # the failure is reported below, with the captured output
    )
    if proc.returncode != 0:
        subprocess.run(["dropdb", "--if-exists", "--force", name], check=False)
        pytest.fail(
            f"could not install base:\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}"
        )
    try:
        yield name
    finally:
        subprocess.run(
            ["dropdb", "--if-exists", "--force", name], check=False, capture_output=True
        )
