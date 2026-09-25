from __future__ import annotations

import subprocess
import sys
import textwrap
import uuid

import pytest

from odoo.modules.module import adapt_version

from .._pg import dropdb_path, pg_reachable, psql_path, repo_root

REPO_ROOT = repo_root()
MODULE = "test_end_migration_probe"

requires_pg = pytest.mark.requires_pg
requires_psql = pytest.mark.requires_psql

END_SCRIPT = textwrap.dedent(
    """
    def migrate(cr, version):
        cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'probe.fail'")
        row = cr.fetchone()
        if row and row[0] == "1":
            raise RuntimeError("the probe's end script fails on purpose")
        cr.execute(
            "INSERT INTO ir_config_parameter "
            "(key, value, create_uid, write_uid, create_date, write_date) "
            "VALUES ('probe.end', %s, 1, 1, now(), now()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (version,),
        )
    """
)


def _write_module(root, version: str) -> None:
    pkg = root / MODULE
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__manifest__.py").write_text(
        repr(
            {
                "name": "End migration probe",
                "version": version,
                "depends": ["base"],
                "installable": True,
                "license": "LGPL-3",
            }
        ),
        encoding="utf-8",
    )
    if version != "1.0":
        versioned = pkg / "migrations" / version
        versioned.mkdir(parents=True, exist_ok=True)
        (versioned / "end-probe.py").write_text(END_SCRIPT, encoding="utf-8")


def _odoo(db: str, addons: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "odoo-bin"),
            "--addons-path",
            addons,
            "-d",
            db,
            *args,
            "--stop-after-init",
            "--log-level",
            "warn",
        ],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )


def _sql(db: str, statement: str) -> str:
    return subprocess.run(
        [psql_path(), "-d", db, "-tAc", statement],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


def _param(db: str, key: str) -> str:
    return _sql(db, f"SELECT value FROM ir_config_parameter WHERE key = '{key}'")


@pytest.fixture(scope="module")
def retried_upgrade(tmp_path_factory):
    if not pg_reachable():
        pytest.skip("no reachable PostgreSQL")
    if dropdb_path() is None or psql_path() is None:
        pytest.skip("psql/dropdb not on PATH")

    extra = tmp_path_factory.mktemp("probe_addons")
    addons = f"{REPO_ROOT / 'odoo' / 'addons'},{REPO_ROOT / 'addons'},{extra}"
    db = f"odoo_end_migration_{uuid.uuid4().hex[:12]}"
    try:
        _write_module(extra, "1.0")
        installed = _odoo(db, addons, "-i", f"base,{MODULE}")
        if installed.returncode != 0:
            pytest.fail(
                "could not install the probe at 1.0:\n"
                f"{installed.stdout[-4000:]}\n{installed.stderr[-4000:]}"
            )
        _sql(
            db,
            "INSERT INTO ir_config_parameter "
            "(key, value, create_uid, write_uid, create_date, write_date) "
            "VALUES ('probe.fail', '1', 1, 1, now(), now())",
        )
        _write_module(extra, "1.1")
        failed = _odoo(db, addons, "-u", MODULE)
        after_failure = {
            "db_version": _sql(
                db,
                f"SELECT db_version FROM ir_module_module WHERE name = '{MODULE}'",
            ),
            "end": _param(db, "probe.end"),
            "pending": _param(db, "base.pending_end_migrations"),
        }
        _sql(db, "UPDATE ir_config_parameter SET value = '0' WHERE key = 'probe.fail'")
        retried = _odoo(db, addons, "-u", MODULE)
        after_retry = {
            "end": _param(db, "probe.end"),
            "pending": _param(db, "base.pending_end_migrations"),
        }
        yield failed, after_failure, retried, after_retry
    finally:
        subprocess.run(
            [dropdb_path(), "--if-exists", "--force", db],
            check=False,
            capture_output=True,
        )


@requires_pg
@requires_psql
class TestAFailedEndMigrationIsRetried:
    def test_the_first_upgrade_fails_in_its_end_script(self, retried_upgrade):
        failed, after_failure, _, _ = retried_upgrade
        assert failed.returncode != 0, failed.stdout[-4000:]
        assert after_failure["end"] == "", "the failing end script wrote its result"

    def test_the_new_version_is_recorded_with_the_end_stage_pending(
        self, retried_upgrade
    ):
        _, after_failure, _, _ = retried_upgrade
        assert after_failure["db_version"] == adapt_version("1.1"), after_failure
        assert after_failure["pending"], (
            "the new db_version is committed before the end stage, so without a "
            "pending marker the next -u sees nothing left to migrate"
        )
        assert MODULE in after_failure["pending"]

    def test_the_retry_runs_the_end_script_from_the_old_version(self, retried_upgrade):
        _, _, retried, after_retry = retried_upgrade
        assert retried.returncode == 0, retried.stdout[-4000:]
        assert after_retry["end"] == adapt_version("1.0"), (
            "the end script did not run on the retry, or ran from the new version"
        )

    def test_the_marker_is_cleared_once_the_end_stage_succeeds(self, retried_upgrade):
        _, _, _, after_retry = retried_upgrade
        assert after_retry["pending"] == ""
