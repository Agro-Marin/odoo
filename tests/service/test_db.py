"""Pure-pytest tests for ``odoo.service.db``.

Covers the mockable parts of the database service layer without a live
database, subprocess, or Odoo module loading.

Run with::

    python -m pytest core/tests/service/test_db.py -v
"""

import io
import subprocess
import tempfile
import zipfile
from contextlib import ExitStack
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


# ---------------------------------------------------------------------------
# DBNAME_PATTERN — name validation in exp_create_database / exp_duplicate_database
# ---------------------------------------------------------------------------


class TestDbNameValidation:
    """Database name validation is enforced at the service layer, not only the
    HTTP controller, so direct RPC callers are also protected."""

    @pytest.mark.parametrize("bad_name", [
        "bad name",     # space
        "-badstart",    # starts with dash
        ".badstart",    # starts with dot
        "_badstart",    # starts with underscore
        "",             # empty
        "ab!cd",        # special character
        "ab/cd",        # slash
    ])
    def test_create_rejects_invalid_names(self, db_mod, bypass_db_mgmt, bad_name):
        with patch.object(db_mod, "_create_empty_database") as mock_create:
            with pytest.raises(ValueError, match="Invalid database name"):
                db_mod.exp_create_database(bad_name, False, "en_US")
        mock_create.assert_not_called()

    @pytest.mark.parametrize("good_name", [
        "mydb",
        "my-db",
        "my_db",
        "my.db",
        "My_DB-1.0",
        "a1",
    ])
    def test_create_accepts_valid_names(self, db_mod, bypass_db_mgmt, good_name):
        with patch.object(db_mod, "_create_empty_database"), \
             patch("odoo.modules.db.initialize_db"):
            db_mod.exp_create_database(good_name, False, "en_US")  # must not raise

    @pytest.mark.parametrize("bad_name", ["bad name", "-start", "has/slash"])
    def test_duplicate_rejects_invalid_new_name(self, db_mod, bypass_db_mgmt, bad_name):
        with pytest.raises(ValueError, match="Invalid database name"):
            db_mod.exp_duplicate_database("source_db", bad_name)

    def test_pattern_accepts_valid_names(self, db_mod):
        """DBNAME_PATTERN accepts all canonical valid names (spot-check)."""
        import re  # noqa: PLC0415
        for name in ["mydb", "my-db", "my_db", "my.db", "My_DB-1.0", "a1"]:
            assert re.match(db_mod.DBNAME_PATTERN, name), f"{name!r} should match DBNAME_PATTERN"


# ---------------------------------------------------------------------------
# restore_db — TypeError on non-str db (replaces disabled assert)
# ---------------------------------------------------------------------------


class TestRestoreDbTypeCheck:
    """restore_db rejects non-str db argument via TypeError, not assert.

    assert is a no-op under ``python -O`` (optimized mode); production
    deployments commonly use -O, making the original assert useless.
    """

    @pytest.mark.parametrize("bad_arg", [42, None, b"bytes", 3.14, ["list"]])
    def test_raises_type_error(self, db_mod, bypass_db_mgmt, bad_arg):
        with pytest.raises(TypeError, match="db must be a str"):
            db_mod.restore_db(bad_arg, "/dev/null")

    def test_str_passes_type_check(self, db_mod, bypass_db_mgmt):
        """A str argument must get past the type check (fail on DB existence)."""
        with patch.object(db_mod, "exp_db_exist", return_value=True):
            with pytest.raises(RuntimeError, match="already exists"):
                db_mod.restore_db("valid_str", "/dev/null")


# ---------------------------------------------------------------------------
# dump_db — zip format: pg_dump stderr capture
# ---------------------------------------------------------------------------


class TestDumpDbZipStderr:
    """dump_db zip format captures pg_dump stderr so failures are diagnosable.

    Previously stderr=subprocess.STDOUT + stdout=DEVNULL discarded all pg_dump
    diagnostic output; CalledProcessError carried no useful message.
    """

    def _patches(self, db_mod, returncode: int, stderr: bytes) -> list:
        # Tests call dump_db(..., with_filestore=False) so the
        # odoo.tools.config.filestore() call is skipped entirely.
        mock_cr = MagicMock()
        mock_cr.__enter__ = MagicMock(return_value=mock_cr)
        mock_cr.__exit__ = MagicMock(return_value=False)
        mock_db = MagicMock()
        mock_db.cursor.return_value = mock_cr
        return [
            patch("odoo.service.db.find_pg_tool", return_value="/usr/bin/pg_dump"),
            patch("odoo.service.db.exec_pg_environ", return_value={}),
            patch("odoo.db.db_connect", return_value=mock_db),
            patch.object(db_mod, "dump_db_manifest", return_value={"odoo_dump": "1"}),
            patch(
                "odoo.service.db.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=returncode, stderr=stderr),
            ),
        ]

    def test_failure_raises_runtime_error(self, db_mod, bypass_db_mgmt):
        with ExitStack() as stack:
            for p in self._patches(db_mod, returncode=1, stderr=b"pg_dump: error: conn failed"):
                stack.enter_context(p)
            with pytest.raises(RuntimeError, match="pg_dump failed"):
                db_mod.dump_db("testdb", None, "zip", with_filestore=False)

    def test_failure_includes_pg_stderr_text(self, db_mod, bypass_db_mgmt):
        pg_err = b'FATAL: role "odoo" does not exist'
        with ExitStack() as stack:
            for p in self._patches(db_mod, returncode=1, stderr=pg_err):
                stack.enter_context(p)
            with pytest.raises(RuntimeError) as exc_info:
                db_mod.dump_db("testdb", None, "zip", with_filestore=False)
        assert 'role "odoo" does not exist' in str(exc_info.value)

    def test_subprocess_called_with_stderr_pipe(self, db_mod, bypass_db_mgmt):
        """Regression: verify stderr=PIPE is used, not stderr=STDOUT piped to DEVNULL."""
        with ExitStack() as stack:
            for p in self._patches(db_mod, returncode=1, stderr=b"err"):
                stack.enter_context(p)
            # Override the subprocess.run patch from _patches to spy on kwargs
            mock_run = stack.enter_context(
                patch(
                    "odoo.service.db.subprocess.run",
                    return_value=CompletedProcess(args=[], returncode=1, stderr=b"err"),
                )
            )
            with pytest.raises(RuntimeError):
                db_mod.dump_db("testdb", None, "zip", with_filestore=False)
        _args, kwargs = mock_run.call_args
        assert kwargs.get("stderr") == subprocess.PIPE
        assert kwargs.get("stdout") != subprocess.STDOUT


# ---------------------------------------------------------------------------
# dump_db — dump (pg_custom) format: error detection
# ---------------------------------------------------------------------------


class TestDumpDbDumpFormat:
    """dump_db dump format detects pg_dump failure in both stream paths.

    Previously the stream=True path ignored proc.returncode entirely, and the
    stream=None path returned a raw proc.stdout pipe with no error detection.
    """

    def _make_mock_proc(self, stderr: bytes, returncode: int) -> MagicMock:
        proc = MagicMock()
        proc.stdout = io.BytesIO(b"partial output")
        proc.stderr = io.BytesIO(stderr)
        proc.returncode = returncode
        proc.wait.return_value = None
        return proc

    # -- stream=True path --

    def test_stream_path_raises_on_nonzero_returncode(self, db_mod, bypass_db_mgmt):
        proc = self._make_mock_proc(b"pg_dump: error: boom", returncode=1)
        with patch("odoo.service.db.find_pg_tool", return_value="/usr/bin/pg_dump"), \
             patch("odoo.service.db.exec_pg_environ", return_value={}), \
             patch("odoo.service.db.subprocess.Popen", return_value=proc):
            with pytest.raises(RuntimeError, match="pg_dump failed"):
                db_mod.dump_db("testdb", io.BytesIO(), "dump")

    def test_stream_path_stderr_in_error_message(self, db_mod, bypass_db_mgmt):
        pg_err = b"FATAL: authentication failed for user"
        proc = self._make_mock_proc(pg_err, returncode=1)
        with patch("odoo.service.db.find_pg_tool", return_value="/usr/bin/pg_dump"), \
             patch("odoo.service.db.exec_pg_environ", return_value={}), \
             patch("odoo.service.db.subprocess.Popen", return_value=proc):
            with pytest.raises(RuntimeError) as exc_info:
                db_mod.dump_db("testdb", io.BytesIO(), "dump")
        assert "FATAL: authentication failed" in str(exc_info.value)

    def test_stream_path_success_returns_none(self, db_mod, bypass_db_mgmt):
        proc = self._make_mock_proc(b"", returncode=0)
        with patch("odoo.service.db.find_pg_tool", return_value="/usr/bin/pg_dump"), \
             patch("odoo.service.db.exec_pg_environ", return_value={}), \
             patch("odoo.service.db.subprocess.Popen", return_value=proc):
            result = db_mod.dump_db("testdb", io.BytesIO(), "dump")
        assert result is None

    # -- stream=None path --

    def test_no_stream_path_raises_on_nonzero_returncode(self, db_mod, bypass_db_mgmt):
        with patch("odoo.service.db.find_pg_tool", return_value="/usr/bin/pg_dump"), \
             patch("odoo.service.db.exec_pg_environ", return_value={}), \
             patch(
                 "odoo.service.db.subprocess.run",
                 return_value=CompletedProcess(args=[], returncode=1, stderr=b"pg error"),
             ):
            with pytest.raises(RuntimeError, match="pg_dump failed"):
                db_mod.dump_db("testdb", None, "dump")

    def test_no_stream_path_returns_seekable_tempfile(self, db_mod, bypass_db_mgmt):
        """Regression: the old code returned proc.stdout (a pipe), not a seekable file."""
        with patch("odoo.service.db.find_pg_tool", return_value="/usr/bin/pg_dump"), \
             patch("odoo.service.db.exec_pg_environ", return_value={}), \
             patch(
                 "odoo.service.db.subprocess.run",
                 return_value=CompletedProcess(args=[], returncode=0, stderr=b""),
             ):
            result = db_mod.dump_db("testdb", None, "dump")
        assert result is not None, "Must return a file object, not None or proc.stdout"
        assert hasattr(result, "seek"), "Returned object must be seekable (TemporaryFile)"
        result.close()
