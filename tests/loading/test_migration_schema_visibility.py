from __future__ import annotations

import subprocess
import sys
import textwrap
import uuid

import pytest

from .._pg import dropdb_path, pg_reachable, psql_path, repo_root

REPO_ROOT = repo_root()
MODULE = "test_migration_probe"
TABLE = "migration_probe"
NEW_COLUMN = "added_at_1_1"

requires_pg = pytest.mark.requires_pg
requires_psql = pytest.mark.requires_psql

PROBE = textwrap.dedent(
    """
    def migrate(cr, version):
        cr.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s",
            ("{table}", "{column}"),
        )
        seen = "yes" if cr.fetchone() else "no"
        cr.execute(
            "INSERT INTO ir_config_parameter "
            "(key, value, create_uid, write_uid, create_date, write_date) "
            "VALUES (%s, %s, 1, 1, now(), now()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            ("{key}", seen),
        )
    """
)


def _manifest(version: str) -> str:
    return repr(
        {
            "name": "Migration stage probe",
            "version": version,
            "depends": ["base"],
            "installable": True,
            "license": "LGPL-3",
        }
    )


def _model(with_new_column: bool) -> str:
    extra = f"    {NEW_COLUMN} = fields.Char()\n" if with_new_column else ""
    return (
        "from odoo import fields, models\n\n\n"
        "class MigrationProbe(models.Model):\n"
        f"    _name = {MODULE!r}.replace('test_migration_probe', 'migration.probe')\n"
        '    _description = "Migration stage probe"\n\n'
        "    kept = fields.Char()\n" + extra
    )


def _write_module(root, version: str, *, with_new_column: bool, stages: bool) -> None:
    pkg = root / MODULE
    (pkg / "models").mkdir(parents=True, exist_ok=True)
    (pkg / "__manifest__.py").write_text(_manifest(version), encoding="utf-8")
    (pkg / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    (pkg / "models" / "__init__.py").write_text(
        "from . import migration_probe\n", encoding="utf-8"
    )
    (pkg / "models" / "migration_probe.py").write_text(
        _model(with_new_column), encoding="utf-8"
    )
    if not stages:
        return
    versioned = pkg / "migrations" / version
    versioned.mkdir(parents=True, exist_ok=True)
    for stage in ("pre", "post"):
        (versioned / f"{stage}-probe.py").write_text(
            PROBE.format(table=TABLE, column=NEW_COLUMN, key=f"probe.{stage}"),
            encoding="utf-8",
        )


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


@pytest.fixture(scope="module")
def staged_upgrade(tmp_path_factory):
    if not pg_reachable():
        pytest.skip("no reachable PostgreSQL")
    if dropdb_path() is None or psql_path() is None:
        pytest.skip("psql/dropdb not on PATH")

    extra = tmp_path_factory.mktemp("probe_addons")
    addons = f"{REPO_ROOT / 'odoo' / 'addons'},{REPO_ROOT / 'addons'},{extra}"
    db = f"odoo_migration_{uuid.uuid4().hex[:12]}"
    try:
        _write_module(extra, "1.0", with_new_column=False, stages=False)
        installed = _odoo(db, addons, "-i", f"base,{MODULE}")
        if installed.returncode != 0:
            pytest.fail(
                "could not install the probe at 1.0:\n"
                f"{installed.stdout[-4000:]}\n{installed.stderr[-4000:]}"
            )
        _write_module(extra, "1.1", with_new_column=True, stages=True)
        upgraded = _odoo(db, addons, "-u", MODULE)
        if upgraded.returncode != 0:
            pytest.fail(
                "could not upgrade the probe to 1.1:\n"
                f"{upgraded.stdout[-4000:]}\n{upgraded.stderr[-4000:]}"
            )
        read = subprocess.run(
            [
                psql_path(),
                "-d",
                db,
                "-tAc",
                (
                    "SELECT key, value FROM ir_config_parameter "
                    "WHERE key LIKE 'probe.%' ORDER BY key"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        seen = dict(
            line.split("|", 1) for line in read.stdout.splitlines() if "|" in line
        )
        yield seen, upgraded
    finally:
        subprocess.run(
            [dropdb_path(), "--if-exists", "--force", db],
            check=False,
            capture_output=True,
        )


@requires_pg
@requires_psql
class TestStagesSeeDifferentSchemas:
    def test_both_stages_ran(self, staged_upgrade):
        seen, _ = staged_upgrade
        assert set(seen) == {"probe.pre", "probe.post"}, (
            f"a stage did not run, so this suite is asserting nothing: {seen}. "
            f"Check the migration directory name against `_convert_version` — "
            f"a mismatch is silent, which is the defect R3's narrowed half is "
            f"about."
        )

    def test_pre_runs_before_the_column_exists(self, staged_upgrade):
        seen, _ = staged_upgrade
        assert seen["probe.pre"] == "no", (
            "the `pre` script could already see the column 1.1 adds, so `pre` "
            "is no longer the stage that observes the old shape and every "
            "migration written against that guarantee is wrong"
        )

    def test_post_runs_after_the_column_exists(self, staged_upgrade):
        seen, _ = staged_upgrade
        assert seen["probe.post"] == "yes", (
            "the `post` script could not see the column 1.1 adds, so `post` no "
            "longer runs against the new schema"
        )
