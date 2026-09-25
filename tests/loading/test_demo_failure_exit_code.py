import os
import subprocess
import sys
import uuid

import pytest

from .._pg import dropdb_path, pg_reachable
from .conftest import REPO_ROOT, requires_pg

MANIFEST = """{
    "name": "%(name)s",
    "version": "1.0",
    "author": "test",
    "license": "LGPL-3",
    "depends": ["base"],
    "demo": ["demo/broken.xml"],
}
"""
BROKEN_DEMO = """<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="partner" model="res.partner">
        <field name="no_such_field">demo</field>
    </record>
</odoo>
"""
PASSING_TEST = """from odoo.tests import TransactionCase


class TestNothing(TransactionCase):
    def test_nothing(self):
        pass
"""
MODULES = ("broken_demo_strict", "broken_demo_opt_out", "broken_demo_no_tests")


def _write_module(root, name):
    module = root / name
    (module / "demo").mkdir(parents=True)
    (module / "tests").mkdir()
    (module / "__init__.py").write_text("")
    (module / "__manifest__.py").write_text(MANIFEST % {"name": name})
    (module / "demo" / "broken.xml").write_text(BROKEN_DEMO)
    (module / "tests" / "__init__.py").write_text("from . import test_nothing\n")
    (module / "tests" / "test_nothing.py").write_text(PASSING_TEST)


@pytest.fixture(scope="module")
def demo_db(odoo_config, tmp_path_factory):
    if not pg_reachable():
        pytest.skip("no reachable PostgreSQL")
    if dropdb_path() is None:
        pytest.skip("dropdb not on PATH")
    addons = tmp_path_factory.mktemp("addons")
    for name in MODULES:
        _write_module(addons, name)
    name = f"odoo_loading_demo_{uuid.uuid4().hex[:12]}"
    addons_path = f"{REPO_ROOT / 'odoo' / 'addons'},{REPO_ROOT / 'addons'},{addons}"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "odoo-bin"),
            "--addons-path",
            addons_path,
            "-d",
            name,
            "-i",
            "base",
            "--with-demo",
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
        yield name, addons_path
    finally:
        subprocess.run(
            [dropdb_path(), "--if-exists", "--force", name],
            check=False,
            capture_output=True,
        )


def _install(demo_db, tmp_path, module, *, tests, require_demo=None):
    name, addons_path = demo_db
    environment = dict(os.environ)
    environment.pop("ODOO_REQUIRE_DEMO", None)
    if require_demo is not None:
        environment["ODOO_REQUIRE_DEMO"] = require_demo
    test_options = ["--test-enable", "--test-tags", f"/{module}"] if tests else []
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "odoo-bin"),
            "--addons-path",
            addons_path,
            "--data-dir",
            str(tmp_path / "data"),
            "-d",
            name,
            "-i",
            module,
            *test_options,
            "--stop-after-init",
            "--no-http",
            "--max-cron-threads",
            "0",
            "--log-level",
            "info",
            "--logfile",
            str(tmp_path / "run.log"),
        ],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
        env=environment,
    )
    log = (tmp_path / "run.log").read_text(encoding="utf-8", errors="replace")
    return proc.returncode, log


@requires_pg
class TestADemoFailureUnderTestsFailsTheRun:
    """A module's demo data that fails to load is a WARNING to an install, so
    `-i <module>` exits 0 without it; account_depreciation's demo was broken
    from ce5a16f77db0 and hr_fleet's from 5807b4388a16 while every per-module
    run looked clean. A run with tests is where that must turn red."""

    def test_a_run_with_tests_exits_non_zero_and_names_the_module(
        self, demo_db, tmp_path
    ):
        rc, log = _install(demo_db, tmp_path, "broken_demo_strict", tests=True)
        assert "Starting TestNothing.test_nothing" in log
        assert rc != 0, "the demo failed and the run with tests still exited 0"
        assert (
            "Module broken_demo_strict demo data failed to load while tests run" in log
        )
        assert "demo data failed to load for broken_demo_strict" in log

    def test_the_explicit_opt_out_lets_the_run_pass(self, demo_db, tmp_path):
        rc, log = _install(
            demo_db, tmp_path, "broken_demo_opt_out", tests=True, require_demo="0"
        )
        assert "Starting TestNothing.test_nothing" in log
        assert "Module broken_demo_opt_out demo data failed to install" in log
        assert "failed to load while tests run" not in log
        assert rc == 0, log[-4000:]

    def test_an_install_without_tests_keeps_the_warning_and_exits_zero(
        self, demo_db, tmp_path
    ):
        rc, log = _install(demo_db, tmp_path, "broken_demo_no_tests", tests=False)
        assert "Module broken_demo_no_tests demo data failed to install" in log
        assert "failed to load while tests run" not in log
        assert rc == 0, log[-4000:]
