"""Pure-pytest tests for ``odoo.service.db``.

Covers the mockable parts of the database service layer without a live
database, subprocess, or Odoo module loading.

Run with::

    python -m pytest tests/service/test_db.py -v
"""

import io
import os
import subprocess
import sys
import tempfile
import threading
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


class _MockConfig(dict):
    """Test stand-in for ``odoo.tools.config``.

    ``odoo.tools.config`` is a dict-AND-object hybrid: callers use both
    ``config["list_db"]`` and ``config.filestore(name)``.  A plain dict
    sufficed for the management decorator (which only needs ``["list_db"]``)
    but ``restore_db`` and friends call ``.filestore(...)``.  Subclassing
    ``dict`` keeps the existing dict semantics while exposing ``filestore``
    as an actual method.  Returns paths under ``/nonexistent/`` so any
    ``Path(...).exists()`` check returns False — which is what every
    pre-flight in these tests wants.
    """

    def filestore(self, name: str) -> str:
        return f"/nonexistent/filestore/{name}"


@pytest.fixture()
def bypass_db_mgmt(db_mod):
    """Patch ``odoo.tools.config`` so the management-enabled decorator passes."""
    import odoo.tools  # noqa: PLC0415

    with patch.object(odoo.tools, "config", _MockConfig({"list_db": True})):
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
        """Return a dict of pre-configured patches for a failing pg run.

        The cleanup path calls the internal ``_drop_database`` helper
        (bypasses the ``list_db`` gate) rather than ``exp_drop``.
        """
        return {
            "exp_db_exist": patch.object(db_mod, "exp_db_exist", return_value=False),
            "create_empty": patch.object(db_mod, "_create_empty_database"),
            "drop_database": patch.object(db_mod, "_drop_database"),
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
             patches["drop_database"], patches["subprocess_run"]:
            with pytest.raises(RuntimeError, match="FATAL: role"):
                db_mod.restore_db("newdb", zip_dump)

    def test_empty_db_is_dropped_on_pg_failure(self, db_mod, bypass_db_mgmt, zip_dump):
        patches = self._make_patches(db_mod, "pg error detail")

        with patches["exp_db_exist"], patches["create_empty"], \
             patches["drop_database"] as mock_drop, patches["subprocess_run"]:
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
             patches["drop_database"], patches["subprocess_run"]:
            with pytest.raises(RuntimeError) as exc_info:
                db_mod.restore_db("newdb", zip_dump)

        assert pg_msg in str(exc_info.value)

    def test_stderr_captured_not_devnull(self, db_mod, bypass_db_mgmt, zip_dump):
        """Regression: before the fix, stderr=subprocess.STDOUT + stdout=DEVNULL
        discarded all pg output. Verify subprocess.run is called with stderr=PIPE."""
        patches = self._make_patches(db_mod, "any error")

        with patches["exp_db_exist"], patches["create_empty"], \
             patches["drop_database"], patches["subprocess_run"] as mock_run:
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
                 patch.object(db_mod, "_drop_database") as mock_drop:
                with pytest.raises(Exception):
                    db_mod.restore_db("newdb", invalid_zip)

        mock_drop.assert_called_once_with("newdb")

    def test_empty_db_dropped_when_registry_load_fails(
        self, db_mod, bypass_db_mgmt, zip_dump
    ):
        with patch.object(db_mod, "exp_db_exist", return_value=False), \
             patch.object(db_mod, "_create_empty_database"), \
             patch.object(db_mod, "_drop_database") as mock_drop, \
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
# restore_db — wall-clock timeout (parity with dump_db)
# ---------------------------------------------------------------------------


class TestRestoreDbWallClockTimeout:
    """``restore_db`` bounds the psql/pg_restore subprocess with a wall-clock
    timeout, mirroring ``dump_db``.  A stall must surface as a typed
    ``RuntimeError`` and the half-restored database must be dropped — not
    block the worker until the master watchdog SIGKILLs it."""

    def test_timeout_raises_runtimeerror_and_drops_db(
        self, db_mod, bypass_db_mgmt, zip_dump
    ):
        with patch.object(db_mod, "exp_db_exist", return_value=False), \
             patch.object(db_mod, "_create_empty_database"), \
             patch.object(db_mod, "_drop_database") as mock_drop, \
             patch(
                 "odoo.service.db.subprocess.run",
                 side_effect=subprocess.TimeoutExpired(cmd="psql", timeout=1.0),
             ):
            with pytest.raises(RuntimeError, match="timeout"):
                db_mod.restore_db("newdb", zip_dump)

        mock_drop.assert_called_once_with("newdb")

    def test_timeout_kwarg_passed_to_subprocess(
        self, db_mod, bypass_db_mgmt, zip_dump
    ):
        with patch.object(db_mod, "exp_db_exist", return_value=False), \
             patch.object(db_mod, "_create_empty_database"), \
             patch.object(db_mod, "_drop_database"), \
             patch(
                 "odoo.service.db.subprocess.run",
                 return_value=CompletedProcess(args=[], returncode=1, stderr="x"),
             ) as mock_run:
            with pytest.raises(RuntimeError):
                db_mod.restore_db("newdb", zip_dump)

        _args, kwargs = mock_run.call_args
        assert kwargs.get("timeout", 0) > 0, (
            "restore subprocess must be bounded by a wall-clock timeout"
        )


# ---------------------------------------------------------------------------
# dump_db — name validation (argument-injection guard for pg_dump argv)
# ---------------------------------------------------------------------------


class TestDumpDbNameValidation:
    """``dump_db`` validates the database name *before* building the pg_dump
    argv.  Without it, a flag-shaped name (``--version``, ``-x``) is parsed by
    pg_dump as an option rather than a database — argument injection.  The
    custom format path has no ``db_connect`` ahead of it to reject the name,
    so the guard must live in ``dump_db`` itself."""

    @pytest.mark.parametrize("bad_name", ["--version", "-x", "bad name", ".hidden"])
    def test_rejects_flag_shaped_name_before_subprocess(
        self, db_mod, bypass_db_mgmt, bad_name
    ):
        with patch("odoo.service.db.subprocess.run") as mock_run, \
             patch.object(db_mod, "find_pg_tool") as mock_tool:
            with pytest.raises(ValueError):
                db_mod.dump_db(bad_name, None, backup_format="custom")
        # Validation fails first: neither the tool lookup nor the subprocess runs.
        mock_run.assert_not_called()
        mock_tool.assert_not_called()

    def test_valid_name_reaches_pg_dump_argv(self, db_mod, bypass_db_mgmt):
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return CompletedProcess(args=cmd, returncode=0, stderr=b"")

        with patch("odoo.service.db.subprocess.run", side_effect=fake_run), \
             patch.object(db_mod, "find_pg_tool", lambda n: f"/usr/bin/{n}"), \
             patch.object(db_mod, "exec_pg_environ", dict):
            result = db_mod.dump_db("gooddb", None, backup_format="custom")
        if result is not None:
            result.close()
        assert "gooddb" in captured["cmd"]


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
            db_mod._duplicate_database("source_db", bad_name)

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


class TestDumpDbZipManifestBeforeFilestore:
    """The zip dump writes the manifest (which opens a DB cursor) BEFORE the
    filestore ``copytree``, so an unreachable/bogus DB fails fast instead of
    after a potentially multi-GB copy.
    """

    def test_unreachable_db_fails_before_filestore_copy(self, db_mod, tmp_path):
        import psycopg

        # A real, non-empty filestore so the copytree branch is live
        # (Path(filestore).exists() is genuinely True) — in the old
        # copytree-first order this copy would run before the DB is touched.
        filestore = tmp_path / "filestore"
        filestore.mkdir()
        (filestore / "blob.bin").write_bytes(b"x" * 16)

        class _Cfg(dict):
            def filestore(self, name: str) -> str:
                return str(filestore)

        import odoo.tools

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(odoo.tools, "config", _Cfg({"list_db": True}))
            )
            stack.enter_context(
                patch("odoo.service.db.find_pg_tool", return_value="/usr/bin/pg_dump")
            )
            stack.enter_context(
                patch("odoo.service.db.exec_pg_environ", return_value={})
            )
            # DB unreachable: the manifest step's db_connect raises.
            stack.enter_context(
                patch("odoo.db.db_connect", side_effect=psycopg.OperationalError("down"))
            )
            copytree = stack.enter_context(patch("odoo.service.db.shutil.copytree"))
            with pytest.raises(psycopg.OperationalError):
                db_mod.dump_db("testdb", None, "zip", with_filestore=True)
        # Manifest ran first and raised → the expensive copy never started.
        copytree.assert_not_called()


class TestDumpDbWallClockTimeout:
    """The blocking dump paths bound pg_dump with a wall-clock timeout.

    Before the fix only the streaming (CLI-only) custom-format path was
    bounded; the common web-backup path (zip, ``stream=None``) used a plain
    ``subprocess.run`` with no timeout, so a hung pg_dump blocked the worker
    indefinitely.  All blocking paths now pass ``timeout=`` and translate
    ``TimeoutExpired`` into a typed ``RuntimeError``.
    """

    def _patches(self, db_mod, run_side_effect) -> list:
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
            patch("odoo.service.db.subprocess.run", side_effect=run_side_effect),
        ]

    def test_zip_path_passes_timeout_kwarg(self, db_mod, bypass_db_mgmt):
        with ExitStack() as stack:
            mock_run = stack.enter_context(
                patch(
                    "odoo.service.db.subprocess.run",
                    return_value=CompletedProcess(args=[], returncode=0, stderr=b""),
                )
            )
            for p in self._patches(db_mod, run_side_effect=None)[:-1]:
                stack.enter_context(p)
            db_mod.dump_db("testdb", None, "zip", with_filestore=False)
        _args, kwargs = mock_run.call_args
        assert kwargs.get("timeout") == 3600.0, (
            "zip-format pg_dump must be bounded by a wall-clock timeout"
        )

    def test_zip_path_timeout_raises_runtime_error(self, db_mod, bypass_db_mgmt):
        timeout_exc = subprocess.TimeoutExpired(cmd=["pg_dump"], timeout=3600)
        with ExitStack() as stack:
            for p in self._patches(db_mod, run_side_effect=timeout_exc):
                stack.enter_context(p)
            with pytest.raises(RuntimeError, match="wall-clock timeout"):
                db_mod.dump_db("testdb", None, "zip", with_filestore=False)

    def test_custom_nonstream_timeout_raises_runtime_error(self, db_mod, bypass_db_mgmt):
        timeout_exc = subprocess.TimeoutExpired(cmd=["pg_dump"], timeout=3600)
        with ExitStack() as stack:
            for p in self._patches(db_mod, run_side_effect=timeout_exc):
                stack.enter_context(p)
            with pytest.raises(RuntimeError, match="wall-clock timeout"):
                db_mod.dump_db("testdb", None, "dump", with_filestore=False)

    def test_malformed_timeout_env_falls_back_to_default(self, db_mod):
        with patch.dict(os.environ, {"ODOO_PG_DUMP_TOTAL_TIMEOUT": "not-a-number"}):
            assert db_mod._pg_dump_total_timeout() == 3600.0


# ---------------------------------------------------------------------------
# ODOO_PG_DUMP_WAIT_TIMEOUT — the post-EOF wait must not crash the dump
# (pure ``env_float`` / ``env_int`` unit tests live in test_env.py)
# ---------------------------------------------------------------------------


class TestDumpWaitTimeoutGuard:
    """A malformed ``ODOO_PG_DUMP_WAIT_TIMEOUT`` must not break a dump.

    The post-EOF wait inside ``_run_pg_dump_streaming``'s ``finally`` block
    once parsed this env var with a bare ``float()`` — a malformed value
    raised ``ValueError`` from the finally, crashing a *successful* dump and
    masking the real error of a *failed* one.  It is now parsed through the
    shared ``service._env.env_float`` guard.
    """

    def test_malformed_wait_timeout_does_not_crash_streaming_dump(self, db_mod):
        """A successful streaming dump must survive a malformed wait-timeout env.

        Exercises the real ``_run_pg_dump_streaming`` finally block with a
        trivial subprocess (no DB, no pg_dump needed).
        """
        cmd = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'dump-bytes')"]
        out = io.BytesIO()
        with patch.dict(os.environ, {"ODOO_PG_DUMP_WAIT_TIMEOUT": "not-a-number"}):
            db_mod._run_pg_dump_streaming(cmd, dict(os.environ), out)
        assert out.getvalue() == b"dump-bytes"

    def test_malformed_wait_timeout_does_not_mask_copy_error(self, db_mod):
        """A real copy error must propagate, not be replaced by the parse error.

        When the destination stream raises mid-copy, that ``RuntimeError`` is
        what the caller needs to see; the ``finally`` must not overwrite it
        with a ``ValueError`` from parsing the (malformed) wait-timeout env var.
        """

        class _ExplodingStream:
            def write(self, _data: bytes) -> int:
                raise RuntimeError("disk-full-during-copy")

        cmd = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 1000)"]
        with patch.dict(os.environ, {"ODOO_PG_DUMP_WAIT_TIMEOUT": "garbage"}):
            with pytest.raises(RuntimeError, match="disk-full-during-copy"):
                db_mod._run_pg_dump_streaming(cmd, dict(os.environ), _ExplodingStream())


class TestDumpStallSigkillEscalation:
    """A stalled pg_dump that IGNORES SIGTERM must still be SIGKILLed.

    The stall ``Timer`` used to send only SIGTERM; the SIGKILL escalation lived
    in the ``finally`` block, reachable only AFTER ``copyfileobj`` returns (i.e.
    after stdout EOFs).  A child wedged with stdout held open never EOFs on a
    SIGTERM it ignores, so the copy — and the escalation — blocked forever,
    degrading the documented hard wall-clock ceiling to a best-effort signal.
    ``_kill_on_stall`` now escalates to SIGKILL itself after a grace period.
    """

    def test_sigterm_ignoring_dump_is_sigkilled_and_does_not_hang(
        self, db_mod, monkeypatch
    ):
        # Child mimics a wedged pg_dump: ignore SIGTERM, emit a few bytes, then
        # block forever holding stdout open (so ``copyfileobj`` never sees EOF).
        child = (
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "sys.stdout.buffer.write(b'partial'); sys.stdout.buffer.flush()\n"
            "time.sleep(3600)\n"
        )
        cmd = [sys.executable, "-c", child]
        monkeypatch.setattr(db_mod, "_pg_dump_total_timeout", lambda: 0.5)
        monkeypatch.setattr(db_mod, "_STALL_SIGKILL_GRACE_S", 0.5)
        out = io.BytesIO()

        result: dict = {}

        def _run() -> None:
            try:
                db_mod._run_pg_dump_streaming(cmd, dict(os.environ), out)
                result["ok"] = True
            except BaseException as exc:  # record for the main-thread assert
                result["exc"] = exc

        t = threading.Thread(target=_run)
        t.start()
        # The fix makes this finish in ~total_timeout + grace (~1s); without it
        # the copy blocks forever.  Generous join so a slow CI box isn't flaky.
        t.join(timeout=30)
        assert not t.is_alive(), (
            "streaming dump hung: a SIGTERM-ignoring pg_dump was never SIGKILLed"
        )
        assert isinstance(result.get("exc"), RuntimeError)
        assert "wall-clock timeout" in str(result["exc"])


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


# ---------------------------------------------------------------------------
# _check_faketime_mode — test-only guard
# ---------------------------------------------------------------------------


class TestCheckFaketimeMode:
    """``_check_faketime_mode`` injects a clock-shifting ``public.now()`` SQL
    function — test-only infrastructure that must never fire in production.

    Regression: gated ONLY on the ``ODOO_FAKETIME_TEST_MODE`` env var. An
    accidental export in a systemd unit would have silently corrupted every
    timestamp in the DB. The fix requires BOTH the env var AND ``test_enable``.
    """

    def test_noop_when_env_var_absent(self, db_mod):
        """Without the env var, the function must not touch the DB at all."""
        import os  # noqa: PLC0415
        import odoo.tools  # noqa: PLC0415

        os.environ.pop("ODOO_FAKETIME_TEST_MODE", None)
        with (
            patch.object(odoo.tools, "config", {"test_enable": True, "db_name": ["x"]}),
            patch("odoo.service.db.odoo.db.db_connect") as mock_connect,
        ):
            db_mod._check_faketime_mode("x")

        mock_connect.assert_not_called()

    def test_noop_when_test_enable_off_with_env_var(self, db_mod, caplog):
        """Env var set but --test-enable off → refuse, log a warning, no DB write."""
        import odoo.tools  # noqa: PLC0415

        with (
            patch.dict("os.environ", {"ODOO_FAKETIME_TEST_MODE": "1"}),
            patch.object(odoo.tools, "config", {"test_enable": False, "db_name": ["x"]}),
            patch("odoo.service.db.odoo.db.db_connect") as mock_connect,
            caplog.at_level("WARNING", logger="odoo.service.db"),
        ):
            db_mod._check_faketime_mode("x")

        mock_connect.assert_not_called()
        assert any("Refusing to install faketime" in m for m in caplog.messages)

    def test_noop_when_db_not_in_config(self, db_mod):
        """Env var + test_enable, but db not listed: no DB write."""
        import odoo.tools  # noqa: PLC0415

        with (
            patch.dict("os.environ", {"ODOO_FAKETIME_TEST_MODE": "1"}),
            patch.object(odoo.tools, "config", {"test_enable": True, "db_name": ["other"]}),
            patch("odoo.service.db.odoo.db.db_connect") as mock_connect,
        ):
            db_mod._check_faketime_mode("unlisted_db")

        mock_connect.assert_not_called()

    def test_active_when_all_gates_pass(self, db_mod):
        """Env var + test_enable + db listed: the DB write path is taken."""
        import datetime  # noqa: PLC0415
        import odoo.tools  # noqa: PLC0415

        fake_now = datetime.datetime(2026, 1, 1)
        fake_cursor = MagicMock()
        fake_cursor.fetchone.side_effect = [(fake_now,), (fake_now,)]
        fake_db = MagicMock()
        fake_db.cursor.return_value.__enter__.return_value = fake_cursor

        with (
            patch.dict("os.environ", {"ODOO_FAKETIME_TEST_MODE": "1"}),
            patch.object(odoo.tools, "config", {"test_enable": True, "db_name": ["x"]}),
            patch("odoo.service.db.odoo.db.db_connect", return_value=fake_db),
        ):
            db_mod._check_faketime_mode("x")

        # CREATE OR REPLACE FUNCTION must have been issued — the whole point
        assert any(
            "CREATE OR REPLACE FUNCTION" in str(call_args)
            for call_args in fake_cursor.execute.call_args_list
        )


# ---------------------------------------------------------------------------
# _create_empty_database — TOCTOU-free creation
# ---------------------------------------------------------------------------


class TestCreateEmptyDatabaseTOCTOU:
    """``_create_empty_database`` must let PG be the source of truth for existence.

    Regression: the prior ``SELECT datname ... / CREATE DATABASE`` pair was
    racy — two concurrent callers could both pass the check and one got a
    raw ``psycopg.errors.DuplicateDatabase`` instead of the canonical
    ``DatabaseExists``. The fix removes the pre-flight query and translates
    PG's 42P04 error directly.
    """

    def test_duplicate_database_translates_to_databaseexists(self, db_mod):
        """A PG DuplicateDatabase error must surface as DatabaseExists."""
        import psycopg  # noqa: PLC0415
        import odoo.tools  # noqa: PLC0415

        # Stub the identifier builder — the real one needs a live pgconn.
        fake_cr = MagicMock()
        fake_cr.execute.side_effect = psycopg.errors.DuplicateDatabase(
            'database "x" already exists'
        )
        fake_db = MagicMock()
        fake_db.cursor.return_value = fake_cr
        fake_cr.__enter__ = MagicMock(return_value=fake_cr)
        fake_cr.__exit__ = MagicMock(return_value=None)

        with (
            patch.object(odoo.tools, "config", {"db_template": "template0"}),
            patch("odoo.service.db.odoo.db.db_connect", return_value=fake_db),
            patch("odoo.service.db.database_identifier", return_value=""),
            patch("odoo.service.db._check_faketime_mode"),
        ):
            with pytest.raises(db_mod.DatabaseExists, match="already exists"):
                db_mod._create_empty_database("x")

    def test_no_preflight_existence_query(self, db_mod):
        """The old pre-flight ``SELECT datname FROM pg_database`` must be gone.

        The fix lets CREATE DATABASE itself be the check — a pre-flight query
        would reintroduce the TOCTOU race.
        """
        import inspect  # noqa: PLC0415

        src = inspect.getsource(db_mod._create_empty_database)
        assert "FROM pg_database" not in src, (
            "Pre-flight pg_database query removed to eliminate TOCTOU; do not re-add."
        )


# ---------------------------------------------------------------------------
# restore_db — explicit ZipSlip defense
# ---------------------------------------------------------------------------


class TestRestoreDbZipSlip:
    """``restore_db`` must refuse to process an archive member that escapes
    the extraction directory, even if the stdlib's ``extractall`` mangles
    the filename to stay in-bounds.

    Regression: the defense previously relied entirely on Python 3.6+
    behavior stripping ``..`` components. An explicit post-extract check
    pins the invariant to THIS file, not the stdlib version.
    """

    def test_zipslip_check_is_present(self, db_mod):
        """Verify the explicit check survives future edits."""
        import inspect  # noqa: PLC0415

        src = inspect.getsource(db_mod.restore_db)
        assert "is_relative_to" in src, (
            "ZipSlip defense removed — extractall alone is not a contract"
        )
        assert "escapes the extraction directory" in src


# ---------------------------------------------------------------------------
# exp_dump — chunked base64 encoding
# ---------------------------------------------------------------------------


class TestExpDumpMemory:
    """``exp_dump`` must not materialise the raw dump + encoded output + str
    simultaneously — a 4 GB DB used to peak at ~16 GB before returning.

    Regression: switched from ``b64encode(t.read())`` to a chunk loop.
    """

    def test_dump_is_streamed_in_chunks(self, db_mod, bypass_db_mgmt):
        """Verify the implementation reads in chunks, not one big read()."""
        import ast  # noqa: PLC0415
        import inspect  # noqa: PLC0415

        # Parse the function body so we match actual code, not docstring prose
        # (the docstring mentions the old ``b64encode(t.read())`` form as
        # historical context, which would false-match a substring check).
        tree = ast.parse(inspect.getsource(db_mod.exp_dump))
        reads_with_arg = False
        reads_without_arg = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "read":
                if node.args:
                    reads_with_arg = True
                else:
                    reads_without_arg = True
        assert reads_with_arg, "exp_dump must read in chunks (t.read(CHUNK_SIZE))"
        assert not reads_without_arg, (
            "exp_dump must not call t.read() with no argument — that materialises "
            "the entire dump in memory"
        )

    def test_dump_output_matches_b64encode_of_raw(self, db_mod, bypass_db_mgmt):
        """Correctness: chunked encode must produce the same bytes as the single-call form."""
        import base64  # noqa: PLC0415

        payload = b"hello world " * 1000  # any content > chunk alignment edges

        def fake_dump_db(db_name, stream, backup_format):
            stream.write(payload)

        with (
            patch.object(db_mod, "list_dbs", return_value=["testdb"]),
            patch.object(db_mod, "dump_db", side_effect=fake_dump_db),
        ):
            encoded = db_mod.exp_dump("testdb", "zip")

        assert encoded == base64.b64encode(payload).decode("ascii")

    def test_dump_accepts_backup_format_kwarg(self, db_mod, bypass_db_mgmt):
        """The parameter was renamed from ``format`` (builtin) to ``backup_format``."""
        with (
            patch.object(db_mod, "list_dbs", return_value=["testdb"]),
            patch.object(db_mod, "dump_db"),
        ):
            # Must not TypeError on the new kwarg name
            db_mod.exp_dump("testdb", backup_format="zip")


# ---------------------------------------------------------------------------
# check_db_exposed — shared allowlist gate
# (exp_rename / exp_duplicate_database gates live in their own sections)
# ---------------------------------------------------------------------------


class TestCheckDbExposed:
    """The shared gate raises ``AccessDenied`` for a db outside ``list_dbs(True)``
    and logs a warning naming it; it is a guard (returns None), not a predicate."""

    def test_raises_access_denied_for_unlisted_db(self, db_mod):
        import odoo.exceptions

        with patch.object(db_mod, "list_dbs", return_value=["exposed"]):
            with pytest.raises(odoo.exceptions.AccessDenied):
                db_mod.check_db_exposed("other")

    def test_passes_silently_for_listed_db(self, db_mod):
        with patch.object(db_mod, "list_dbs", return_value=["exposed"]):
            assert db_mod.check_db_exposed("exposed") is None

    def test_logs_warning_with_db_name_before_raising(self, db_mod, caplog):
        import odoo.exceptions

        with (
            patch.object(db_mod, "list_dbs", return_value=["exposed"]),
            caplog.at_level("WARNING", logger="odoo.service.db"),
        ):
            with pytest.raises(odoo.exceptions.AccessDenied):
                db_mod.check_db_exposed("secret_db")
        assert any("secret_db" in m for m in caplog.messages)

    def test_consults_list_dbs_with_force(self, db_mod):
        """Uses ``list_dbs(True)`` so the allowlist is enforced even when
        ``list_db`` is toggled off — the gate can't be bypassed that way."""
        with patch.object(db_mod, "list_dbs", return_value=["exposed"]) as mock_list:
            db_mod.check_db_exposed("exposed")
        mock_list.assert_called_once_with(True)


class TestExpDumpAllowlistGate:
    """``exp_dump`` refuses a source outside the allowlist before dumping."""

    def test_rejects_db_outside_allowlist(self, db_mod, bypass_db_mgmt):
        import odoo.exceptions

        with (
            patch.object(db_mod, "list_dbs", return_value=["exposed"]),
            patch.object(db_mod, "dump_db") as mock_dump,
        ):
            with pytest.raises(odoo.exceptions.AccessDenied):
                db_mod.exp_dump("other", "zip")
        mock_dump.assert_not_called()

    def test_allows_db_inside_allowlist(self, db_mod, bypass_db_mgmt):
        import base64

        payload = b"content" * 500

        def fake_dump_db(db_name, stream, backup_format):
            stream.write(payload)

        with (
            patch.object(db_mod, "list_dbs", return_value=["exposed"]),
            patch.object(db_mod, "dump_db", side_effect=fake_dump_db),
        ):
            encoded = db_mod.exp_dump("exposed", "zip")

        assert encoded == base64.b64encode(payload).decode("ascii")


class TestExpMigrateDatabasesAllowlistGate:
    """``exp_migrate_databases`` rejects the WHOLE call if any db is unexposed,
    before migrating any of them (no partial run)."""

    def test_rejects_when_any_db_outside_allowlist(self, db_mod, bypass_db_mgmt):
        import odoo.exceptions

        with (
            patch.object(db_mod, "list_dbs", return_value=["a", "b"]),
            patch("odoo.modules.registry.Registry.new") as mock_new,
        ):
            with pytest.raises(odoo.exceptions.AccessDenied):
                db_mod.exp_migrate_databases(["a", "c"])
        # Not even the allowed "a" was migrated — the gate rejects up front.
        mock_new.assert_not_called()

    def test_accepts_when_all_in_allowlist(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod, "list_dbs", return_value=["a", "b"]),
            patch("odoo.modules.registry.Registry.new") as mock_new,
        ):
            result = db_mod.exp_migrate_databases(["a", "b"])
        assert result is True
        assert mock_new.call_count == 2

    def test_empty_list_is_noop_success(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod, "list_dbs", return_value=["a"]),
            patch("odoo.modules.registry.Registry.new") as mock_new,
        ):
            result = db_mod.exp_migrate_databases([])
        assert result is True
        mock_new.assert_not_called()


class TestExpRenameAllowlistGate:
    """``exp_rename`` gates ``old_name`` (source) through the allowlist and
    delegates to the ungated ``_rename_database``; ``new_name`` (target) is
    create-like and not checked."""

    def test_rejects_old_name_outside_allowlist(self, db_mod, bypass_db_mgmt):
        import odoo.exceptions

        with (
            patch.object(db_mod, "list_dbs", return_value=["exposed"]),
            patch.object(db_mod, "_rename_database") as mock_inner,
        ):
            with pytest.raises(odoo.exceptions.AccessDenied):
                db_mod.exp_rename("other", "newname")
        mock_inner.assert_not_called()

    def test_passes_through_to_inner_when_exposed(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod, "list_dbs", return_value=["exposed"]),
            patch.object(db_mod, "_rename_database", return_value=True) as mock_inner,
        ):
            result = db_mod.exp_rename("exposed", "newname")
        assert result is True
        mock_inner.assert_called_once_with("exposed", "newname")

    def test_new_name_not_checked_against_allowlist(self, db_mod, bypass_db_mgmt):
        # Only the source is gated; the target need not be exposed (it's new).
        with (
            patch.object(db_mod, "list_dbs", return_value=["exposed"]),
            patch.object(db_mod, "_rename_database", return_value=True) as mock_inner,
        ):
            db_mod.exp_rename("exposed", "brand_new_target")
        mock_inner.assert_called_once_with("exposed", "brand_new_target")

    def test_internal_helper_does_not_consult_allowlist(self, db_mod):
        """``_rename_database`` must never call ``list_dbs`` — the CLI/rollback
        path depends on renaming a source that need not be exposed."""
        with patch.object(db_mod, "list_dbs") as mock_list:
            # Fails fast at validate_db_name (target), proving we got past any
            # would-be gate without ever consulting list_dbs.
            with pytest.raises(ValueError):
                db_mod._rename_database("any_unexposed", "bad name")
        mock_list.assert_not_called()


class TestExpDuplicateAllowlistGate:
    """``exp_duplicate_database`` gates ``db_original_name`` (source) and
    delegates to the ungated ``_duplicate_database``; ``db_name`` (target) is
    create-like and not checked."""

    def test_rejects_source_outside_allowlist(self, db_mod, bypass_db_mgmt):
        import odoo.exceptions

        with (
            patch.object(db_mod, "list_dbs", return_value=["exposed"]),
            patch.object(db_mod, "_duplicate_database") as mock_inner,
        ):
            with pytest.raises(odoo.exceptions.AccessDenied):
                db_mod.exp_duplicate_database("other", "newdb")
        mock_inner.assert_not_called()

    def test_passes_through_to_inner_when_exposed(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod, "list_dbs", return_value=["exposed"]),
            patch.object(
                db_mod, "_duplicate_database", return_value=True
            ) as mock_inner,
        ):
            result = db_mod.exp_duplicate_database(
                "exposed", "newdb", neutralize_database=True
            )
        assert result is True
        mock_inner.assert_called_once_with("exposed", "newdb", True)

    def test_target_name_not_checked_against_allowlist(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod, "list_dbs", return_value=["exposed"]),
            patch.object(
                db_mod, "_duplicate_database", return_value=True
            ) as mock_inner,
        ):
            db_mod.exp_duplicate_database("exposed", "brand_new_target")
        mock_inner.assert_called_once()

    def test_internal_helper_does_not_consult_allowlist(self, db_mod):
        """``_duplicate_database`` must never call ``list_dbs``."""
        with patch.object(db_mod, "list_dbs") as mock_list:
            with pytest.raises(ValueError):
                db_mod._duplicate_database("any_unexposed", "bad name")
        mock_list.assert_not_called()


# ---------------------------------------------------------------------------
# restore_db — cleanup uses internal helper
# ---------------------------------------------------------------------------


class TestRestoreDbCleanupHelper:
    """``restore_db`` rollback path must use ``_drop_database`` directly,
    bypassing the ``@check_db_management_enabled`` decorator that guards
    ``exp_drop``.

    Regression: a runtime toggle of ``list_db`` between the initial
    check and cleanup would orphan the empty database.
    """

    def test_cleanup_uses_internal_drop_helper(self, db_mod):
        """The cleanup path must call ``_drop_database``, not ``exp_drop``.

        The drop is centralised in ``_rollback_new_database`` (shared by
        create/restore/duplicate); pin the invariant there and confirm
        ``restore_db`` routes its rollback through it.
        """
        import inspect  # noqa: PLC0415

        restore_src = inspect.getsource(db_mod.restore_db)
        # restore_db must delegate its cleanup to the shared rollback helper...
        assert "_rollback_new_database(" in restore_src
        # ...and must NOT call the decorated ``exp_drop`` (the list_db re-check
        # race the helper exists to avoid).
        for line in restore_src.splitlines():
            if line.strip().startswith("exp_drop("):
                pytest.fail(
                    f"restore_db cleanup must not use exp_drop: {line.strip()!r}"
                )

        # The shared helper itself must drop via the internal ``_drop_database``.
        helper_src = inspect.getsource(db_mod._rollback_new_database)
        assert "_drop_database(" in helper_src
        for line in helper_src.splitlines():
            if line.strip().startswith("exp_drop("):
                pytest.fail(
                    f"_rollback_new_database must not use exp_drop: {line.strip()!r}"
                )


# ---------------------------------------------------------------------------
# _drop_database — DROP-after-terminate race handling
# ---------------------------------------------------------------------------


class TestDropDatabaseRetry:
    """``_drop_database`` retries DROP on ``ObjectInUse``.

    Regression: a new HTTP request or cron tick can open a connection between
    ``pg_terminate_backend`` and ``DROP DATABASE``. Before the fix, PG's
    ``ObjectInUse`` (sqlstate 55006) surfaced immediately as RuntimeError
    with no retry. The fix re-runs terminate + drop up to 3 times.
    """

    @pytest.fixture()
    def drop_env(self, db_mod, tmp_path):
        """Shared setup: patches list_dbs, Registry, db_connect, filestore."""
        fake_cr = MagicMock()
        fake_cr.__enter__ = MagicMock(return_value=fake_cr)
        fake_cr.__exit__ = MagicMock(return_value=None)
        fake_db = MagicMock()
        fake_db.cursor.return_value = fake_cr

        with ExitStack() as stack:
            stack.enter_context(patch.object(db_mod, "list_dbs", return_value=["x"]))
            stack.enter_context(patch.object(db_mod.odoo.modules.registry.Registry, "delete"))
            stack.enter_context(patch.object(db_mod.odoo.db, "close_db"))
            stack.enter_context(patch("odoo.service.db.odoo.db.db_connect", return_value=fake_db))
            stack.enter_context(patch("odoo.service.db.database_identifier", return_value=""))
            stack.enter_context(patch("odoo.service.db.time.sleep"))
            # filestore() is a method on config, so patch just that attribute
            # leaving the rest of the config object intact.
            stack.enter_context(
                patch(
                    "odoo.service.db.odoo.tools.config.filestore",
                    return_value=str(tmp_path / "nonexistent"),
                    create=True,
                )
            )
            yield fake_cr

    def test_successful_drop_on_first_try(self, db_mod, drop_env):
        """Happy path: drop succeeds on the first try."""
        result = db_mod._drop_database("x")

        assert result is True
        drop_calls = [c for c in drop_env.execute.call_args_list
                      if "DROP DATABASE" in str(c)]
        assert len(drop_calls) == 1

    def test_retries_on_object_in_use_then_succeeds(self, db_mod, drop_env):
        """If the first DROP hits ObjectInUse, retry succeeds."""
        import psycopg  # noqa: PLC0415

        call_log: list[str] = []

        def execute_side_effect(sql, *args, **kwargs):
            call_log.append(str(sql))
            if "DROP DATABASE" in str(sql):
                if sum("DROP DATABASE" in c for c in call_log) == 1:
                    raise psycopg.errors.ObjectInUse("still connected")
            return None

        drop_env.execute.side_effect = execute_side_effect

        result = db_mod._drop_database("x")

        assert result is True
        drops = [c for c in call_log if "DROP DATABASE" in c]
        terminates = [c for c in call_log if "pg_terminate_backend" in c]
        assert len(drops) == 2
        assert len(terminates) == 2

    def test_raises_after_max_retries(self, db_mod, drop_env):
        """If all retries hit ObjectInUse, a RuntimeError surfaces."""
        import psycopg  # noqa: PLC0415

        def execute_side_effect(sql, *args, **kwargs):
            if "DROP DATABASE" in str(sql):
                raise psycopg.errors.ObjectInUse("forever in use")
            return None

        drop_env.execute.side_effect = execute_side_effect

        with pytest.raises(RuntimeError, match="forever in use"):
            db_mod._drop_database("x")


# ---------------------------------------------------------------------------
# DBNAME_PATTERN — single-character names
# ---------------------------------------------------------------------------


class TestDbnamePattern:
    """``DBNAME_PATTERN`` permits any alphanumeric-prefixed, dot/underscore/dash
    name — including single-character names, which PostgreSQL itself accepts.

    Regression: the previous ``+`` quantifier required ≥2 chars, rejecting
    valid names. The fix uses ``*`` to match zero-or-more additional chars.
    """

    @pytest.mark.parametrize("name", ["a", "A", "0", "agromarin", "mdb_1.test-2"])
    def test_accepts_valid_names(self, db_mod, name):
        import re  # noqa: PLC0415

        assert re.match(db_mod.DBNAME_PATTERN, name), name

    @pytest.mark.parametrize("name", ["", "_leading_underscore", ".dotfirst", "-dashfirst"])
    def test_rejects_invalid_names(self, db_mod, name):
        import re  # noqa: PLC0415

        assert not re.match(db_mod.DBNAME_PATTERN, name), name


# ---------------------------------------------------------------------------
# list_db_incompatible — docstring
# ---------------------------------------------------------------------------


class TestListDbIncompatibleDocstring:
    """The docstring had a stray leading quote that leaked into generated docs."""

    def test_docstring_has_no_stray_quote(self, db_mod):
        doc = db_mod.list_db_incompatible.__doc__
        assert doc is not None
        # No stray leading quote character after the triple-quote opener
        assert not doc.lstrip().startswith('"'), f"stray leading quote in docstring: {doc[:40]!r}"


# ---------------------------------------------------------------------------
# exp_change_admin_password — minimum complexity
# ---------------------------------------------------------------------------


class TestAdminPasswordComplexity:
    """The master admin password authorises every destructive DB-level
    operation. Rejecting trivial passwords (<8 chars) reduces the effective
    attack surface from "brute-force short passwords" to "brute-force >=8-char
    passwords"; not a full policy, but a meaningful floor.
    """

    def test_rejects_short_password(self, db_mod):
        with pytest.raises(ValueError, match="at least 8 characters"):
            db_mod.exp_change_admin_password("short")

    def test_rejects_empty_password(self, db_mod):
        with pytest.raises(ValueError, match="at least 8 characters"):
            db_mod.exp_change_admin_password("")

    def test_rejects_non_string(self, db_mod):
        with pytest.raises(TypeError, match="must be a str"):
            db_mod.exp_change_admin_password(12345678)  # type: ignore[arg-type]

    def test_accepts_8_char_password(self, db_mod):
        """Boundary: exactly 8 chars must be accepted."""
        with (
            patch("odoo.service.db.odoo.tools.config.set_admin_password") as mock_set,
            patch("odoo.service.db.odoo.tools.config.save") as mock_save,
        ):
            result = db_mod.exp_change_admin_password("abcdefgh")
        assert result is True
        mock_set.assert_called_once_with("abcdefgh")
        mock_save.assert_called_once_with(["admin_passwd"])


# ---------------------------------------------------------------------------
# exp_rename — DBNAME_PATTERN enforcement
# ---------------------------------------------------------------------------


class TestExpRenameValidation:
    """exp_rename validates new_name against DBNAME_PATTERN at the service
    layer (not just the HTTP controller), so direct RPC callers are also
    protected against names like ``../etc/passwd`` or shell metachars.
    """

    def test_rejects_invalid_new_name(self, db_mod):
        with pytest.raises(ValueError, match="Invalid database name"):
            db_mod._rename_database("old_name", "has spaces")

    def test_rejects_empty_new_name(self, db_mod):
        with pytest.raises(ValueError, match="Invalid database name"):
            db_mod._rename_database("old_name", "")

    def test_rejects_leading_underscore(self, db_mod):
        with pytest.raises(ValueError, match="Invalid database name"):
            db_mod._rename_database("old_name", "_starts_with_underscore")


# ---------------------------------------------------------------------------
# Public-API docstring invariant
# ---------------------------------------------------------------------------


class TestPublicApiDocstrings:
    """Every public ``exp_*`` RPC entry point must have a docstring.

    The fork's coding standard requires docstrings on public methods.
    This test makes the requirement self-enforcing: future ``exp_*``
    additions without a docstring will fail CI.
    """

    def test_all_exp_functions_have_docstrings(self, db_mod):
        missing = []
        for name in dir(db_mod):
            if not name.startswith("exp_"):
                continue
            obj = getattr(db_mod, name)
            if not callable(obj):
                continue
            # Unwrap decorated functions (functools.wraps preserves __doc__
            # on the wrapper, but some decorators don't use wraps — walk
            # __wrapped__ to find the original if needed).
            target = obj
            while hasattr(target, "__wrapped__"):
                target = target.__wrapped__
            if not (obj.__doc__ or target.__doc__):
                missing.append(name)
        assert not missing, f"Public exp_* functions missing docstrings: {missing}"


# ---------------------------------------------------------------------------
# Dispatch dict — public/admin disjointness invariant
# ---------------------------------------------------------------------------


class TestDispatchInvariants:
    """Pin the structural invariants of the unified ``_DISPATCH`` table.

    Replaces the old ``_DISPATCH_PUBLIC`` / ``_DISPATCH_ADMIN`` disjointness
    test: with one dict, no key can be in both "public" and "admin" — that
    bug class is now structurally impossible.  What remains to verify:

    1. Every method that requires the master password actually exists in
       the dispatch table (typo in ``_REQUIRES_MASTER_PASSWORD`` would
       silently disable auth for a method that exists, or enable it for
       a non-existent method).
    2. The dispatch table contains every documented exp_* RPC method we
       intend to expose (catches "added handler, forgot dispatch entry").
    """

    def test_master_password_set_is_subset_of_dispatch(self, db_mod):
        """A method in ``_REQUIRES_MASTER_PASSWORD`` must exist in ``_DISPATCH``."""
        missing = db_mod._REQUIRES_MASTER_PASSWORD - set(db_mod._DISPATCH)
        assert not missing, (
            f"_REQUIRES_MASTER_PASSWORD references non-existent dispatch keys: "
            f"{missing}. Either add the handler to _DISPATCH or remove from the "
            f"auth set."
        )

    def test_known_admin_methods_require_master_password(self, db_mod):
        """The destructive/admin methods must be in ``_REQUIRES_MASTER_PASSWORD``.

        Pin the admin allowlist explicitly so a future PR that adds a new
        ``exp_*`` to ``_DISPATCH`` without thinking about auth fails this test.
        """
        must_require_auth = {
            "create_database",
            "duplicate_database",
            "drop",
            "dump",
            "restore",
            "rename",
            "change_admin_password",
            "migrate_databases",
        }
        missing_auth = must_require_auth - db_mod._REQUIRES_MASTER_PASSWORD
        assert not missing_auth, (
            f"Methods that must require master password but don't: {missing_auth}"
        )

    def test_public_methods_not_password_gated(self, db_mod):
        """Public dispatch endpoints MUST be callable without master password.

        ``list_countries`` reads bundled XML and is invoked by the
        unauthenticated database-creation wizard; ``db_exist``, ``list``,
        ``list_lang``, and ``server_version`` are similarly public. Listing
        any of them in ``_REQUIRES_MASTER_PASSWORD`` causes:

        * ``ValueError`` from ``passwd, *params = []`` when the client sends
          no leading password (the wizard's normal flow), or
        * ``AccessDenied`` when the client sends any non-master password.

        Either failure is a regression from the documented contract that the
        wizard's pre-DB pages reach these endpoints without credentials.
        """
        public_methods = frozenset({
            "db_exist",
            "list",
            "list_lang",
            "server_version",
            "list_countries",
        })
        gated = public_methods & db_mod._REQUIRES_MASTER_PASSWORD
        assert not gated, (
            f"Public dispatch endpoints incorrectly listed in "
            f"_REQUIRES_MASTER_PASSWORD: {sorted(gated)}. These read "
            f"non-sensitive data and are invoked by unauthenticated UI "
            f"and wizard callers."
        )

    def test_dispatch_list_countries_no_password(self, db_mod):
        """End-to-end: dispatch('list_countries', []) must not require a password.

        Regression test for a bug where ``list_countries`` was placed in
        ``_REQUIRES_MASTER_PASSWORD``; calling it via XML-RPC with empty
        params raised ``ValueError: not enough values to unpack``.
        """
        mock_handler = MagicMock(return_value=[["MX", "Mexico"]])
        with patch.object(db_mod, "check_super") as mock_check, \
             patch.dict(db_mod._DISPATCH, {"list_countries": mock_handler}):
            result = db_mod.dispatch("list_countries", [])
        mock_check.assert_not_called()
        mock_handler.assert_called_once_with()
        assert result == [["MX", "Mexico"]]

    def test_no_legacy_dual_dict_remains(self, db_mod):
        """The old ``_DISPATCH_PUBLIC`` / ``_DISPATCH_ADMIN`` symbols are gone.

        Regression-prevention: a future maintainer re-adding the dual dict
        (perhaps copy-pasting from upstream Odoo) would defeat the
        structural-disjointness guarantee of the new single-dict design.
        """
        assert not hasattr(db_mod, "_DISPATCH_PUBLIC"), (
            "_DISPATCH_PUBLIC has been replaced by single _DISPATCH + _REQUIRES_MASTER_PASSWORD"
        )
        assert not hasattr(db_mod, "_DISPATCH_ADMIN"), (
            "_DISPATCH_ADMIN has been replaced by single _DISPATCH + _REQUIRES_MASTER_PASSWORD"
        )

    def test_dispatch_calls_check_super_for_admin_method(self, db_mod):
        """End-to-end: dispatching an admin method must invoke ``check_super``."""
        with patch.object(db_mod, "check_super") as mock_check, \
             patch.object(db_mod, "exp_drop") as mock_drop:
            # Place the patched mock_drop into _DISPATCH so dispatch finds it.
            with patch.dict(db_mod._DISPATCH, {"drop": mock_drop}):
                db_mod.dispatch("drop", ["secret_password", "mydb"])
        mock_check.assert_called_once_with("secret_password")
        mock_drop.assert_called_once_with("mydb")

    def test_dispatch_skips_check_super_for_public_method(self, db_mod):
        """Public methods must NOT call check_super (no leading password arg).

        Patches the handler in ``_DISPATCH`` itself — patching
        ``db_mod.exp_db_exist`` alone does not change what's already
        registered in the dispatch table.  Without this patch, the test
        falls through to a real ``db_connect`` and times out (~30s) on
        a missing database.
        """
        mock_handler = MagicMock(return_value=True)
        with patch.object(db_mod, "check_super") as mock_check, \
             patch.dict(db_mod._DISPATCH, {"db_exist": mock_handler}):
            result = db_mod.dispatch("db_exist", ["mydb"])
        mock_check.assert_not_called()
        mock_handler.assert_called_once_with("mydb")
        assert result is True

    # Master-password handlers whose DB-name argument is a NEW/create-like
    # target (or which take no DB name at all) — nothing to gate against the
    # exposed-databases allowlist. Every OTHER master-password handler acts on
    # an EXISTING database by name and MUST gate it.
    _ALLOWLIST_EXEMPT = frozenset({
        "create_database",  # target is a brand-new name
        "restore",  # target is a brand-new name
        "change_admin_password",  # takes no DB name
    })

    def test_db_name_handlers_gate_through_check_db_exposed(self, db_mod):
        """Every master-password handler acting on an EXISTING DB by name must
        gate it — via ``check_db_exposed`` (the 4 raising handlers) or the
        inline ``list_dbs(True)`` form (``exp_drop``, whose ``-> bool`` contract
        is consumed by the web/CLI drop callers so it can't raise).

        Derived from ``_REQUIRES_MASTER_PASSWORD`` minus ``_ALLOWLIST_EXEMPT``,
        NOT a hardcoded list — so a future ``exp_*`` added to the master-password
        set without a gate (and without an explicit, justified exemption) fails
        this test by default. That is the actual forget-proofing.
        """
        import ast
        import inspect
        import textwrap

        # A real CALL to check_db_exposed (the 4 raising handlers) or list_dbs
        # (exp_drop's inline form) — parsed from the AST, NOT a substring search,
        # so a mere docstring/comment mention (the handlers' own docstrings name
        # check_db_exposed) cannot satisfy the gate check.
        gate_calls = {"check_db_exposed", "list_dbs"}
        missing = []
        for method in db_mod._REQUIRES_MASTER_PASSWORD - self._ALLOWLIST_EXEMPT:
            fn = db_mod._DISPATCH[method]
            # Unwrap @check_db_management_enabled to reach the real body.
            while hasattr(fn, "__wrapped__"):
                fn = fn.__wrapped__
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            calls = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            if not (calls & gate_calls):
                missing.append(method)
        assert not missing, (
            f"master-password handlers acting on an existing DB by name but "
            f"missing an allowlist gate: {sorted(missing)}. Gate via "
            f"check_db_exposed (raise) or list_dbs(True) (exp_drop's form), or "
            f"add to _ALLOWLIST_EXEMPT with a create-like/no-DB-name justification."
        )


# ---------------------------------------------------------------------------
# exp_duplicate_database — rollback on filestore copy failure
# ---------------------------------------------------------------------------


class TestExpDuplicateRollback:
    """``exp_duplicate_database`` must drop the newly-created database when
    the filestore copy (or any post-CREATE step) fails.

    Regression: previously the post-CREATE work ran without a try/except.  A
    ``shutil.copytree`` failure (disk full, permission, source vanished mid-
    copy) left a perfectly valid PG database whose ``ir.attachment`` rows
    pointed at a filestore that was never created — a silent data
    inconsistency that's only noticed when a user opens an attachment.
    """

    @pytest.fixture()
    def duplicate_env(self, db_mod, tmp_path):
        """Patches around exp_duplicate_database so we can inject failures.

        Does NOT depend on ``bypass_db_mgmt`` (which replaces ``config`` with a
        bare dict that lacks ``filestore``).  Instead, leaves the real config
        in place and patches ``filestore`` on it.
        """
        from contextlib import ExitStack  # noqa: PLC0415

        fake_cr = MagicMock()
        fake_cr.__enter__ = MagicMock(return_value=fake_cr)
        fake_cr.__exit__ = MagicMock(return_value=False)
        fake_db = MagicMock()
        fake_db.cursor.return_value = fake_cr

        # Match the lambda below: filestore("source") -> tmp_path/"filestore_source".
        from_fs = tmp_path / "filestore_source"
        from_fs.mkdir()
        (from_fs / "marker.txt").write_text("hello")

        stack = ExitStack()
        # Bypass the @check_db_management_enabled decorator by overriding the
        # specific list_db key only — preserves the rest of the config object.
        stack.enter_context(
            patch.dict(db_mod.odoo.tools.config.options, {"list_db": True})
        )
        stack.enter_context(patch.object(db_mod.odoo.db, "close_db"))
        stack.enter_context(patch("odoo.service.db.odoo.db.db_connect", return_value=fake_db))
        stack.enter_context(patch("odoo.service.db.database_identifier", return_value=""))
        stack.enter_context(patch("odoo.service.db._drop_conn"))
        stack.enter_context(
            patch.object(
                db_mod.odoo.tools.config,
                "filestore",
                side_effect=lambda name: str(tmp_path / f"filestore_{name}"),
                create=True,
            )
        )
        yield {"cr": fake_cr, "stack": stack, "from_fs": from_fs}
        stack.close()

    def test_drops_db_when_filestore_copy_fails(self, db_mod, duplicate_env):
        """A ``shutil.copytree`` failure must trigger ``_drop_database``."""
        # Patch Environment globally — its __new__ asserts isinstance(cr, BaseCursor)
        # which our MagicMock cursor is not.  We don't care about the env behavior
        # here; we only care that the failure path runs the cleanup.
        fake_registry = MagicMock()
        fake_registry.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
        fake_registry.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with duplicate_env["stack"]:
            with patch.object(
                db_mod.odoo.modules.registry.Registry, "new", return_value=fake_registry
            ), patch(
                "odoo.service.db.odoo.api.Environment", return_value=MagicMock()
            ), patch(
                "odoo.service.db.shutil.copytree",
                side_effect=OSError("disk full"),
            ), patch.object(db_mod, "_drop_database") as mock_drop:
                with pytest.raises(OSError, match="disk full"):
                    db_mod._duplicate_database("source", "newdb")

            mock_drop.assert_called_once_with("newdb")

    def test_drops_db_when_registry_init_fails(self, db_mod, duplicate_env):
        """``Registry.new`` failure (any reason) must trigger rollback."""
        with duplicate_env["stack"]:
            with patch.object(
                db_mod.odoo.modules.registry.Registry,
                "new",
                side_effect=RuntimeError("registry boom"),
            ), patch.object(db_mod, "_drop_database") as mock_drop:
                with pytest.raises(RuntimeError, match="registry boom"):
                    db_mod._duplicate_database("source", "newdb")

            mock_drop.assert_called_once_with("newdb")

    def test_drop_failure_does_not_mask_original_error(self, db_mod, duplicate_env):
        """If the rollback itself fails, the ORIGINAL exception must propagate
        (the rollback failure is suppressed).  The user/operator needs to know
        what went wrong before they can fix the orphan database."""
        with duplicate_env["stack"]:
            with patch.object(
                db_mod.odoo.modules.registry.Registry,
                "new",
                side_effect=RuntimeError("original error"),
            ), patch.object(
                db_mod, "_drop_database", side_effect=Exception("drop also failed")
            ):
                with pytest.raises(RuntimeError, match="original error"):
                    db_mod._duplicate_database("source", "newdb")


# ---------------------------------------------------------------------------
# exp_rename — rollback on filestore move failure
# ---------------------------------------------------------------------------


class TestExpRenameRollback:
    """``exp_rename`` must roll back the SQL rename if the filestore move fails.

    Regression: the half-done state ("DB at new_name, filestore at old_name")
    silently serves attachments to the wrong database after a future rename.
    The fix issues an ALTER DATABASE RENAME back to the old name; if THAT
    also fails, both errors are surfaced for manual intervention.
    """

    @pytest.fixture()
    def rename_env(self, db_mod, tmp_path):
        """Setup with a real source filestore and patched DB layer.

        Self-contained: doesn't depend on ``bypass_db_mgmt`` (which replaces
        the config object with a bare dict).
        """
        from contextlib import ExitStack  # noqa: PLC0415

        fake_cr = MagicMock()
        fake_cr.__enter__ = MagicMock(return_value=fake_cr)
        fake_cr.__exit__ = MagicMock(return_value=False)
        fake_db = MagicMock()
        fake_db.cursor.return_value = fake_cr

        # Match the lambda below: filestore("oldname") -> tmp_path/"filestore_oldname".
        old_fs = tmp_path / "filestore_oldname"
        old_fs.mkdir()
        (old_fs / "data.txt").write_text("attachment payload")

        stack = ExitStack()
        stack.enter_context(
            patch.dict(db_mod.odoo.tools.config.options, {"list_db": True})
        )
        stack.enter_context(patch.object(db_mod.odoo.modules.registry.Registry, "delete"))
        stack.enter_context(patch.object(db_mod.odoo.db, "close_db"))
        stack.enter_context(patch("odoo.service.db.odoo.db.db_connect", return_value=fake_db))
        stack.enter_context(patch("odoo.service.db.database_identifier", return_value=""))
        stack.enter_context(patch("odoo.service.db._drop_conn"))
        stack.enter_context(
            patch.object(
                db_mod.odoo.tools.config,
                "filestore",
                side_effect=lambda name: str(tmp_path / f"filestore_{name}"),
                create=True,
            )
        )
        yield {"cr": fake_cr, "stack": stack}
        stack.close()

    def test_rolls_back_db_rename_when_filestore_move_fails(self, db_mod, rename_env):
        """A failed ``shutil.move`` must trigger an ALTER DATABASE RENAME back
        to the old name."""
        with rename_env["stack"]:
            with patch(
                "odoo.service.db.shutil.move", side_effect=OSError("permission denied")
            ):
                with pytest.raises(RuntimeError, match="permission denied"):
                    db_mod._rename_database("oldname", "newname")

        # Two ALTER DATABASE RENAME calls expected: the original one, then
        # the rollback that swaps newname back to oldname.
        rename_calls = [
            c for c in rename_env["cr"].execute.call_args_list
            if "ALTER DATABASE" in str(c)
        ]
        assert len(rename_calls) == 2, (
            f"Expected 2 ALTER DATABASE RENAME calls (forward + rollback), "
            f"got {len(rename_calls)}: {rename_calls}"
        )

    def test_double_failure_surfaces_both_errors(self, db_mod, rename_env):
        """If both filestore move AND the DB rename-back fail, the operator
        needs both error messages to recover manually."""
        # Make the SECOND ALTER DATABASE RENAME (the rollback) also fail.
        rename_call_count = 0

        def execute_side_effect(sql, *args, **kwargs):
            nonlocal rename_call_count
            if "ALTER DATABASE" in str(sql):
                rename_call_count += 1
                if rename_call_count == 2:
                    raise RuntimeError("rollback rename also failed")
            return None

        rename_env["cr"].execute.side_effect = execute_side_effect

        with rename_env["stack"]:
            with patch(
                "odoo.service.db.shutil.move", side_effect=OSError("disk full")
            ):
                with pytest.raises(RuntimeError, match="manual intervention required"):
                    db_mod._rename_database("oldname", "newname")


# ---------------------------------------------------------------------------
# _DROP_DATABASE_MAX_RETRIES — bumped from 3 to 5 with exponential backoff
# ---------------------------------------------------------------------------


class TestDropDatabaseRetryBudget:
    """The retry budget covers the realistic worst-case for a busy DB.

    Regression: a 3-attempt / 0.6s budget consistently failed under load.
    The new budget (5 attempts / 6.2s cumulative) gives a connection holder
    enough time to receive ``pg_terminate_backend``, unwind, and release.
    """

    def test_retry_count_is_at_least_5(self, db_mod):
        assert db_mod._DROP_DATABASE_MAX_RETRIES >= 5, (
            "Lowering the retry count below 5 reintroduces the 'connection "
            "lands in the drop window' failure mode under load."
        )

    def test_backoff_is_exponential(self, db_mod):
        """Each attempt waits longer than the previous one."""
        base = db_mod._DROP_DATABASE_BACKOFF_BASE
        delays = [base * (2 ** (n - 1)) for n in range(1, db_mod._DROP_DATABASE_MAX_RETRIES + 1)]
        assert all(delays[i] < delays[i + 1] for i in range(len(delays) - 1)), (
            f"Backoff is not strictly increasing: {delays}"
        )
        # Cumulative budget — at minimum a few seconds for production
        assert sum(delays) >= 3.0, (
            f"Total backoff budget {sum(delays):.2f}s is too short for a busy DB"
        )


# ---------------------------------------------------------------------------
# exp_list — no redundant list_db pre-check
# ---------------------------------------------------------------------------


class TestExpListNoRedundantCheck:
    """``exp_list`` must rely on ``list_dbs()`` for the ``list_db`` gate.

    Regression-prevention: the prior body re-implemented the same gate as
    ``list_dbs()``.  A future change to ``list_dbs`` (e.g. adding a context
    where it should NOT raise) would silently be subverted by the
    redundant pre-check that ``exp_list`` did itself.
    """

    def test_passthrough_when_list_db_enabled(self, db_mod):
        with patch.object(db_mod, "list_dbs", return_value=["a", "b"]) as mock_list:
            assert db_mod.exp_list() == ["a", "b"]
        mock_list.assert_called_once_with()

    def test_propagates_access_denied_from_list_dbs(self, db_mod):
        from odoo.exceptions import AccessDenied  # noqa: PLC0415

        with patch.object(db_mod, "list_dbs", side_effect=AccessDenied):
            with pytest.raises(AccessDenied):
                db_mod.exp_list()

    def test_document_kwarg_accepted_for_backcompat(self, db_mod):
        """Old XML-RPC clients pass document=True; must not TypeError."""
        with patch.object(db_mod, "list_dbs", return_value=[]):
            # Both call shapes must work
            assert db_mod.exp_list() == []
            assert db_mod.exp_list(document=True) == []


# ---------------------------------------------------------------------------
# _drop_conn — debug logging on suppressed failure
# ---------------------------------------------------------------------------


class TestDropConnLogging:
    """``_drop_conn`` logs at debug level when ``pg_terminate_backend`` fails.

    Regression: the prior bare ``suppress(Exception)`` made permission errors
    invisible — operators investigating "DROP DATABASE keeps hitting
    ObjectInUse" had no way to discover that their PG role lacked
    ``pg_signal_backend`` membership.
    """

    def test_failure_is_logged_at_debug(self, db_mod, caplog):
        import logging  # noqa: PLC0415

        fake_cr = MagicMock()
        fake_cr.execute.side_effect = RuntimeError("permission denied for pg_signal_backend")

        # Force the underlying logger to DEBUG (pytest's caplog attaches a
        # handler but the logger's effective level may still filter records).
        target_logger = logging.getLogger("odoo.service.db")
        prior_level = target_logger.level
        target_logger.setLevel(logging.DEBUG)
        try:
            with caplog.at_level(logging.DEBUG, logger="odoo.service.db"):
                db_mod._drop_conn(fake_cr, "any_db")
        finally:
            target_logger.setLevel(prior_level)

        assert any(
            "pg_terminate_backend failed" in r.message for r in caplog.records
            if r.name == "odoo.service.db"
        ), f"Expected debug log; got records: {[(r.name, r.message) for r in caplog.records]}"

    def test_failure_does_not_propagate(self, db_mod):
        """Exceptions are still swallowed — termination is best-effort."""
        fake_cr = MagicMock()
        fake_cr.execute.side_effect = RuntimeError("anything")
        # Must not raise
        db_mod._drop_conn(fake_cr, "any_db")


# ---------------------------------------------------------------------------
# restore_db — psql must hard-stop on the first SQL error
# ---------------------------------------------------------------------------


class TestRestoreDbOnErrorStop:
    """``psql -f`` exits 0 even when a statement fails, so without
    ``-v ON_ERROR_STOP=1`` a truncated/corrupt dump restores a partially
    populated database and ``r.returncode != 0`` never trips — a silent
    partial restore reported as success.  Pin the flag on the psql call.

    (Empirically: ``psql -q -f bad.sql`` exits 0 while
    ``psql -q -v ON_ERROR_STOP=1 -f bad.sql`` exits 3 on a failing statement.)
    """

    def test_psql_invocation_passes_on_error_stop(
        self, db_mod, bypass_db_mgmt, zip_dump
    ):
        with patch.object(db_mod, "exp_db_exist", return_value=False), \
             patch.object(db_mod, "_create_empty_database"), \
             patch.object(db_mod, "_drop_database"), \
             patch(
                 "odoo.service.db.subprocess.run",
                 return_value=CompletedProcess(args=[], returncode=1, stderr="x"),
             ) as mock_run:
            with pytest.raises(RuntimeError):
                db_mod.restore_db("newdb", zip_dump)

        cmd = mock_run.call_args.args[0]
        assert "-v" in cmd and "ON_ERROR_STOP=1" in cmd, (
            f"psql restore must pass -v ON_ERROR_STOP=1; got {cmd!r}"
        )
        # the option flag and its value must be adjacent in psql's expected order
        assert cmd[cmd.index("-v") + 1] == "ON_ERROR_STOP=1", (
            f"-v must be immediately followed by ON_ERROR_STOP=1; got {cmd!r}"
        )


# ---------------------------------------------------------------------------
# restore_db — db-name validation (parity with create/duplicate/rename)
# ---------------------------------------------------------------------------


class TestRestoreDbNameValidation:
    """``restore_db`` must enforce the same name shape/length as the other
    name-accepting entry points, before creating anything.  Otherwise a 64+
    char name reaches ``CREATE DATABASE`` where PostgreSQL silently truncates
    it to 63 bytes — the footgun ``DBNAME_MAX_LENGTH`` exists to prevent.
    """

    def test_rejects_overlong_name_before_any_side_effect(
        self, db_mod, bypass_db_mgmt
    ):
        with patch.object(db_mod, "exp_db_exist") as mock_exist, \
             patch.object(db_mod, "_create_empty_database") as mock_create:
            with pytest.raises(ValueError, match="63 characters"):
                db_mod.restore_db("a" * 70, "/dev/null")
        # validation happens first: neither the existence check nor the
        # empty-DB creation may run for an invalid name.
        mock_exist.assert_not_called()
        mock_create.assert_not_called()

    def test_rejects_invalid_shape_before_any_side_effect(
        self, db_mod, bypass_db_mgmt
    ):
        with patch.object(db_mod, "exp_db_exist") as mock_exist, \
             patch.object(db_mod, "_create_empty_database") as mock_create:
            with pytest.raises(ValueError, match="must start with"):
                db_mod.restore_db("../etc/passwd", "/dev/null")
        mock_exist.assert_not_called()
        mock_create.assert_not_called()

    def test_valid_name_passes_validation(self, db_mod, bypass_db_mgmt):
        """A well-formed name must NOT be rejected by the new check — the
        guard must reach the existing-DB pre-flight (which we stub to True)."""
        with patch.object(db_mod, "exp_db_exist", return_value=True), \
             patch.object(db_mod, "_create_empty_database"):
            # raises 'already exists' (RuntimeError), NOT ValueError — proving
            # validation accepted the name and execution moved past it.
            with pytest.raises(RuntimeError, match="already exists"):
                db_mod.restore_db("valid_db.name-1", "/dev/null")


# ---------------------------------------------------------------------------
# _retry_terminate_then_ddl — shared DROP/DUPLICATE/RENAME retry primitive
# ---------------------------------------------------------------------------


class TestRetryTerminateThenDdl:
    """The terminate-then-act retry loop shared by drop / duplicate / rename.

    Replaces three copy-pasted loops; pinned directly so the contract
    (retry only on ObjectInUse, propagate everything else, exhaust to
    RuntimeError carrying the last error) is enforced in one place.
    """

    def test_returns_on_first_success(self, db_mod):
        cr = MagicMock()
        run = MagicMock()
        with patch.object(db_mod, "_drop_conn") as drop_conn, \
             patch("odoo.service.db.time.sleep"):
            db_mod._retry_terminate_then_ddl(cr, "db", "OP: db", run)
        run.assert_called_once()
        drop_conn.assert_called_once_with(cr, "db")

    def test_retries_on_object_in_use_then_succeeds(self, db_mod):
        import psycopg  # noqa: PLC0415

        cr = MagicMock()
        run = MagicMock(side_effect=[psycopg.errors.ObjectInUse("busy"), None])
        with patch.object(db_mod, "_drop_conn") as drop_conn, \
             patch("odoo.service.db.time.sleep") as sleep:
            db_mod._retry_terminate_then_ddl(cr, "db", "OP: db", run)
        assert run.call_count == 2
        assert drop_conn.call_count == 2  # re-terminate before each attempt
        sleep.assert_called_once()        # one backoff between the two attempts

    def test_exhaustion_raises_runtimeerror_with_last_error(self, db_mod):
        import psycopg  # noqa: PLC0415

        cr = MagicMock()
        run = MagicMock(side_effect=psycopg.errors.ObjectInUse("forever"))
        with patch.object(db_mod, "_drop_conn"), \
             patch("odoo.service.db.time.sleep"):
            with pytest.raises(RuntimeError, match="forever"):
                db_mod._retry_terminate_then_ddl(cr, "db", "OP: db", run)
        assert run.call_count == db_mod._DROP_DATABASE_MAX_RETRIES

    def test_non_object_in_use_propagates_without_retry(self, db_mod):
        cr = MagicMock()
        run = MagicMock(side_effect=ValueError("hard fail"))
        with patch.object(db_mod, "_drop_conn"), \
             patch("odoo.service.db.time.sleep") as sleep:
            with pytest.raises(ValueError, match="hard fail"):
                db_mod._retry_terminate_then_ddl(cr, "db", "OP: db", run)
        run.assert_called_once()   # no retry on a non-ObjectInUse error
        sleep.assert_not_called()

    def test_no_sleep_after_final_attempt(self, db_mod):
        """On exhaustion the loop runs MAX attempts but sleeps only between them.

        The backoff after the final attempt is dead time — the loop is about to
        exit and raise, so the longest interval would only delay the error for
        no retry.
        """
        import psycopg

        cr = MagicMock()
        run = MagicMock(side_effect=psycopg.errors.ObjectInUse("forever"))
        with patch.object(db_mod, "_drop_conn"), \
             patch("odoo.service.db.time.sleep") as sleep:
            with pytest.raises(RuntimeError):
                db_mod._retry_terminate_then_ddl(cr, "db", "OP: db", run)
        assert run.call_count == db_mod._DROP_DATABASE_MAX_RETRIES
        # No backoff after the last attempt: MAX runs, MAX-1 sleeps.
        assert sleep.call_count == db_mod._DROP_DATABASE_MAX_RETRIES - 1
