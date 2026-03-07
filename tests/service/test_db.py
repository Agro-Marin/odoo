"""Pure-pytest tests for ``odoo.service.db``.

Covers the mockable parts of the database service layer without a live
database, subprocess, or Odoo module loading.

Run with::

    python -m pytest core/tests/service/test_db.py -v
"""

import subprocess
import tempfile
import zipfile
from subprocess import CompletedProcess
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_mod():
    """Import ``odoo.service.db`` once per session."""
    import odoo.service.db as mod  # noqa: PLC0415

    return mod


@pytest.fixture()
def bypass_db_mgmt(db_mod):
    """Patch ``odoo.tools.config`` so the management-enabled decorator passes."""
    import odoo.tools  # noqa: PLC0415

    with patch.object(odoo.tools, "config", {"list_db": True}):
        yield


@pytest.fixture()
def zip_dump():
    """A minimal, valid zip file containing ``dump.sql`` and no filestore."""
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        with zipfile.ZipFile(f, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("dump.sql", "-- empty sql dump\n")
        tmp = f.name
    yield tmp
    import os  # noqa: PLC0415
    os.unlink(tmp)


# ---------------------------------------------------------------------------
# restore_db — pre-flight guard
# ---------------------------------------------------------------------------


class TestRestoreDbPreFlight:
    """``restore_db`` rejects a pre-existing database before touching anything."""

    def test_raises_when_db_already_exists(self, db_mod, bypass_db_mgmt):
        with patch.object(db_mod, "exp_db_exist", return_value=True) as mock_exist, \
             patch.object(db_mod, "_create_empty_database") as mock_create:
            with pytest.raises(RuntimeError, match="already exists"):
                db_mod.restore_db("already_there", "/dev/null")

        mock_exist.assert_called_once_with("already_there")
        mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# restore_db — subprocess failure
# ---------------------------------------------------------------------------


class TestRestoreDbSubprocessFailure:
    """When the pg command fails, the real stderr must surface and the empty
    database must be cleaned up."""

    def _make_patches(self, db_mod, pg_stderr: str):
        """Return a dict of pre-configured patches for a failing pg run."""
        return {
            "exp_db_exist": patch.object(db_mod, "exp_db_exist", return_value=False),
            "create_empty": patch.object(db_mod, "_create_empty_database"),
            "exp_drop": patch.object(db_mod, "exp_drop"),
            "subprocess_run": patch(
                "odoo.service.db.subprocess.run",
                return_value=CompletedProcess(
                    args=[], returncode=1, stderr=pg_stderr
                ),
            ),
        }

    def test_error_message_includes_pg_stderr(self, db_mod, bypass_db_mgmt, zip_dump):
        pg_msg = "FATAL: role \"odoo\" does not exist"
        patches = self._make_patches(db_mod, pg_msg)

        with patches["exp_db_exist"], patches["create_empty"], \
             patches["exp_drop"], patches["subprocess_run"]:
            with pytest.raises(RuntimeError, match="FATAL: role"):
                db_mod.restore_db("newdb", zip_dump)

    def test_empty_db_is_dropped_on_pg_failure(self, db_mod, bypass_db_mgmt, zip_dump):
        patches = self._make_patches(db_mod, "pg error detail")

        with patches["exp_db_exist"], patches["create_empty"], \
             patches["exp_drop"] as mock_drop, patches["subprocess_run"]:
            with pytest.raises(RuntimeError):
                db_mod.restore_db("newdb", zip_dump)

        mock_drop.assert_called_once_with("newdb")

    def test_pg_stderr_not_swallowed_into_generic_message(
        self, db_mod, bypass_db_mgmt, zip_dump
    ):
        """Regression: before the fix, RuntimeError only said 'Couldn't restore database'
        with no pg detail, making silent failures impossible to diagnose."""
        pg_msg = "ERROR: column \"foo\" of relation \"bar\" does not exist"
        patches = self._make_patches(db_mod, pg_msg)

        with patches["exp_db_exist"], patches["create_empty"], \
             patches["exp_drop"], patches["subprocess_run"]:
            with pytest.raises(RuntimeError) as exc_info:
                db_mod.restore_db("newdb", zip_dump)

        assert pg_msg in str(exc_info.value)

    def test_stderr_captured_not_devnull(self, db_mod, bypass_db_mgmt, zip_dump):
        """Regression: before the fix, stderr=subprocess.STDOUT + stdout=DEVNULL
        discarded all pg output. Verify subprocess.run is called with stderr=PIPE."""
        patches = self._make_patches(db_mod, "any error")

        with patches["exp_db_exist"], patches["create_empty"], \
             patches["exp_drop"], patches["subprocess_run"] as mock_run:
            with pytest.raises(RuntimeError):
                db_mod.restore_db("newdb", zip_dump)

        _args, kwargs = mock_run.call_args
        assert kwargs.get("stderr") == subprocess.PIPE, (
            "subprocess.run must capture stderr=PIPE so pg errors are visible"
        )
        assert kwargs.get("stdout") != subprocess.STDOUT, (
            "stdout=subprocess.STDOUT would redirect stderr to /dev/null"
        )


# ---------------------------------------------------------------------------
# restore_db — cleanup on non-pg failure
# ---------------------------------------------------------------------------


class TestRestoreDbCleanupOnAnyFailure:
    """The empty database is dropped even when the failure is not from the pg
    tool — e.g. the zip is unreadable or the registry load fails."""

    def test_empty_db_dropped_when_zip_is_invalid(
        self, db_mod, bypass_db_mgmt
    ):
        with tempfile.NamedTemporaryFile(suffix=".zip") as f:
            f.write(b"not a zip file at all")
            f.flush()
            invalid_zip = f.name

            with patch.object(db_mod, "exp_db_exist", return_value=False), \
                 patch.object(db_mod, "_create_empty_database"), \
                 patch.object(db_mod, "exp_drop") as mock_drop:
                with pytest.raises(Exception):
                    db_mod.restore_db("newdb", invalid_zip)

        mock_drop.assert_called_once_with("newdb")

    def test_empty_db_dropped_when_registry_load_fails(
        self, db_mod, bypass_db_mgmt, zip_dump
    ):
        with patch.object(db_mod, "exp_db_exist", return_value=False), \
             patch.object(db_mod, "_create_empty_database"), \
             patch.object(db_mod, "exp_drop") as mock_drop, \
             patch(
                 "odoo.service.db.subprocess.run",
                 return_value=CompletedProcess(args=[], returncode=0, stderr=""),
             ), \
             patch(
                 "odoo.modules.registry.Registry.new",
                 side_effect=RuntimeError("registry boom"),
             ):
            with pytest.raises(RuntimeError, match="registry boom"):
                db_mod.restore_db("newdb", zip_dump)

        mock_drop.assert_called_once_with("newdb")
