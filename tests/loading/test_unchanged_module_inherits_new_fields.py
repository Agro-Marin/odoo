from __future__ import annotations

import subprocess
import sys
import uuid

import pytest

from .._pg import dropdb_path, pg_reachable, psql_path, repo_root

REPO_ROOT = repo_root()
PARENT, CHILD = "probe_parent", "probe_child"

PARENT_MODELS = """
from odoo import fields, models


class ProbeMixin(models.AbstractModel):
    _name = "probe.mixin"
    _description = "Lends its fields to a model of another module"

{mixin_fields}


class ProbeDelegate(models.Model):
    _name = "probe.delegate"
    _description = "Lends its fields through _inherits"

{delegate_fields}
"""

CHILD_MODELS = """
from odoo import fields, models


class ProbeThing(models.Model):
    _name = "probe.thing"
    _inherit = ["probe.mixin"]
    _description = "Inherits the mixin"

    name = fields.Char()


class ProbeWrapper(models.Model):
    _name = "probe.wrapper"
    _inherits = {"probe.delegate": "delegate_id"}
    _description = "Delegates to probe.delegate"

    delegate_id = fields.Many2one("probe.delegate", required=True, ondelete="cascade")
"""


def _write(root, name: str, depends: list[str], models: str) -> None:
    pkg = root / name
    (pkg / "models").mkdir(parents=True, exist_ok=True)
    (pkg / "__manifest__.py").write_text(
        repr(
            {
                "name": name,
                "version": "1.0",
                "depends": depends,
                "installable": True,
                "license": "LGPL-3",
            }
        ),
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    (pkg / "models" / "__init__.py").write_text("from . import m\n", encoding="utf-8")
    (pkg / "models" / "m.py").write_text(models, encoding="utf-8")


def _write_parent(root, *names: str) -> None:
    _write(
        root,
        PARENT,
        ["base"],
        PARENT_MODELS.format(
            mixin_fields="\n".join(f"    {n} = fields.Char()" for n in names),
            delegate_fields="\n".join(f"    d_{n} = fields.Char()" for n in names),
        ),
    )


def _odoo(db: str, addons: str, data_dir, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "odoo-bin"),
            "--addons-path",
            addons,
            "-d",
            db,
            "--db-filter",
            f"^{db}$",
            "--max-cron-threads",
            "0",
            "--stream-workers",
            "0",
            "--db_maxconn",
            "8",
            "--no-http",
            "--data-dir",
            str(data_dir),
            *args,
            "--stop-after-init",
            "--log-level",
            "info",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=900,
        check=False,
    )


def _rows(db: str, query: str) -> set[str]:
    out = subprocess.run(
        [psql_path(), "-d", db, "-tAc", query],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout
    return {line for line in out.splitlines() if line}


@pytest.mark.requires_pg
@pytest.mark.requires_psql
def test_an_unchanged_module_gets_the_fields_an_upgraded_parent_adds(
    tmp_path_factory,
):
    if not pg_reachable():
        pytest.skip("no reachable PostgreSQL")
    if dropdb_path() is None or psql_path() is None:
        pytest.skip("psql/dropdb not on PATH")

    extra = tmp_path_factory.mktemp("inherit_probe_addons")
    addons = f"{REPO_ROOT / 'odoo' / 'addons'},{REPO_ROOT / 'addons'},{extra}"
    data_dir = tmp_path_factory.mktemp("inherit_probe_data")
    db = f"odoo_inheritprobe_{uuid.uuid4().hex[:12]}"
    try:
        _write_parent(extra, "a")
        _write(extra, CHILD, [PARENT], CHILD_MODELS)
        run = _odoo(db, addons, data_dir, "-i", f"base,{PARENT},{CHILD}")
        assert run.returncode == 0, run.stdout[-4000:]
        # the first update stamps the checksums the skip compares against
        run = _odoo(db, addons, data_dir, "-u", "base")
        assert run.returncode == 0, run.stdout[-4000:]

        _write_parent(extra, "a", "b")
        run = _odoo(db, addons, data_dir, "-u", "base")
        assert run.returncode == 0, run.stdout[-4000:]
        assert f"{CHILD} is unchanged" not in run.stdout, (
            "the child must be left out of the upgrade for this test to mean anything"
        )
        assert "unchanged modules left as installed" in run.stdout

        assert _rows(
            db,
            "SELECT model || '.' || name FROM ir_model_fields"
            " WHERE model IN ('probe.thing', 'probe.wrapper')"
            " AND name IN ('b', 'd_b')",
        ) == {"probe.thing.b", "probe.wrapper.d_b"}, (
            "the fields the upgraded parent added are in the registry of the "
            "unchanged child's models but were never reflected"
        )
        assert _rows(
            db,
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'probe_thing' AND column_name = 'b'",
        ) == {"b"}, "a stored field without a column fails every read of the model"
    finally:
        subprocess.run(
            [dropdb_path(), "--if-exists", "--force", db], check=False, timeout=60
        )
