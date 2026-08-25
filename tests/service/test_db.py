"""Pure-pytest tests for ``odoo.service.db``.

Covers the database service layer without a live database or Odoo module
loading.

Two classes DO spawn real subprocesses — ``TestDumpStderrDrainIsBounded`` and
``TestDumpStallSigkillEscalation``.  Both assert that a wedged ``pg_dump``
cannot hang the server forever, and neither property survives a mock: the first
needs a grandchild that inherits the stderr pipe and never closes it, the second
needs a child that really ignores ``SIGTERM``.  A stubbed ``Popen`` returns
whatever the stub was told to return, which is the belief under test.

They stay here rather than moving to ``tests/process`` because that suite runs
under ``service_suites.yml``, which is still ``continue-on-error`` — moving them
would drop two denial-of-service guards from a blocking gate to an advisory one.
They cost ~2s of the suite's ~7s; revisit if that stops being worth it.

Run with::

    python -m pytest tests/service/test_db.py -v
"""

import contextlib
import io
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import threading
import warnings
import zipfile
from contextlib import ExitStack
from subprocess import CompletedProcess
from unittest.mock import MagicMock, call, patch

import pytest

from .conftest import fake_pg_connection, fake_pg_cursor


@pytest.fixture(scope="module")
def db_mod():
    """Import ``odoo.service.db`` once per session."""
    # Loaded so `odoo.db.schema` is bound for the monkeypatch in
    # test_create_empty_database_*; `odoo.service.db` does not import it.
    import odoo.db.schema  # noqa: F401  see comment above
    import odoo.service.db as mod

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


class _FlippingListDb(_MockConfig):
    """``config`` whose ``list_db`` is ``True`` once, then ``False``.

    Simulates the flag being turned off — by an operator or a config reload —
    between the ``@check_db_management_enabled`` gate and the rollback that runs
    much later, which is the window the internal-drop rule exists to close.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reads = 0

    def __getitem__(self, key):
        if key == "list_db":
            self.reads += 1
            return self.reads == 1
        return super().__getitem__(key)


@pytest.fixture
def bypass_db_mgmt(db_mod):
    """Patch ``odoo.tools.config`` so the management-enabled decorator passes."""
    import odoo.tools

    with patch.object(odoo.tools, "config", _MockConfig({"list_db": True})):
        yield


@pytest.fixture
def zip_dump():
    """A minimal, valid zip file containing ``dump.sql`` and no filestore."""
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        with zipfile.ZipFile(f, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("dump.sql", "-- empty sql dump\n")
        tmp = f.name
    yield tmp
    pathlib.Path(tmp).unlink()


class TestRestoreDbPreFlight:
    """``restore_db`` rejects a pre-existing database before touching anything."""

    def test_raises_when_db_already_exists(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(
                db_mod.restore, "exp_db_exist", return_value=True
            ) as mock_exist,
            patch.object(db_mod.restore, "_create_empty_database") as mock_create,
        ):
            with pytest.raises(RuntimeError, match="already exists"):
                db_mod.restore_db("already_there", "/dev/null")

        mock_exist.assert_called_once_with("already_there")
        mock_create.assert_not_called()


class TestRestoreDbSubprocessFailure:
    """When the pg command fails, the real stderr must surface and the empty
    database must be cleaned up."""

    def _make_patches(self, db_mod, pg_stderr: str):
        """Return a dict of pre-configured patches for a failing pg run.

        The cleanup path calls the internal ``_drop_database`` helper
        (bypasses the ``list_db`` gate) rather than ``exp_drop``.
        """
        return {
            "exp_db_exist": patch.object(
                db_mod.restore, "exp_db_exist", return_value=False
            ),
            "create_empty": patch.object(db_mod.restore, "_create_empty_database"),
            "drop_database": patch.object(db_mod.lifecycle, "_drop_database"),
            "subprocess_run": patch(
                "odoo.service.db.restore.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=1, stderr=pg_stderr),
            ),
        }

    def test_error_message_includes_pg_stderr(self, db_mod, bypass_db_mgmt, zip_dump):
        pg_msg = 'FATAL: role "odoo" does not exist'
        patches = self._make_patches(db_mod, pg_msg)

        with (
            patches["exp_db_exist"],
            patches["create_empty"],
            patches["drop_database"],
            patches["subprocess_run"],
        ):
            with pytest.raises(RuntimeError, match="FATAL: role"):
                db_mod.restore_db("newdb", zip_dump)

    def test_empty_db_is_dropped_on_pg_failure(self, db_mod, bypass_db_mgmt, zip_dump):
        patches = self._make_patches(db_mod, "pg error detail")

        with (
            patches["exp_db_exist"],
            patches["create_empty"],
            patches["drop_database"] as mock_drop,
            patches["subprocess_run"],
        ):
            with pytest.raises(RuntimeError):
                db_mod.restore_db("newdb", zip_dump)

        mock_drop.assert_called_once_with("newdb")

    def test_pg_stderr_not_swallowed_into_generic_message(
        self, db_mod, bypass_db_mgmt, zip_dump
    ):
        """Regression: before the fix, RuntimeError only said 'Couldn't restore database'
        with no pg detail, making silent failures impossible to diagnose."""
        pg_msg = 'ERROR: column "foo" of relation "bar" does not exist'
        patches = self._make_patches(db_mod, pg_msg)

        with (
            patches["exp_db_exist"],
            patches["create_empty"],
            patches["drop_database"],
            patches["subprocess_run"],
        ):
            with pytest.raises(RuntimeError) as exc_info:
                db_mod.restore_db("newdb", zip_dump)

        assert pg_msg in str(exc_info.value)

    def test_stderr_captured_not_devnull(self, db_mod, bypass_db_mgmt, zip_dump):
        """Regression: before the fix, stderr=subprocess.STDOUT + stdout=DEVNULL
        discarded all pg output. Verify subprocess.run is called with stderr=PIPE."""
        patches = self._make_patches(db_mod, "any error")

        with (
            patches["exp_db_exist"],
            patches["create_empty"],
            patches["drop_database"],
            patches["subprocess_run"] as mock_run,
        ):
            with pytest.raises(RuntimeError):
                db_mod.restore_db("newdb", zip_dump)

        _args, kwargs = mock_run.call_args
        assert kwargs.get("stderr") == subprocess.PIPE, (
            "subprocess.run must capture stderr=PIPE so pg errors are visible"
        )
        assert kwargs.get("stdout") != subprocess.STDOUT, (
            "stdout=subprocess.STDOUT would redirect stderr to /dev/null"
        )

    def test_restore_creates_target_from_bare_template(
        self, db_mod, bypass_db_mgmt, zip_dump
    ):
        """The restore target must be created from template0 with unaccent
        forced indexable — NOT from the configured db_template.  A dump is
        self-contained: any object a populated template pre-creates (e.g.
        orm_signaling_*) collides with the dump's own copy and aborts the
        replay under ON_ERROR_STOP; and pg_dump cannot carry the IMMUTABLE
        marking of unaccent, which the dump's expression indexes may need."""
        patches = self._make_patches(db_mod, "any error")

        with (
            patches["exp_db_exist"],
            patches["create_empty"] as mock_create,
            patches["drop_database"],
            patches["subprocess_run"],
        ):
            with pytest.raises(RuntimeError):
                db_mod.restore_db("newdb", zip_dump)

        mock_create.assert_called_once_with(
            "newdb", template="template0", force_unaccent=True, setup_if_exists=False
        )


class TestRestoreDbCleanupOnAnyFailure:
    """The empty database is dropped even when the failure is not from the pg
    tool — e.g. the zip is unreadable or the registry load fails."""

    def test_empty_db_dropped_when_zip_is_invalid(self, db_mod, bypass_db_mgmt):
        with tempfile.NamedTemporaryFile(suffix=".zip") as f:
            f.write(b"not a zip file at all")
            f.flush()
            invalid_zip = f.name

            with (
                patch.object(db_mod.restore, "exp_db_exist", return_value=False),
                patch.object(db_mod.restore, "_create_empty_database"),
                patch.object(db_mod.lifecycle, "_drop_database") as mock_drop,
            ):
                # Not merely "something raised": a non-zip is treated as a
                # custom-format dump, so the failure must come back as the
                # wrapped RuntimeError carrying pg_restore's own diagnosis.
                # A bare ``pytest.raises(Exception)`` here was satisfied by any
                # AttributeError a refactor might introduce — verified by
                # injecting one, which left this test green.
                with pytest.raises(RuntimeError, match="Couldn't restore database"):
                    db_mod.restore_db("newdb", invalid_zip)

        mock_drop.assert_called_once_with("newdb")

    def test_empty_db_dropped_when_registry_load_fails(
        self, db_mod, bypass_db_mgmt, zip_dump
    ):
        with (
            patch.object(db_mod.restore, "exp_db_exist", return_value=False),
            patch.object(db_mod.restore, "_create_empty_database"),
            patch.object(db_mod.lifecycle, "_drop_database") as mock_drop,
            patch(
                "odoo.service.db.restore.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=0, stderr=""),
            ),
            patch(
                "odoo.modules.registry.Registry.new",
                side_effect=RuntimeError("registry boom"),
            ),
        ):
            with pytest.raises(RuntimeError, match="registry boom"):
                db_mod.restore_db("newdb", zip_dump)

        mock_drop.assert_called_once_with("newdb")


class TestRestoreDbWallClockTimeout:
    """``restore_db`` bounds the psql/pg_restore subprocess with a wall-clock
    timeout, mirroring ``dump_db``.  A stall must surface as a typed
    ``RuntimeError`` and the half-restored database must be dropped — not
    block the worker until the master watchdog SIGKILLs it."""

    def test_timeout_raises_runtimeerror_and_drops_db(
        self, db_mod, bypass_db_mgmt, zip_dump
    ):
        with (
            patch.object(db_mod.restore, "exp_db_exist", return_value=False),
            patch.object(db_mod.restore, "_create_empty_database"),
            patch.object(db_mod.lifecycle, "_drop_database") as mock_drop,
            patch(
                "odoo.service.db.restore.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="psql", timeout=1.0),
            ),
        ):
            with pytest.raises(RuntimeError, match="timeout"):
                db_mod.restore_db("newdb", zip_dump)

        mock_drop.assert_called_once_with("newdb")

    def test_timeout_kwarg_passed_to_subprocess(self, db_mod, bypass_db_mgmt, zip_dump):
        with (
            patch.object(db_mod.restore, "exp_db_exist", return_value=False),
            patch.object(db_mod.restore, "_create_empty_database"),
            patch.object(db_mod.lifecycle, "_drop_database"),
            patch(
                "odoo.service.db.restore.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=1, stderr="x"),
            ) as mock_run,
        ):
            with pytest.raises(RuntimeError):
                db_mod.restore_db("newdb", zip_dump)

        _args, kwargs = mock_run.call_args
        assert kwargs.get("timeout", 0) > 0, (
            "restore subprocess must be bounded by a wall-clock timeout"
        )


class TestDumpDbNameValidation:
    """``dump_db`` validates the database name *before* building the pg_dump
    argv.  Without it, a flag-shaped name (``--version``, ``-x``) is parsed by
    pg_dump as an option rather than a database — argument injection.  The
    custom format path has no ``db_connect`` ahead of it to reject the name,
    so the guard must live in ``dump_db`` itself.

    (``dump`` is the non-zip format's real name — the one the web database
    manager and ``BACKUP_FORMATS`` use; it maps to ``pg_dump --format=c``.)"""

    @pytest.mark.parametrize("bad_name", ["--version", "-x", "bad name", ".hidden"])
    def test_rejects_flag_shaped_name_before_subprocess(
        self, db_mod, bypass_db_mgmt, bad_name
    ):
        with (
            patch("odoo.service.db.dump.subprocess.run") as mock_run,
            patch.object(db_mod.dump, "find_pg_tool") as mock_tool,
        ):
            with pytest.raises(ValueError):
                db_mod.dump_db(bad_name, None, backup_format="dump")
        mock_run.assert_not_called()
        mock_tool.assert_not_called()

    def test_valid_name_reaches_pg_dump_argv(self, db_mod, bypass_db_mgmt):
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return CompletedProcess(args=cmd, returncode=0, stderr=b"")

        with (
            patch("odoo.service.db.dump.subprocess.run", side_effect=fake_run),
            patch.object(db_mod.dump, "find_pg_tool", lambda n: f"/usr/bin/{n}"),
            patch.object(db_mod.dump, "exec_pg_environ", dict),
        ):
            result = db_mod.dump_db("gooddb", None, backup_format="dump")
        if result is not None:
            result.close()
        assert "gooddb" in captured["cmd"]


class TestDbNameValidation:
    """Database name validation is enforced at the service layer, not only the
    HTTP controller, so direct RPC callers are also protected."""

    @pytest.mark.parametrize(
        "bad_name",
        [
            "bad name",
            "-badstart",
            ".badstart",
            "_badstart",
            "",
            "ab!cd",
            "ab/cd",
        ],
    )
    def test_create_rejects_invalid_names(self, db_mod, bypass_db_mgmt, bad_name):
        with patch.object(db_mod.lifecycle, "_create_empty_database") as mock_create:
            with pytest.raises(ValueError, match="Invalid database name"):
                db_mod.exp_create_database(bad_name, False, "en_US")
        mock_create.assert_not_called()

    @pytest.mark.parametrize(
        "good_name",
        [
            "mydb",
            "my-db",
            "my_db",
            "my.db",
            "My_DB-1.0",
            "a1",
        ],
    )
    def test_create_accepts_valid_names(self, db_mod, bypass_db_mgmt, good_name):
        with (
            patch.object(db_mod.lifecycle, "_create_empty_database"),
            patch("odoo.modules.db.initialize_db"),
        ):
            db_mod.exp_create_database(good_name, False, "en_US")

    @pytest.mark.parametrize("bad_name", ["bad name", "-start", "has/slash"])
    def test_duplicate_rejects_invalid_new_name(self, db_mod, bypass_db_mgmt, bad_name):
        with pytest.raises(ValueError, match="Invalid database name"):
            db_mod._duplicate_database("source_db", bad_name)

    # ``DBNAME_PATTERN`` itself is exercised by ``TestDbnamePattern`` below —
    # this class is about the ENTRY POINTS that consult it.  A near-duplicate
    # spot-check lived here, 1200 lines from the real one and with an
    # overlapping-but-different name list, so a pattern change had two places to
    # be reconciled and neither said it was the authority.


class TestRestoreDbTypeCheck:
    """restore_db rejects non-str db argument via TypeError, not assert.

    assert is a no-op under ``python -O`` (optimized mode); production
    deployments commonly use -O, making the original assert useless.
    """

    @pytest.mark.parametrize("bad_arg", [42, None, b"bytes", 2.5, ["list"]])
    def test_raises_type_error(self, db_mod, bypass_db_mgmt, bad_arg):
        with pytest.raises(TypeError, match="db must be a str"):
            db_mod.restore_db(bad_arg, "/dev/null")

    def test_str_passes_type_check(self, db_mod, bypass_db_mgmt):
        """A str argument must get past the type check (fail on DB existence)."""
        with patch.object(db_mod.restore, "exp_db_exist", return_value=True):
            with pytest.raises(RuntimeError, match="already exists"):
                db_mod.restore_db("valid_str", "/dev/null")


class _FakePgDumpPopen:
    """Minimal ``Popen`` stand-in for the streaming pg_dump runner.

    ``_run_pg_dump_streaming`` copies ``stdout`` to the destination, drains
    ``stderr`` on a sibling thread, then ``wait()``s — so a fake only needs
    readable pipes, a return code, and the signal methods the stall timer may
    reach for.
    """

    def __init__(self, returncode: int = 0, stderr: bytes = b"", stdout: bytes = b""):
        self.returncode = returncode
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class TestDumpDbZipStderr:
    """dump_db zip format captures pg_dump stderr so failures are diagnosable.

    Previously stderr=subprocess.STDOUT + stdout=DEVNULL discarded all pg_dump
    diagnostic output; CalledProcessError carried no useful message.

    Driven through ``Popen`` rather than ``subprocess.run``: the zip path streams
    pg_dump's stdout into the archive member instead of staging an uncompressed
    ``dump.sql``.  The property under test is unchanged — a pg_dump failure must
    still surface carrying pg_dump's own stderr text.
    """

    def _patches(self, db_mod, returncode: int, stderr: bytes) -> list:
        mock_db, _mock_cr = fake_pg_connection()
        return [
            patch("odoo.service.db.dump.find_pg_tool", return_value="/usr/bin/pg_dump"),
            patch("odoo.service.db.dump.exec_pg_environ", return_value={}),
            patch("odoo.db.db_connect", return_value=mock_db),
            patch.object(
                db_mod.dump, "dump_db_manifest", return_value={"odoo_dump": "1"}
            ),
            patch(
                "odoo.service.db.dump.subprocess.Popen",
                return_value=_FakePgDumpPopen(returncode=returncode, stderr=stderr),
            ),
        ]

    def test_failure_raises_runtime_error(self, db_mod, bypass_db_mgmt):
        with ExitStack() as stack:
            for p in self._patches(
                db_mod, returncode=1, stderr=b"pg_dump: error: conn failed"
            ):
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
            for p in self._patches(db_mod, returncode=1, stderr=b"err")[:-1]:
                stack.enter_context(p)
            mock_popen = stack.enter_context(
                patch(
                    "odoo.service.db.dump.subprocess.Popen",
                    return_value=_FakePgDumpPopen(returncode=1, stderr=b"err"),
                )
            )
            with pytest.raises(RuntimeError):
                db_mod.dump_db("testdb", None, "zip", with_filestore=False)
        _args, kwargs = mock_popen.call_args
        assert kwargs.get("stderr") == subprocess.PIPE
        assert kwargs.get("stdout") == subprocess.PIPE
        assert kwargs.get("stdout") != subprocess.STDOUT

    def test_zip_pg_dump_no_longer_writes_an_uncompressed_dump_to_disk(
        self, db_mod, bypass_db_mgmt
    ):
        """No ``--file=`` argument: the SQL goes to stdout, into the deflater.

        Staging it on disk first is what made a backup cost temp space
        proportional to the database rather than to the compressed archive.
        """
        with ExitStack() as stack:
            for p in self._patches(db_mod, returncode=0, stderr=b"")[:-1]:
                stack.enter_context(p)
            mock_popen = stack.enter_context(
                patch(
                    "odoo.service.db.dump.subprocess.Popen",
                    return_value=_FakePgDumpPopen(returncode=0, stderr=b""),
                )
            )
            db_mod.dump_db("testdb", None, "zip", with_filestore=False)
        cmd = mock_popen.call_args[0][0]
        assert not any(str(a).startswith("--file=") for a in cmd), cmd


class TestDumpDbZipLargeSqlMember:
    """A ``dump.sql`` past the ZIP64 threshold must still produce an archive.

    Streaming into a member through ``ZipFile.open(..., "w")`` commits the local
    header before any data is read, so — unlike ``ZipFile.write()``, which stats
    its source first — zipfile cannot promote the member to ZIP64 on its own:
    ``_open_to_write`` decides from ``force_zip64`` alone, the declared
    ``file_size`` still being 0.  Without the flag the dump therefore dies at
    member close with "File size too large, try using force_zip64" — but only
    once the database outgrows 4 GiB, and only after the whole dump has already
    run.  ``allowZip64`` on the archive covers the central directory, not this.

    ``ZIP64_LIMIT`` is shrunk rather than dumping 4 GiB of fake SQL:
    ``_ZipWriteFile.close`` reads it as a module global, so a tiny limit drives
    exactly the branch a genuinely oversized dump reaches.
    """

    def _patches(self, db_mod, stdout: bytes, zip64_limit: int) -> list:
        mock_db, _mock_cr = fake_pg_connection()
        return [
            patch("odoo.service.db.dump.find_pg_tool", return_value="/usr/bin/pg_dump"),
            patch("odoo.service.db.dump.exec_pg_environ", return_value={}),
            patch("odoo.db.db_connect", return_value=mock_db),
            patch.object(
                db_mod.dump, "dump_db_manifest", return_value={"odoo_dump": "1"}
            ),
            patch(
                "odoo.service.db.dump.subprocess.Popen",
                return_value=_FakePgDumpPopen(stdout=stdout),
            ),
            patch.object(zipfile, "ZIP64_LIMIT", zip64_limit),
        ]

    def test_sql_member_over_the_zip64_limit_round_trips(self, db_mod, bypass_db_mgmt):
        sql = b"-- oversized dump\n" + b"x" * 4096
        with ExitStack() as stack:
            for p in self._patches(db_mod, sql, zip64_limit=64):
                stack.enter_context(p)
            dump = db_mod.dump_db("testdb", None, "zip", with_filestore=False)
        assert dump is not None
        with dump, zipfile.ZipFile(dump) as zf:
            assert zf.testzip() is None
            assert zf.read("dump.sql") == sql

    def test_sql_member_under_the_limit_is_unaffected(self, db_mod, bypass_db_mgmt):
        """The flag must not disturb the ordinary, comfortably-small case."""
        sql = b"-- small dump\n"
        with ExitStack() as stack:
            for p in self._patches(db_mod, sql, zip64_limit=zipfile.ZIP64_LIMIT):
                stack.enter_context(p)
            dump = db_mod.dump_db("testdb", None, "zip", with_filestore=False)
        assert dump is not None
        with dump, zipfile.ZipFile(dump) as zf:
            assert zf.read("dump.sql") == sql


class TestDumpDbZipManifestBeforeFilestore:
    """The zip dump writes the manifest (which opens a DB cursor) BEFORE the
    filestore ``copytree``, so an unreachable/bogus DB fails fast instead of
    after a potentially multi-GB copy.
    """

    def test_unreachable_db_fails_before_filestore_copy(self, db_mod, tmp_path):
        import psycopg

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
                patch(
                    "odoo.service.db.dump.find_pg_tool", return_value="/usr/bin/pg_dump"
                )
            )
            stack.enter_context(
                patch("odoo.service.db.dump.exec_pg_environ", return_value={})
            )
            stack.enter_context(
                patch(
                    "odoo.db.db_connect", side_effect=psycopg.OperationalError("down")
                )
            )
            copytree = stack.enter_context(
                patch("odoo.service.db.dump.shutil.copytree")
            )
            with pytest.raises(psycopg.OperationalError):
                db_mod.dump_db("testdb", None, "zip", with_filestore=True)
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
        mock_db, _mock_cr = fake_pg_connection()
        return [
            patch("odoo.service.db.dump.find_pg_tool", return_value="/usr/bin/pg_dump"),
            patch("odoo.service.db.dump.exec_pg_environ", return_value={}),
            patch("odoo.db.db_connect", return_value=mock_db),
            patch.object(
                db_mod.dump, "dump_db_manifest", return_value={"odoo_dump": "1"}
            ),
            patch("odoo.service.db.dump.subprocess.run", side_effect=run_side_effect),
        ]

    def test_zip_path_arms_the_wall_clock_stall_timer(self, db_mod, bypass_db_mgmt):
        """The zip path is bounded — now by the streaming runner's stall timer.

        It used to be a ``subprocess.run(timeout=)`` on a blocking pg_dump
        writing ``--file=dump.sql``.  Streaming the SQL into the archive replaced
        that with :func:`_run_pg_dump_streaming`'s ``threading.Timer``, which
        SIGTERMs (then SIGKILLs) a stalled pg_dump.  What must not regress is
        that the ceiling is still ``_pg_dump_total_timeout()``, so assert the
        armed interval rather than the mechanism's shape.  The timer's own
        SIGTERM/SIGKILL escalation is covered against real subprocesses by
        ``TestPgDumpStall*``.
        """
        armed = []

        class _SpyTimer(threading.Timer):
            def __init__(self, interval, function, *a, **kw):
                armed.append(interval)
                super().__init__(interval, function, *a, **kw)

        with ExitStack() as stack:
            for p in self._patches(db_mod, run_side_effect=None)[:-1]:
                stack.enter_context(p)
            stack.enter_context(
                patch(
                    "odoo.service.db.dump.subprocess.Popen",
                    return_value=_FakePgDumpPopen(returncode=0),
                )
            )
            stack.enter_context(patch.object(db_mod.dump.threading, "Timer", _SpyTimer))
            db_mod.dump_db("testdb", None, "zip", with_filestore=False)
        assert armed == [3600.0], (
            "zip-format pg_dump must be bounded by a wall-clock timeout"
        )

    def test_zip_path_timeout_raises_runtime_error(self, db_mod, bypass_db_mgmt):
        """A stalled-and-killed pg_dump on the zip path is a typed RuntimeError."""
        proc = _FakePgDumpPopen(returncode=-15, stderr=b"")

        class _FiringTimer(threading.Timer):
            """Fire the stall callback synchronously, as a real stall would."""

            def start(self):
                self.function()

        with ExitStack() as stack:
            for p in self._patches(db_mod, run_side_effect=None)[:-1]:
                stack.enter_context(p)
            stack.enter_context(
                patch("odoo.service.db.dump.subprocess.Popen", return_value=proc)
            )
            stack.enter_context(
                patch.object(db_mod.dump.threading, "Timer", _FiringTimer)
            )
            with pytest.raises(RuntimeError, match="wall-clock timeout"):
                db_mod.dump_db("testdb", None, "zip", with_filestore=False)
        assert proc.terminated, "a stalled pg_dump must be signalled, not just failed"

    def test_custom_nonstream_timeout_raises_runtime_error(
        self, db_mod, bypass_db_mgmt
    ):
        timeout_exc = subprocess.TimeoutExpired(cmd=["pg_dump"], timeout=3600)
        with ExitStack() as stack:
            for p in self._patches(db_mod, run_side_effect=timeout_exc):
                stack.enter_context(p)
            with pytest.raises(RuntimeError, match="wall-clock timeout"):
                db_mod.dump_db("testdb", None, "dump", with_filestore=False)

    def test_malformed_timeout_env_falls_back_to_default(self, db_mod):
        with patch.dict(os.environ, {"ODOO_PG_DUMP_TOTAL_TIMEOUT": "not-a-number"}):
            assert db_mod.dump._pg_dump_total_timeout() == 3600.0


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
        cmd = [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'dump-bytes')",
        ]
        out = io.BytesIO()
        with patch.dict(os.environ, {"ODOO_PG_DUMP_WAIT_TIMEOUT": "not-a-number"}):
            db_mod.dump._run_pg_dump_streaming(cmd, dict(os.environ), out)
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
                db_mod.dump._run_pg_dump_streaming(
                    cmd, dict(os.environ), _ExplodingStream()
                )


class TestDumpStreamingClosesItsPipes:
    """``_run_pg_dump_streaming`` must close BOTH pipes it opened.

    Only ``proc.stdout`` was closed; ``Popen`` closes neither by itself, so the
    stderr pipe was left to the garbage collector.  On the SUCCESS path
    refcounting hides that (``proc`` dies with the frame), which is why the fd
    count never grew and the only symptom was a ``ResourceWarning`` per dump.

    On the FAILURE path it does not hide it: the raised exception's traceback
    pins this frame — and ``proc`` with it — for as long as the caller holds the
    exception, which is what the HTTP error path and ``_logger.exception`` do.
    Measured on this GIL build before the fix: 10 failed streaming dumps whose
    errors were still referenced retained 10 pipe fds.
    """

    def test_no_resource_warning_and_both_pipes_closed(self, db_mod):
        cmd = [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'dump'); sys.stderr.write('warn')",
        ]
        out = io.BytesIO()
        opened: list = []
        real_popen = subprocess.Popen

        def _tracking_popen(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            opened.append(proc)
            return proc

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            with patch.object(db_mod.dump.subprocess, "Popen", _tracking_popen):
                db_mod.dump._run_pg_dump_streaming(cmd, dict(os.environ), out)

        assert out.getvalue() == b"dump"
        assert len(opened) == 1
        proc = opened[0]
        assert proc.stdout.closed, "stdout pipe left open"
        assert proc.stderr.closed, "stderr pipe left open"
        leaked = [w for w in caught if issubclass(w.category, ResourceWarning)]
        assert not leaked, f"unclosed file(s): {[str(w.message) for w in leaked]}"

    def test_failed_dump_does_not_retain_fds_while_error_is_held(self, db_mod):
        """The failure path is where the leak is actually observable.

        The traceback of the raised error keeps this frame — and the ``Popen``
        — alive for as long as the caller references the exception, so
        refcounting does NOT reclaim the pipe.  This is the real regression
        guard; the success-path test above only catches the ResourceWarning.
        """

        class _ExplodingStream:
            def write(self, _data: bytes) -> int:
                raise RuntimeError("disk-full-during-copy")

        cmd = [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'x' * 100000)",
        ]

        def open_fds():
            return {p.name for p in pathlib.Path(f"/proc/{os.getpid()}/fd").iterdir()}

        held = []
        before = open_fds()
        for _ in range(5):
            try:
                db_mod.dump._run_pg_dump_streaming(
                    cmd, dict(os.environ), _ExplodingStream()
                )
            except RuntimeError as exc:
                held.append(exc)
        retained = open_fds() - before
        assert not retained, (
            f"{len(retained)} fd(s) retained by 5 failed dumps whose errors are "
            f"still referenced"
        )
        assert len(held) == 5


class TestDumpStderrDrainIsBounded:
    """A grandchild holding the stderr pipe must not hang the dump forever.

    The stderr drain thread was joined with NO timeout.  pg_dump's stderr can be
    inherited by a process that outlives it (a wrapper script, a sudo/ssh hop in
    a remote-dump setup), so the drain never sees EOF and the ``finally`` blocked
    indefinitely — silently defeating the wall-clock ceiling this whole function
    is built around, *after* the stall timer had already done its job.
    """

    def test_orphan_holding_stderr_does_not_block_the_dump(
        self, db_mod, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(db_mod.dump, "_STDERR_DRAIN_JOIN_S", 1.0)
        # The grandchild is orphaned to init by design -- that is the condition
        # under test -- so it cannot be reaped by the dump.  It records its pid
        # for the test to kill instead; left to time out on its own it outlives
        # the run and overlaps the next one.
        pidfile = tmp_path / "grandchild.pid"
        grandchild = (
            f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid()));"
            " time.sleep(30)"
        )
        child = (
            "import subprocess, sys\n"
            "sys.stdout.buffer.write(b'dump-bytes'); sys.stdout.buffer.flush()\n"
            f"subprocess.Popen([sys.executable, '-c', {grandchild!r}],"
            " stdout=subprocess.DEVNULL, stderr=sys.stderr)\n"
        )
        cmd = [sys.executable, "-c", child]
        out = io.BytesIO()
        result: dict = {}

        def _run():
            try:
                db_mod.dump._run_pg_dump_streaming(cmd, dict(os.environ), out)
                result["ok"] = True
            except BaseException as exc:
                result["exc"] = exc

        t = threading.Thread(target=_run)
        t.start()
        t.join(timeout=30)
        try:
            assert not t.is_alive(), (
                "streaming dump hung: the stderr drain join is still unbounded"
            )
            assert result.get("ok"), f"dump failed unexpectedly: {result.get('exc')!r}"
            assert out.getvalue() == b"dump-bytes"
        finally:
            with contextlib.suppress(OSError, ValueError):
                os.kill(int(pidfile.read_text()), signal.SIGKILL)


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
        child = (
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "sys.stdout.buffer.write(b'partial'); sys.stdout.buffer.flush()\n"
            "time.sleep(3600)\n"
        )
        cmd = [sys.executable, "-c", child]
        monkeypatch.setattr(db_mod.dump, "_pg_dump_total_timeout", lambda: 0.5)
        monkeypatch.setattr(db_mod.dump, "_STALL_SIGKILL_GRACE_S", 0.5)
        out = io.BytesIO()

        result: dict = {}

        def _run() -> None:
            try:
                db_mod.dump._run_pg_dump_streaming(cmd, dict(os.environ), out)
                result["ok"] = True
            except BaseException as exc:
                result["exc"] = exc

        t = threading.Thread(target=_run)
        t.start()
        t.join(timeout=30)
        assert not t.is_alive(), (
            "streaming dump hung: a SIGTERM-ignoring pg_dump was never SIGKILLed"
        )
        assert isinstance(result.get("exc"), RuntimeError)
        assert "wall-clock timeout" in str(result["exc"])


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

    def test_stream_path_raises_on_nonzero_returncode(self, db_mod, bypass_db_mgmt):
        proc = self._make_mock_proc(b"pg_dump: error: boom", returncode=1)
        with (
            patch("odoo.service.db.dump.find_pg_tool", return_value="/usr/bin/pg_dump"),
            patch("odoo.service.db.dump.exec_pg_environ", return_value={}),
            patch("odoo.service.db.dump.subprocess.Popen", return_value=proc),
        ):
            with pytest.raises(RuntimeError, match="pg_dump failed"):
                db_mod.dump_db("testdb", io.BytesIO(), "dump")

    def test_stream_path_stderr_in_error_message(self, db_mod, bypass_db_mgmt):
        pg_err = b"FATAL: authentication failed for user"
        proc = self._make_mock_proc(pg_err, returncode=1)
        with (
            patch("odoo.service.db.dump.find_pg_tool", return_value="/usr/bin/pg_dump"),
            patch("odoo.service.db.dump.exec_pg_environ", return_value={}),
            patch("odoo.service.db.dump.subprocess.Popen", return_value=proc),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                db_mod.dump_db("testdb", io.BytesIO(), "dump")
        assert "FATAL: authentication failed" in str(exc_info.value)

    def test_stream_path_success_returns_none(self, db_mod, bypass_db_mgmt):
        proc = self._make_mock_proc(b"", returncode=0)
        with (
            patch("odoo.service.db.dump.find_pg_tool", return_value="/usr/bin/pg_dump"),
            patch("odoo.service.db.dump.exec_pg_environ", return_value={}),
            patch("odoo.service.db.dump.subprocess.Popen", return_value=proc),
        ):
            result = db_mod.dump_db("testdb", io.BytesIO(), "dump")
        assert result is None

    def test_no_stream_path_raises_on_nonzero_returncode(self, db_mod, bypass_db_mgmt):
        with (
            patch("odoo.service.db.dump.find_pg_tool", return_value="/usr/bin/pg_dump"),
            patch("odoo.service.db.dump.exec_pg_environ", return_value={}),
            patch(
                "odoo.service.db.dump.subprocess.run",
                return_value=CompletedProcess(
                    args=[], returncode=1, stderr=b"pg error"
                ),
            ),
        ):
            with pytest.raises(RuntimeError, match="pg_dump failed"):
                db_mod.dump_db("testdb", None, "dump")

    def test_no_stream_path_returns_seekable_tempfile(self, db_mod, bypass_db_mgmt):
        """Regression: the old code returned proc.stdout (a pipe), not a seekable file."""
        with (
            patch("odoo.service.db.dump.find_pg_tool", return_value="/usr/bin/pg_dump"),
            patch("odoo.service.db.dump.exec_pg_environ", return_value={}),
            patch(
                "odoo.service.db.dump.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=0, stderr=b""),
            ),
        ):
            result = db_mod.dump_db("testdb", None, "dump")
        assert result is not None, "Must return a file object, not None or proc.stdout"
        assert hasattr(result, "seek"), (
            "Returned object must be seekable (TemporaryFile)"
        )
        result.close()


class TestCheckFaketimeMode:
    """``_check_faketime_mode`` injects a clock-shifting ``public.now()`` SQL
    function — test-only infrastructure that must never fire in production.

    Regression: gated ONLY on the ``ODOO_FAKETIME_TEST_MODE`` env var. An
    accidental export in a systemd unit would have silently corrupted every
    timestamp in the DB. The fix requires BOTH the env var AND ``test_enable``.
    """

    def test_noop_when_env_var_absent(self, db_mod):
        """Without the env var, the function must not touch the DB at all."""
        import os

        import odoo.tools

        os.environ.pop("ODOO_FAKETIME_TEST_MODE", None)
        with (
            patch.object(odoo.tools, "config", {"test_enable": True, "db_name": ["x"]}),
            patch("odoo.service.db.lifecycle.odoo.db.db_connect") as mock_connect,
        ):
            db_mod.lifecycle._check_faketime_mode("x")

        mock_connect.assert_not_called()

    def test_noop_when_test_enable_off_with_env_var(self, db_mod, caplog):
        """Env var set but --test-enable off → refuse, log a warning, no DB write."""
        import odoo.tools

        with (
            patch.dict("os.environ", {"ODOO_FAKETIME_TEST_MODE": "1"}),
            patch.object(
                odoo.tools, "config", {"test_enable": False, "db_name": ["x"]}
            ),
            patch("odoo.service.db.lifecycle.odoo.db.db_connect") as mock_connect,
            caplog.at_level("WARNING", logger="odoo.service.db"),
        ):
            db_mod.lifecycle._check_faketime_mode("x")

        mock_connect.assert_not_called()
        assert any("Refusing to install faketime" in m for m in caplog.messages)

    def test_noop_when_db_not_in_config(self, db_mod):
        """Env var + test_enable, but db not listed: no DB write."""
        import odoo.tools

        with (
            patch.dict("os.environ", {"ODOO_FAKETIME_TEST_MODE": "1"}),
            patch.object(
                odoo.tools, "config", {"test_enable": True, "db_name": ["other"]}
            ),
            patch("odoo.service.db.lifecycle.odoo.db.db_connect") as mock_connect,
        ):
            db_mod.lifecycle._check_faketime_mode("unlisted_db")

        mock_connect.assert_not_called()

    def test_active_when_all_gates_pass(self, db_mod):
        """Env var + test_enable + db listed: the DB write path is taken."""
        import datetime

        import odoo.tools

        fake_now = datetime.datetime(2026, 1, 1)
        fake_db, fake_cursor = fake_pg_connection(
            fetchone_sequence=[(fake_now,), (fake_now,)]
        )

        with (
            patch.dict("os.environ", {"ODOO_FAKETIME_TEST_MODE": "1"}),
            patch.object(odoo.tools, "config", {"test_enable": True, "db_name": ["x"]}),
            patch("odoo.service.db.lifecycle.odoo.db.db_connect", return_value=fake_db),
        ):
            db_mod.lifecycle._check_faketime_mode("x")

        assert any(
            "CREATE OR REPLACE FUNCTION" in str(call_args)
            for call_args in fake_cursor.execute.call_args_list
        )


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
        import psycopg

        import odoo.tools

        fake_db, _fake_cr = fake_pg_connection(
            execute=psycopg.errors.DuplicateDatabase('database "x" already exists')
        )

        with (
            patch.object(odoo.tools, "config", {"db_template": "template0"}),
            patch("odoo.service.db.lifecycle.odoo.db.db_connect", return_value=fake_db),
            patch("odoo.service.db.lifecycle.database_identifier", return_value=""),
            patch("odoo.service.db.lifecycle._check_faketime_mode"),
        ):
            with pytest.raises(db_mod.DatabaseExists, match="already exists"):
                db_mod._create_empty_database("x")

    def test_creation_is_the_first_statement_issued(self, db_mod):
        """``CREATE DATABASE`` *is* the existence check, so nothing may run
        before it.

        Replaces a source-text assertion that ``"FROM pg_database"`` did not
        appear.  That only recognised the one spelling the original bug used —
        a pre-flight written against ``pg_catalog.pg_database``, or as a
        ``datname`` lookup through any other relation, reintroduces exactly the
        same race and would have gone unnoticed.  Observing the statement
        stream catches a pre-flight query however it is written.
        """
        import odoo.tools

        executed = []
        fake_db, _fake_cr = fake_pg_connection(
            execute=lambda sql, *a, **kw: executed.append(str(sql))
        )

        with (
            patch.object(
                odoo.tools,
                "config",
                {"db_template": "template0", "unaccent": False},
            ),
            patch("odoo.service.db.lifecycle.odoo.db.db_connect", return_value=fake_db),
            patch("odoo.service.db.lifecycle.database_identifier", return_value="x"),
            patch("odoo.service.db.lifecycle._check_faketime_mode"),
        ):
            db_mod._create_empty_database("x")

        assert executed, "no SQL was issued at all"
        assert "CREATE DATABASE" in executed[0].upper(), (
            f"a statement ran before CREATE DATABASE, reopening the TOCTOU "
            f"window: {executed[0]!r}"
        )


class TestRestoreDbZipSlip:
    """``restore_db`` must refuse to process an archive member that escapes
    the extraction directory, even if the stdlib's ``extractall`` mangles
    the filename to stay in-bounds.

    Regression: the defense previously relied entirely on Python 3.6+
    behavior stripping ``..`` components. An explicit post-extract check
    pins the invariant to THIS file, not the stdlib version.

    A companion test asserted ``"is_relative_to"`` appeared in
    ``inspect.getsource(restore_db)``.  It was removed: deleting the guard
    already fails all four cases below, so it detected nothing they did not,
    while extracting the loop into a helper — the same refactor this module
    applied to ``_rollback_new_database`` — failed it with the behaviour
    unchanged.
    """

    @pytest.fixture
    def malicious_zip(self):
        """Factory: a zip whose second member has an attacker-chosen name."""
        made = []

        def _make(escaping_name: str) -> str:
            fd = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)  # noqa: SIM115
            with zipfile.ZipFile(fd, "w") as zf:
                zf.writestr("dump.sql", "SELECT 1;")
                zf.writestr(escaping_name, b"payload")
            fd.close()
            made.append(fd.name)
            return fd.name

        yield _make
        for path in made:
            pathlib.Path(path).unlink()

    @pytest.mark.parametrize(
        "escaping_name",
        [
            "../evil.sql",
            "../../etc/cron.d/pwn",
            "filestore/../../../tmp/escape",
            "/abs/evil",
        ],
    )
    def test_escaping_member_is_refused_behaviorally(
        self, db_mod, bypass_db_mgmt, malicious_zip, escaping_name
    ):
        """A real archive member that escapes the extraction dir must raise —
        not merely have a matching string in the source.  Reaches the actual
        namelist() check; ``_create_empty_database`` is stubbed so the guard
        is exercised before any DB/psql work, and ``_drop_database`` records
        that the half-built DB is rolled back."""
        with (
            patch.object(db_mod.restore, "exp_db_exist", return_value=False),
            patch.object(db_mod.restore, "_create_empty_database"),
            patch.object(db_mod.lifecycle, "_drop_database") as mock_drop,
            patch("odoo.service.db.restore.subprocess.run") as mock_run,
        ):
            with pytest.raises(RuntimeError, match="escapes the extraction directory"):
                db_mod.restore_db("newdb", malicious_zip(escaping_name))
            mock_run.assert_not_called()
        mock_drop.assert_called_once_with("newdb")


class TestExpRestoreBase64Decoder:
    """``exp_restore`` decodes a base64 body in fixed chunks, tolerating
    whitespace at any offset (76-col line wraps, leading/trailing blanks).

    Regression: chunk boundaries landing mid-4-char group on a wrapped body
    used to corrupt or crash the decode.  These tests capture the bytes written
    to the temp file (via a stubbed ``restore_db``) and assert an exact
    round-trip — the decoder is the only logic under test, so no DB is needed.
    """

    @staticmethod
    def _decode_via_exp_restore(db_mod, b64_text: str) -> bytes:
        captured = {}

        def _capture(db, dump_file, copy=False, neutralize_database=False):
            captured["bytes"] = pathlib.Path(dump_file).read_bytes()

        with patch.object(db_mod.restore, "restore_db", side_effect=_capture):
            db_mod.exp_restore("dummy", b64_text)
        return captured["bytes"]

    @pytest.mark.parametrize("size", [0, 1, 2, 3, 4, 5, 100, 8192, 8193, 12000])
    def test_clean_base64_round_trips(self, db_mod, bypass_db_mgmt, size):
        import base64

        payload = bytes((i * 7 + 3) % 256 for i in range(size))
        b64 = base64.b64encode(payload).decode("ascii")
        assert self._decode_via_exp_restore(db_mod, b64) == payload

    def test_wrapped_and_padded_whitespace_round_trips(self, db_mod, bypass_db_mgmt):
        """Whitespace injected mid-stream (incl. across the 8192-char chunk
        boundary) and around the body must not corrupt the decoded bytes."""
        import base64

        payload = bytes((i * 13) % 256 for i in range(10000))
        b64 = base64.b64encode(payload).decode("ascii")
        wrapped = "\n".join(b64[i : i + 76] for i in range(0, len(b64), 76))
        wrapped = "  \r\n" + wrapped.replace("A", "A\t", 1) + "\n\n  "
        assert self._decode_via_exp_restore(db_mod, wrapped) == payload


class TestExpDumpMemory:
    """``exp_dump`` must not materialise the raw dump + encoded output + str
    simultaneously — a 4 GB DB used to peak at ~16 GB before returning.

    Regression: switched from ``b64encode(t.read())`` to a chunk loop.
    """

    def test_dump_is_streamed_in_bounded_reads(self, db_mod, bypass_db_mgmt):
        """No single read may pull the whole dump into memory.

        Observes the reads the function actually issues.  The previous version
        walked the AST for a ``read`` call with no argument; ``t.read(-1)``
        slurps the entire file just the same and has an argument, so the
        regression could return in the one spelling the check could not see —
        verified against this test.
        """

        def read_sizes_for(dump_bytes):
            sizes = []
            real_tempfile = tempfile.TemporaryFile

            def instrumented(*args, **kwargs):
                handle = real_tempfile(*args, **kwargs)
                real_read = handle.read

                def read(size=-1, /):
                    sizes.append(size)
                    return real_read(size)

                handle.read = read
                return handle

            def fake_dump_db(db_name, stream, backup_format):
                stream.write(b"x" * dump_bytes)

            with (
                patch("odoo.service.db.dump.tempfile.TemporaryFile", instrumented),
                patch.object(db_mod.dump, "dump_db", fake_dump_db),
                patch.object(db_mod.dump, "check_db_exposed"),
            ):
                db_mod.exp_dump("mydb", "zip")
            return sizes

        small = read_sizes_for(4 * 1024 * 1024)
        large = read_sizes_for(16 * 1024 * 1024)

        assert small and large, "exp_dump issued no read at all"
        assert all(size > 0 for size in small + large), (
            f"exp_dump asked for an unbounded read: {small + large!r}. "
            f"``read(-1)`` materialises the whole dump exactly like ``read()``"
        )
        assert max(small) == max(large), (
            f"read size scales with dump size ({max(small)} -> {max(large)}); it "
            f"must be a fixed chunk, or peak memory grows with the database"
        )
        assert len(large) > len(small), (
            "a four-times-larger dump must take more reads, not bigger ones"
        )

    def test_dump_output_matches_b64encode_of_raw(self, db_mod, bypass_db_mgmt):
        """Correctness: chunked encode must produce the same bytes as the single-call form."""
        import base64

        payload = b"hello world " * 1000

        def fake_dump_db(db_name, stream, backup_format):
            stream.write(payload)

        with (
            patch.object(db_mod.listing, "list_dbs", return_value=["testdb"]),
            patch.object(db_mod.dump, "dump_db", side_effect=fake_dump_db),
        ):
            encoded = db_mod.exp_dump("testdb", "zip")

        assert encoded == base64.b64encode(payload).decode("ascii")

    def test_dump_accepts_backup_format_kwarg(self, db_mod, bypass_db_mgmt):
        """The parameter was renamed from ``format`` (builtin) to ``backup_format``."""
        with (
            patch.object(db_mod.listing, "list_dbs", return_value=["testdb"]),
            patch.object(db_mod.dump, "dump_db"),
        ):
            db_mod.exp_dump("testdb", backup_format="zip")


class TestCheckDbExposed:
    """The shared gate raises ``AccessDenied`` for a db outside ``list_dbs(True)``
    and logs a warning naming it; it is a guard (returns None), not a predicate."""

    def test_raises_access_denied_for_unlisted_db(self, db_mod):
        import odoo.exceptions

        with patch.object(db_mod.listing, "list_dbs", return_value=["exposed"]):
            with pytest.raises(odoo.exceptions.AccessDenied):
                db_mod.check_db_exposed("other")

    def test_passes_silently_for_listed_db(self, db_mod):
        with patch.object(db_mod.listing, "list_dbs", return_value=["exposed"]):
            assert db_mod.check_db_exposed("exposed") is None

    def test_logs_warning_with_db_name_before_raising(self, db_mod, caplog):
        import odoo.exceptions

        with (
            patch.object(db_mod.listing, "list_dbs", return_value=["exposed"]),
            caplog.at_level("WARNING", logger="odoo.service.db"),
        ):
            with pytest.raises(odoo.exceptions.AccessDenied):
                db_mod.check_db_exposed("secret_db")
        assert any("secret_db" in m for m in caplog.messages)

    def test_consults_list_dbs_with_force(self, db_mod):
        """Uses ``list_dbs(True)`` so the allowlist is enforced even when
        ``list_db`` is toggled off — the gate can't be bypassed that way."""
        with patch.object(
            db_mod.listing, "list_dbs", return_value=["exposed"]
        ) as mock_list:
            db_mod.check_db_exposed("exposed")
        mock_list.assert_called_once_with(True)


class TestListDbsConfiguredNamesAreAnAssertion:
    """``-d`` is an operator assertion, not a check that the database exists.

    With ``db_name`` set and no ``dbfilter``, ``list_dbs`` returns the configured
    names verbatim and never touches ``pg_database`` -- the fast path exists so a
    pinned deployment needs no connection to ``postgres`` to answer at all. The
    consequence is that ``check_db_exposed`` admits a name whose database was
    dropped. That is inherited upstream behaviour and deliberate; these tests
    pin the contract so the next reader does not have to re-derive which gate is
    loose and which is not.
    """

    def test_configured_names_are_returned_without_consulting_the_catalogue(
        self, db_mod
    ):
        import odoo.db

        with (
            patch.object(
                odoo.tools,
                "config",
                {
                    "list_db": True,
                    "dbfilter": "",
                    "db_name": ["definitely_not_a_db_xyz"],
                },
            ),
            patch.object(odoo.db, "db_connect") as connect,
        ):
            assert db_mod.list_dbs(True) == ["definitely_not_a_db_xyz"]
        connect.assert_not_called()

    def test_check_db_exposed_admits_a_configured_name_that_no_longer_exists(
        self, db_mod
    ):
        import odoo.db

        with (
            patch.object(
                odoo.tools,
                "config",
                {
                    "list_db": True,
                    "dbfilter": "",
                    "db_name": ["definitely_not_a_db_xyz"],
                },
            ),
            patch.object(odoo.db, "db_connect") as connect,
        ):
            assert db_mod.check_db_exposed("definitely_not_a_db_xyz") is None
            # ...and a real database that is NOT in -d is still refused.
            with pytest.raises(odoo.exceptions.AccessDenied):
                db_mod.check_db_exposed("some_other_real_db")
        connect.assert_not_called()

    def test_rpc_db_exist_does_not_inherit_that_looseness(self, db_mod):
        """It ends at ``exp_db_exist``, which opens a connection, so a dead name
        answers False even though it passes the membership test."""
        import odoo.tools

        with (
            patch.object(
                odoo.tools,
                "config",
                {
                    "list_db": True,
                    "dbfilter": "",
                    "db_name": ["definitely_not_a_db_xyz"],
                    "db_template": "template0",
                },
            ),
            patch.object(db_mod.listing, "exp_db_exist", return_value=False) as exists,
        ):
            assert db_mod.listing._rpc_db_exist("definitely_not_a_db_xyz") is False
        exists.assert_called_once_with("definitely_not_a_db_xyz")


class TestExpDumpAllowlistGate:
    """``exp_dump`` refuses a source outside the allowlist before dumping."""

    def test_rejects_db_outside_allowlist(self, db_mod, bypass_db_mgmt):
        import odoo.exceptions

        with (
            patch.object(db_mod.listing, "list_dbs", return_value=["exposed"]),
            patch.object(db_mod.dump, "dump_db") as mock_dump,
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
            patch.object(db_mod.listing, "list_dbs", return_value=["exposed"]),
            patch.object(db_mod.dump, "dump_db", side_effect=fake_dump_db),
        ):
            encoded = db_mod.exp_dump("exposed", "zip")

        assert encoded == base64.b64encode(payload).decode("ascii")


class TestExpMigrateDatabasesAllowlistGate:
    """``exp_migrate_databases`` rejects the WHOLE call if any db is unexposed,
    before migrating any of them (no partial run)."""

    def test_rejects_when_any_db_outside_allowlist(self, db_mod, bypass_db_mgmt):
        import odoo.exceptions

        with (
            patch.object(db_mod.listing, "list_dbs", return_value=["a", "b"]),
            patch("odoo.modules.registry.Registry.new") as mock_new,
        ):
            with pytest.raises(odoo.exceptions.AccessDenied):
                db_mod.exp_migrate_databases(["a", "c"])
        mock_new.assert_not_called()

    def test_accepts_when_all_in_allowlist(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod.listing, "list_dbs", return_value=["a", "b"]),
            patch("odoo.modules.registry.Registry.new") as mock_new,
        ):
            result = db_mod.exp_migrate_databases(["a", "b"])
        assert result is True
        assert mock_new.call_count == 2

    def test_empty_list_is_noop_success(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod.listing, "list_dbs", return_value=["a"]),
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
            patch.object(db_mod.listing, "list_dbs", return_value=["exposed"]),
            patch.object(db_mod.lifecycle, "_rename_database") as mock_inner,
        ):
            with pytest.raises(odoo.exceptions.AccessDenied):
                db_mod.exp_rename("other", "newname")
        mock_inner.assert_not_called()

    def test_passes_through_to_inner_when_exposed(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod.listing, "list_dbs", return_value=["exposed"]),
            patch.object(
                db_mod.lifecycle, "_rename_database", return_value=True
            ) as mock_inner,
        ):
            result = db_mod.exp_rename("exposed", "newname")
        assert result is True
        mock_inner.assert_called_once_with("exposed", "newname")

    def test_new_name_not_checked_against_allowlist(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod.listing, "list_dbs", return_value=["exposed"]),
            patch.object(
                db_mod.lifecycle, "_rename_database", return_value=True
            ) as mock_inner,
        ):
            db_mod.exp_rename("exposed", "brand_new_target")
        mock_inner.assert_called_once_with("exposed", "brand_new_target")

    def test_internal_helper_does_not_consult_allowlist(self, db_mod):
        """``_rename_database`` must never call ``list_dbs`` — the CLI/rollback
        path depends on renaming a source that need not be exposed."""
        with patch.object(db_mod.listing, "list_dbs") as mock_list:
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
            patch.object(db_mod.listing, "list_dbs", return_value=["exposed"]),
            patch.object(db_mod.lifecycle, "_duplicate_database") as mock_inner,
        ):
            with pytest.raises(odoo.exceptions.AccessDenied):
                db_mod.exp_duplicate_database("other", "newdb")
        mock_inner.assert_not_called()

    def test_passes_through_to_inner_when_exposed(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod.listing, "list_dbs", return_value=["exposed"]),
            patch.object(
                db_mod.lifecycle, "_duplicate_database", return_value=True
            ) as mock_inner,
        ):
            result = db_mod.exp_duplicate_database(
                "exposed", "newdb", neutralize_database=True
            )
        assert result is True
        mock_inner.assert_called_once_with("exposed", "newdb", True)

    def test_target_name_not_checked_against_allowlist(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod.listing, "list_dbs", return_value=["exposed"]),
            patch.object(
                db_mod.lifecycle, "_duplicate_database", return_value=True
            ) as mock_inner,
        ):
            db_mod.exp_duplicate_database("exposed", "brand_new_target")
        mock_inner.assert_called_once()

    def test_internal_helper_does_not_consult_allowlist(self, db_mod):
        """``_duplicate_database`` must never call ``list_dbs``."""
        with patch.object(db_mod.listing, "list_dbs") as mock_list:
            with pytest.raises(ValueError):
                db_mod._duplicate_database("any_unexposed", "bad name")
        mock_list.assert_not_called()


class TestRestoreDbCleanupHelper:
    """``restore_db`` rollback path must use ``_drop_database`` directly,
    bypassing the ``@check_db_management_enabled`` decorator that guards
    ``exp_drop``.

    Regression: a runtime toggle of ``list_db`` between the initial
    check and cleanup would orphan the empty database.
    """

    def test_rollback_survives_list_db_being_turned_off_mid_restore(
        self, db_mod, zip_dump
    ):
        """The regression, driven rather than read.

        ``list_db`` reads ``True`` at ``restore_db``'s gate and ``False``
        everywhere after — an operator flipping the flag, or a config reload,
        during a long restore.  A rollback routed through ``exp_drop`` re-enters
        ``@check_db_management_enabled``, raises ``AccessDenied`` inside the
        cleanup, and leaves the half-built database behind forever.

        Replaces a pair of ``inspect.getsource`` scans for the literal
        ``exp_drop(`` at the start of a line.  Those missed any call not written
        flush against the indent — ``rc = exp_drop(name)``, a wrapper, an alias —
        and said nothing about whether the rollback actually completes.
        """
        config = _FlippingListDb({"list_db": True})
        import odoo.tools

        with (
            patch.object(odoo.tools, "config", config),
            patch.object(db_mod.restore, "exp_db_exist", return_value=False),
            patch.object(db_mod.restore, "_create_empty_database"),
            patch.object(db_mod.lifecycle, "_drop_database") as mock_drop,
            patch(
                "odoo.service.db.restore.subprocess.run",
                side_effect=OSError("psql gone"),
            ),
        ):
            with pytest.raises(OSError, match="psql gone"):
                db_mod.restore_db("halfbuilt", zip_dump)

        mock_drop.assert_called_once_with("halfbuilt")
        assert config.reads == 1, (
            f"list_db was consulted {config.reads} times; the rollback re-entered "
            f"a gated verb instead of calling _drop_database directly"
        )

    def test_rollback_does_not_re_enter_the_rpc_verb(self, db_mod, zip_dump):
        """``exp_drop`` is the gated RPC entry point; the internal rollback must
        not call it even when the gate would currently pass."""
        with (
            patch.object(db_mod.restore, "exp_db_exist", return_value=False),
            patch.object(db_mod.restore, "_create_empty_database"),
            patch.object(db_mod.lifecycle, "_drop_database") as mock_drop,
            patch.object(db_mod.lifecycle, "exp_drop") as mock_exp_drop,
            patch(
                "odoo.service.db.restore.subprocess.run",
                side_effect=OSError("psql gone"),
            ),
            patch.object(
                __import__("odoo.tools", fromlist=["config"]),
                "config",
                _MockConfig({"list_db": True}),
            ),
        ):
            with pytest.raises(OSError, match="psql gone"):
                db_mod.restore_db("halfbuilt", zip_dump)

        mock_drop.assert_called_once_with("halfbuilt")
        mock_exp_drop.assert_not_called()


class TestDropDatabaseRetry:
    """``_drop_database`` retries DROP on ``ObjectInUse``.

    Regression: a new HTTP request or cron tick can open a connection between
    ``pg_terminate_backend`` and ``DROP DATABASE``. Before the fix, PG's
    ``ObjectInUse`` (sqlstate 55006) surfaced immediately as RuntimeError
    with no retry. The fix re-runs terminate + drop up to 3 times.
    """

    @pytest.fixture
    def drop_env(self, db_mod, tmp_path):
        """Shared setup: patches list_dbs, Registry, db_connect, filestore.

        ``fetchone=(1,)`` answers ``_drop_database``'s existence probe
        (``SELECT 1 FROM pg_database WHERE datname = %s``) with "yes, it is
        there" — the premise of every test below, all of which are about what
        happens while dropping a database that EXISTS.  It used to be supplied
        by accident: a bare ``MagicMock().fetchone()`` returns a truthy mock, so
        the probe passed without anyone saying so, and the same accident is what
        let a stray pre-flight ``SELECT`` elsewhere in this module read as
        "database already exists".
        """
        fake_db, fake_cr = fake_pg_connection(fetchone=(1,))

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(db_mod.listing, "list_dbs", return_value=["x"])
            )
            stack.enter_context(
                patch.object(db_mod.lifecycle.odoo.modules.registry.Registry, "delete")
            )
            stack.enter_context(patch.object(db_mod.lifecycle.odoo.db, "close_db"))
            stack.enter_context(
                patch(
                    "odoo.service.db.lifecycle.odoo.db.db_connect", return_value=fake_db
                )
            )
            stack.enter_context(
                patch("odoo.service.db.lifecycle.database_identifier", return_value="")
            )
            stack.enter_context(patch("odoo.service.db.lifecycle.time.sleep"))
            stack.enter_context(
                patch(
                    "odoo.service.db.lifecycle.odoo.tools.config.filestore",
                    return_value=str(tmp_path / "nonexistent"),
                    create=True,
                )
            )
            yield fake_cr

    def test_successful_drop_on_first_try(self, db_mod, drop_env):
        """Happy path: drop succeeds on the first try."""
        result = db_mod._drop_database("x")

        assert result is True
        drop_calls = [
            c for c in drop_env.execute.call_args_list if "DROP DATABASE" in str(c)
        ]
        assert len(drop_calls) == 1

    def test_absent_database_returns_false_without_dropping(self, db_mod, drop_env):
        """An existence probe that finds nothing means ``False``, not a DROP.

        This is the branch ``exp_drop``'s whole contract rests on:
        ``TestExpDropGate.test_false_now_means_only_that_the_database_was_absent``
        pins that ``False`` has exactly ONE meaning, but it patches
        ``_drop_database`` wholesale, so nothing checked that the helper actually
        produces ``False`` for an absent name — or that it stops there instead of
        issuing DDL against a database it just failed to find.

        Verified by mutation: deleting ``if owner_row is None: return False``
        left the entire suite green.  It was invisible for the same reason the
        rest of this fixture's premise was — a bare ``MagicMock().fetchone()`` is
        truthy, so "the database exists" was the only case any test could reach.
        """
        drop_env.fetchone.return_value = None

        result = db_mod._drop_database("gone")

        assert result is False
        assert not [
            c for c in drop_env.execute.call_args_list if "DROP DATABASE" in str(c)
        ], "issued DROP DATABASE against a database the probe said was absent"

    def test_retries_on_object_in_use_then_succeeds(self, db_mod, drop_env):
        """If the first DROP hits ObjectInUse, retry succeeds."""
        import psycopg

        call_log: list[str] = []

        def execute_side_effect(sql, *args, **kwargs):
            call_log.append(str(sql))
            if "DROP DATABASE" in str(sql):
                if sum("DROP DATABASE" in c for c in call_log) == 1:
                    raise psycopg.errors.ObjectInUse("still connected")

        drop_env.execute.side_effect = execute_side_effect

        result = db_mod._drop_database("x")

        assert result is True
        drops = [c for c in call_log if "DROP DATABASE" in c]
        terminates = [c for c in call_log if "pg_terminate_backend" in c]
        assert len(drops) == 2
        assert len(terminates) == 2

    def test_raises_after_max_retries(self, db_mod, drop_env):
        """If all retries hit ObjectInUse, a RuntimeError surfaces."""
        import psycopg

        def execute_side_effect(sql, *args, **kwargs):
            if "DROP DATABASE" in str(sql):
                raise psycopg.errors.ObjectInUse("forever in use")

        drop_env.execute.side_effect = execute_side_effect

        with pytest.raises(RuntimeError, match="forever in use"):
            db_mod._drop_database("x")


class TestDbnamePattern:
    """``DBNAME_PATTERN`` permits any alphanumeric-prefixed, dot/underscore/dash
    name — including single-character names, which PostgreSQL itself accepts.

    Regression: the previous ``+`` quantifier required ≥2 chars, rejecting
    valid names. The fix uses ``*`` to match zero-or-more additional chars.

    The SOLE authority on the pattern itself.  ``TestDbNameValidation`` used to
    carry a second spot-check with its own name list; the two had to be kept in
    step by hand and neither claimed precedence.  Names from both lists are
    merged here — every entry-point test now asserts only on the refusal it
    produces, not on the regex.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "a",
            "A",
            "0",
            "a1",
            "agromarin",
            "mydb",
            "my-db",
            "my_db",
            "my.db",
            "My_DB-1.0",
            "mdb_1.test-2",
        ],
    )
    def test_accepts_valid_names(self, db_mod, name):
        import re

        assert re.match(db_mod.DBNAME_PATTERN, name), name

    @pytest.mark.parametrize(
        "name", ["", "_leading_underscore", ".dotfirst", "-dashfirst"]
    )
    def test_rejects_invalid_names(self, db_mod, name):
        import re

        assert not re.match(db_mod.DBNAME_PATTERN, name), name


class TestListDbIncompatibleDocstring:
    """The docstring had a stray leading quote that leaked into generated docs."""

    def test_docstring_has_no_stray_quote(self, db_mod):
        doc = db_mod.list_db_incompatible.__doc__
        assert doc is not None
        assert not doc.lstrip().startswith('"'), (
            f"stray leading quote in docstring: {doc[:40]!r}"
        )


class TestValidateDbNameLengthBoundary:
    """``DBNAME_MAX_LENGTH`` is a CEILING, not a forbidden value.

    PostgreSQL stores ``datname`` as a 63-byte ``name``, silently truncating
    anything longer — which is the whole reason this guard exists.  So 63 must
    be ACCEPTED and 64 refused, and the guard is ``len(name) > MAX``.

    Found by mutation: flipping that to ``>=`` — which rejects every name of
    exactly the legal maximum — left the whole suite green.  The only length
    test used ``"a" * 70``, so it could not see either side of the boundary.
    """

    def test_exactly_the_maximum_is_accepted(self, db_mod):
        name = "a" * db_mod.DBNAME_MAX_LENGTH
        db_mod.validate_db_name(name)  # must not raise

    def test_one_over_the_maximum_is_refused(self, db_mod):
        name = "a" * (db_mod.DBNAME_MAX_LENGTH + 1)
        with pytest.raises(ValueError, match="63 characters"):
            db_mod.validate_db_name(name)

    def test_the_length_check_runs_before_the_regex(self, db_mod):
        """An over-long name is rejected for its LENGTH even when its shape is
        also invalid — the length test is O(1) and deliberately first, so a
        degenerate input is not walked by the regex."""
        with pytest.raises(ValueError, match="63 characters"):
            db_mod.validate_db_name("-" * 5000)


class TestRpcDbExposedGate:
    """``rpc_db_exposed`` is the shared gate every RPC verb consults before
    ``Registry(db)`` builds a registry and a pool for an unauthenticated caller.

    Its argument is typed ``object`` precisely because it comes off the wire, so
    the non-``str``/empty guard is load-bearing.  Nothing tested the gate
    DIRECTLY: ``common.exp_authenticate`` and ``model.dispatch`` each carry their
    own copy of the same check, so the callers' tests pass whatever this
    function does — ``TestExpAuthenticateArgumentTypes`` says as much about its
    own ``db`` case ("an EQUIVALENT mutation ... it fails if BOTH are removed").

    Confirmed by mutation: turning ``or`` into ``and`` on the guard, and making
    it ``return True`` for a non-string, both left the suite green.  These pin
    the gate itself, so the two layers can no longer only be tested together.
    """

    @pytest.fixture
    def gate(self):
        from odoo.service._db_helpers import rpc_db_exposed

        return rpc_db_exposed

    @pytest.mark.parametrize(
        "db_name", [None, 42, 4.0, True, b"bytes", ["db"], {"db": 1}, object()]
    )
    def test_a_non_string_is_never_exposed(self, gate, db_name):
        assert gate(db_name) is False

    def test_the_empty_string_is_never_exposed(self, gate):
        assert gate("") is False

    @pytest.mark.parametrize("db_name", ["postgres", "template0", "template1"])
    def test_system_databases_are_never_exposed(self, gate, db_name):
        assert gate(db_name) is False

    def test_the_configured_template_is_never_exposed(self, db_mod, gate):
        from odoo.tools import config

        with config.patch(db_template="tpl_custom", db_name=[]):
            assert gate("tpl_custom") is False

    def test_database_option_acts_as_the_allowlist(self, gate):
        from odoo.tools import config

        with config.patch(db_name=["served"]):
            assert gate("served") is True
            assert gate("other") is False

    def test_every_ordinary_name_is_exposed_when_no_allowlist_is_set(self, gate):
        from odoo.tools import config

        with config.patch(db_name=[]):
            assert gate("anything") is True


class TestAdminGates:
    """``check_super`` and ``check_db_management_enabled`` — the two gates every
    destructive database verb passes through.

    Both live in ``odoo/service/_db_helpers.py`` and are re-exported by
    ``odoo.service.db``.  These tests were filed in ``test_server.py``, which is
    where their only coverage sat: removing them there dropped ``_db_helpers``
    from 98% to 87%, and nobody looking for the tests of two admin-auth gates
    would have grepped a file about the HTTP server.
    """

    def test_correct_master_password_passes(self, db_mod):
        import odoo.tools

        with patch.object(
            odoo.tools.config, "verify_admin_password", return_value=True
        ) as verify:
            assert db_mod.check_super("correct") is True
        # The gate must hand the verifier the password it was GIVEN.  Both tests
        # here stub the verifier, so without this the ARGUMENT is unobserved and
        # `verify_admin_password(passwd)` -> `verify_admin_password("")` passes
        # the whole suite (verified by mutation).
        verify.assert_called_once_with("correct")

    def test_wrong_master_password_is_refused(self, db_mod):
        import odoo.tools
        from odoo.exceptions import AccessDenied

        with patch.object(
            odoo.tools.config, "verify_admin_password", return_value=False
        ) as verify:
            with pytest.raises(AccessDenied):
                db_mod.check_super("wrong")
        verify.assert_called_once_with("wrong")

    def test_empty_master_password_is_refused(self, db_mod):
        """Short-circuited before the comparison, so an unset ``admin_passwd``
        cannot be matched by sending an empty string."""
        from odoo.exceptions import AccessDenied

        with pytest.raises(AccessDenied):
            db_mod.check_super("")

    def test_management_gate_blocks_when_list_db_is_false(self, db_mod):
        import odoo.tools
        from odoo.exceptions import AccessDenied

        @db_mod.check_db_management_enabled
        def _op():
            return "ok"

        # Patching __getitem__ on an instance doesn't work for special methods —
        # Python looks them up on the class.  Replace the object with a plain dict.
        with patch.object(odoo.tools, "config", {"list_db": False}):
            with pytest.raises(AccessDenied):
                _op()

    def test_management_gate_passes_when_list_db_is_true(self, db_mod):
        import odoo.tools

        @db_mod.check_db_management_enabled
        def _op():
            return "ok"

        with patch.object(odoo.tools, "config", {"list_db": True}):
            assert _op() == "ok"

    def test_the_gate_sits_on_the_rpc_verbs_not_on_the_manifest_reader(self, db_mod):
        """``dump_db_manifest`` is a pure read against a cursor the caller
        already holds, and it is exported from ``odoo.service.db``.  Gating it
        made ``list_db = False`` refuse a read that discloses nothing new, while
        adding nothing: its one in-tree caller is inside ``dump_db``, which is
        gated itself.  The gate belongs on the RPC entry points."""
        import odoo.tools

        cr = MagicMock()
        cr.connection.info.server_version = 180000
        cr.fetchall.return_value = [("base", "19.0.1.3")]
        cr.dbname = "somedb"

        with patch.object(odoo.tools, "config", {"list_db": False}):
            manifest = db_mod.dump_db_manifest(cr)
        assert manifest["db_name"] == "somedb"
        assert manifest["pg_version"] == "18.0"

        # ...while the two RPC verbs that reach a cluster still refuse.
        from odoo.exceptions import AccessDenied

        for gated in (db_mod.dump_db, db_mod.exp_dump):
            with patch.object(odoo.tools, "config", {"list_db": False}):
                with pytest.raises(AccessDenied):
                    gated("somedb", None)


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
            db_mod.exp_change_admin_password(12345678)

    def test_accepts_8_char_password(self, db_mod):
        """Boundary: exactly 8 chars must be accepted."""
        with (
            patch(
                "odoo.service.db.rpc.odoo.tools.config.set_admin_password"
            ) as mock_set,
            patch("odoo.service.db.rpc.odoo.tools.config.save") as mock_save,
        ):
            result = db_mod.exp_change_admin_password("abcdefgh")
        assert result is True
        mock_set.assert_called_once_with("abcdefgh")
        mock_save.assert_called_once_with(["admin_passwd"])


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
            target = obj
            while hasattr(target, "__wrapped__"):
                target = target.__wrapped__
            if not (obj.__doc__ or target.__doc__):
                missing.append(name)
        assert not missing, f"Public exp_* functions missing docstrings: {missing}"


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
        missing = db_mod.rpc._REQUIRES_MASTER_PASSWORD - set(db_mod.rpc._DISPATCH)
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
        missing_auth = must_require_auth - db_mod.rpc._REQUIRES_MASTER_PASSWORD
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
        public_methods = frozenset(
            {
                "db_exist",
                "list",
                "list_lang",
                "server_version",
                "list_countries",
            }
        )
        gated = public_methods & db_mod.rpc._REQUIRES_MASTER_PASSWORD
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
        with (
            patch.object(db_mod.rpc, "check_super") as mock_check,
            patch.dict(db_mod.rpc._DISPATCH, {"list_countries": mock_handler}),
        ):
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
        with (
            patch.object(db_mod.rpc, "check_super") as mock_check,
            patch.object(db_mod.rpc, "exp_drop") as mock_drop,
        ):
            with patch.dict(db_mod.rpc._DISPATCH, {"drop": mock_drop}):
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
        with (
            patch.object(db_mod.rpc, "check_super") as mock_check,
            patch.dict(db_mod.rpc._DISPATCH, {"db_exist": mock_handler}),
        ):
            result = db_mod.dispatch("db_exist", ["mydb"])
        mock_check.assert_not_called()
        mock_handler.assert_called_once_with("mydb")
        assert result is True

    _ALLOWLIST_EXEMPT = frozenset(
        {
            "create_database",
            "restore",
            "change_admin_password",
        }
    )

    # How to invoke each gated handler with an UNEXPOSED database name.  The
    # gated name is always ``hidden_db``; the remaining arguments are whatever
    # the signature needs to reach the gate.
    _UNEXPOSED_CALL = {
        "drop": ("hidden_db",),
        "dump": ("hidden_db", "zip"),
        "duplicate_database": ("hidden_db", "copy_db"),
        "migrate_databases": (["hidden_db"],),
        "rename": ("hidden_db", "new_db"),
    }

    def test_db_name_handlers_gate_through_check_db_exposed(self, db_mod):
        """Every master-password handler acting on an EXISTING DB by name must
        gate it through ``check_db_exposed`` — ONE gate, one reaction.

        The inline ``list_dbs(True)`` form used to be accepted here as well,
        because ``exp_drop`` returned ``False`` instead of raising.  It no
        longer does, so the alternative is no longer permitted: allowing two
        spellings of one rule is how the two drift apart, and they had — the
        same unexposed name produced ``Access Denied`` from ``exp_dump`` and
        ``Database %r was not found`` from ``exp_drop``.

        Derived from ``_REQUIRES_MASTER_PASSWORD`` minus ``_ALLOWLIST_EXEMPT``,
        NOT a hardcoded list — so a future ``exp_*`` added to the master-password
        set without a gate (and without an explicit, justified exemption) fails
        this test by default. That is the actual forget-proofing.
        """
        from odoo.exceptions import AccessDenied

        gated = db_mod.rpc._REQUIRES_MASTER_PASSWORD - self._ALLOWLIST_EXEMPT
        assert set(self._UNEXPOSED_CALL) == gated, (
            f"the call recipes below no longer match the dispatch table "
            f"(missing {sorted(gated - set(self._UNEXPOSED_CALL))!r}, stale "
            f"{sorted(set(self._UNEXPOSED_CALL) - gated)!r}).  A new "
            f"master-password handler acting on an existing DB by name needs a "
            f"recipe here — and therefore a real refusal test — or an explicit, "
            f"justified entry in _ALLOWLIST_EXEMPT."
        )

        refusals = {}
        for method, args in self._UNEXPOSED_CALL.items():
            handler = db_mod.rpc._DISPATCH[method]
            with (
                patch.object(db_mod.listing, "list_dbs", return_value=["visible_db"]),
                patch.object(db_mod.lifecycle, "_drop_database") as dropped,
                patch("odoo.service.db.dump.subprocess.run") as ran,
            ):
                with pytest.raises(Exception) as excinfo:
                    handler(*args)
                refusals[method] = type(excinfo.value)
                assert not dropped.called, f"{method} acted before refusing"
                assert not ran.called, f"{method} shelled out before refusing"

        assert set(refusals.values()) == {AccessDenied}, (
            f"the unexposed-database refusal is not uniform: {refusals!r}. "
            f"Divergent reactions are the original bug — the same hidden name "
            f"produced AccessDenied from exp_dump and 'Database %r was not "
            f"found' from exp_drop, which is itself an existence oracle."
        )


class TestExpDuplicateRollback:
    """``exp_duplicate_database`` must drop the newly-created database when
    the filestore copy (or any post-CREATE step) fails.

    Regression: previously the post-CREATE work ran without a try/except.  A
    ``shutil.copytree`` failure (disk full, permission, source vanished mid-
    copy) left a perfectly valid PG database whose ``ir.attachment`` rows
    pointed at a filestore that was never created — a silent data
    inconsistency that's only noticed when a user opens an attachment.
    """

    @pytest.fixture
    def duplicate_env(self, db_mod, tmp_path):
        """Patches around exp_duplicate_database so we can inject failures.

        Does NOT depend on ``bypass_db_mgmt`` (which replaces ``config`` with a
        bare dict that lacks ``filestore``).  Instead, leaves the real config
        in place and patches ``filestore`` on it.
        """
        from contextlib import ExitStack

        fake_db, fake_cr = fake_pg_connection()

        from_fs = tmp_path / "filestore_source"
        from_fs.mkdir()
        (from_fs / "marker.txt").write_text("hello")

        stack = ExitStack()
        stack.enter_context(db_mod.lifecycle.odoo.tools.config.patch(list_db=True))
        stack.enter_context(patch.object(db_mod.lifecycle.odoo.db, "close_db"))
        stack.enter_context(
            patch("odoo.service.db.lifecycle.odoo.db.db_connect", return_value=fake_db)
        )
        stack.enter_context(
            patch("odoo.service.db.lifecycle.database_identifier", return_value="")
        )
        stack.enter_context(patch("odoo.service.db.lifecycle._drop_conn"))
        stack.enter_context(
            patch.object(
                db_mod.lifecycle.odoo.tools.config,
                "filestore",
                side_effect=lambda name: str(tmp_path / f"filestore_{name}"),
                create=True,
            )
        )
        yield {"cr": fake_cr, "stack": stack, "from_fs": from_fs}
        stack.close()

    def test_drops_db_when_filestore_copy_fails(self, db_mod, duplicate_env):
        """A ``shutil.copytree`` failure must trigger ``_drop_database``."""
        # A Registry, not a connection — but its ``cursor()`` is entered the same
        # way, so the shared helper describes it too.
        fake_registry = MagicMock()
        fake_registry.cursor.return_value = fake_pg_cursor()

        with duplicate_env["stack"]:
            with (
                patch.object(
                    db_mod.lifecycle.odoo.modules.registry.Registry,
                    "new",
                    return_value=fake_registry,
                ),
                patch(
                    "odoo.service.db.lifecycle.odoo.api.Environment",
                    return_value=MagicMock(),
                ),
                patch(
                    "odoo.service.db.lifecycle.shutil.copytree",
                    side_effect=OSError("disk full"),
                ),
                patch.object(db_mod.lifecycle, "_drop_database") as mock_drop,
            ):
                with pytest.raises(OSError, match="disk full"):
                    db_mod._duplicate_database("source", "newdb")

            mock_drop.assert_called_once_with("newdb")

    def test_drops_db_when_registry_init_fails(self, db_mod, duplicate_env):
        """``Registry.new`` failure (any reason) must trigger rollback."""
        with duplicate_env["stack"]:
            with (
                patch.object(
                    db_mod.lifecycle.odoo.modules.registry.Registry,
                    "new",
                    side_effect=RuntimeError("registry boom"),
                ),
                patch.object(db_mod.lifecycle, "_drop_database") as mock_drop,
            ):
                with pytest.raises(RuntimeError, match="registry boom"):
                    db_mod._duplicate_database("source", "newdb")

            mock_drop.assert_called_once_with("newdb")

    def test_drop_failure_does_not_mask_original_error(self, db_mod, duplicate_env):
        """If the rollback itself fails, the ORIGINAL exception must propagate
        (the rollback failure is suppressed).  The user/operator needs to know
        what went wrong before they can fix the orphan database."""
        with duplicate_env["stack"]:
            with (
                patch.object(
                    db_mod.lifecycle.odoo.modules.registry.Registry,
                    "new",
                    side_effect=RuntimeError("original error"),
                ),
                patch.object(
                    db_mod.lifecycle,
                    "_drop_database",
                    side_effect=Exception("drop also failed"),
                ),
            ):
                with pytest.raises(RuntimeError, match="original error"):
                    db_mod._duplicate_database("source", "newdb")


class TestExpRenameRollback:
    """``exp_rename`` must roll back the SQL rename if the filestore move fails.

    Regression: the half-done state ("DB at new_name, filestore at old_name")
    silently serves attachments to the wrong database after a future rename.
    The fix issues an ALTER DATABASE RENAME back to the old name; if THAT
    also fails, both errors are surfaced for manual intervention.
    """

    @pytest.fixture
    def rename_env(self, db_mod, tmp_path):
        """Setup with a real source filestore and patched DB layer.

        Self-contained: doesn't depend on ``bypass_db_mgmt`` (which replaces
        the config object with a bare dict).
        """
        from contextlib import ExitStack

        fake_db, fake_cr = fake_pg_connection()

        old_fs = tmp_path / "filestore_oldname"
        old_fs.mkdir()
        (old_fs / "data.txt").write_text("attachment payload")

        stack = ExitStack()
        stack.enter_context(db_mod.lifecycle.odoo.tools.config.patch(list_db=True))
        stack.enter_context(
            patch.object(db_mod.lifecycle.odoo.modules.registry.Registry, "delete")
        )
        stack.enter_context(patch.object(db_mod.lifecycle.odoo.db, "close_db"))
        stack.enter_context(
            patch("odoo.service.db.lifecycle.odoo.db.db_connect", return_value=fake_db)
        )
        stack.enter_context(
            patch("odoo.service.db.lifecycle.database_identifier", return_value="")
        )
        stack.enter_context(patch("odoo.service.db.lifecycle._drop_conn"))
        stack.enter_context(
            patch.object(
                db_mod.lifecycle.odoo.tools.config,
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
                "odoo.service.db.lifecycle.shutil.move",
                side_effect=OSError("permission denied"),
            ):
                with pytest.raises(RuntimeError, match="permission denied"):
                    db_mod._rename_database("oldname", "newname")

        rename_calls = [
            c
            for c in rename_env["cr"].execute.call_args_list
            if "ALTER DATABASE" in str(c)
        ]
        assert len(rename_calls) == 2, (
            f"Expected 2 ALTER DATABASE RENAME calls (forward + rollback), "
            f"got {len(rename_calls)}: {rename_calls}"
        )

    def test_double_failure_surfaces_both_errors(self, db_mod, rename_env):
        """If both filestore move AND the DB rename-back fail, the operator
        needs both error messages to recover manually."""
        rename_call_count = 0

        def execute_side_effect(sql, *args, **kwargs):
            nonlocal rename_call_count
            if "ALTER DATABASE" in str(sql):
                rename_call_count += 1
                if rename_call_count == 2:
                    raise RuntimeError("rollback rename also failed")

        rename_env["cr"].execute.side_effect = execute_side_effect

        with rename_env["stack"]:
            with patch(
                "odoo.service.db.lifecycle.shutil.move",
                side_effect=OSError("disk full"),
            ):
                with pytest.raises(RuntimeError, match="manual intervention required"):
                    db_mod._rename_database("oldname", "newname")


class TestDropDatabaseRetryBudget:
    """The retry budget covers the realistic worst-case for a busy DB.

    Regression: a 3-attempt / 0.6s budget consistently failed under load.
    The new budget (5 attempts / 6.2s cumulative) gives a connection holder
    enough time to receive ``pg_terminate_backend``, unwind, and release.
    """

    def test_retry_count_is_at_least_5(self, db_mod):
        assert db_mod.lifecycle._DROP_DATABASE_MAX_RETRIES >= 5, (
            "Lowering the retry count below 5 reintroduces the 'connection "
            "lands in the drop window' failure mode under load."
        )

    def test_backoff_is_exponential(self, db_mod):
        """Each attempt waits longer than the previous one."""
        base = db_mod.lifecycle._DROP_DATABASE_BACKOFF_BASE
        delays = [
            base * (2 ** (n - 1))
            for n in range(1, db_mod.lifecycle._DROP_DATABASE_MAX_RETRIES + 1)
        ]
        assert all(delays[i] < delays[i + 1] for i in range(len(delays) - 1)), (
            f"Backoff is not strictly increasing: {delays}"
        )
        assert sum(delays) >= 3.0, (
            f"Total backoff budget {sum(delays):.2f}s is too short for a busy DB"
        )


class TestExpListNoRedundantCheck:
    """``exp_list`` must rely on ``list_dbs()`` for the ``list_db`` gate.

    Regression-prevention: the prior body re-implemented the same gate as
    ``list_dbs()``.  A future change to ``list_dbs`` (e.g. adding a context
    where it should NOT raise) would silently be subverted by the
    redundant pre-check that ``exp_list`` did itself.
    """

    def test_passthrough_when_list_db_enabled(self, db_mod):
        with patch.object(
            db_mod.listing, "list_dbs", return_value=["a", "b"]
        ) as mock_list:
            assert db_mod.exp_list() == ["a", "b"]
        mock_list.assert_called_once_with()

    def test_propagates_access_denied_from_list_dbs(self, db_mod):
        from odoo.exceptions import AccessDenied

        with patch.object(db_mod.listing, "list_dbs", side_effect=AccessDenied):
            with pytest.raises(AccessDenied):
                db_mod.exp_list()

    def test_document_kwarg_accepted_for_backcompat(self, db_mod):
        """Old XML-RPC clients pass document=True; must not TypeError."""
        with patch.object(db_mod.listing, "list_dbs", return_value=[]):
            assert db_mod.exp_list() == []
            assert db_mod.exp_list(document=True) == []


class TestDropConnLogging:
    """``_drop_conn`` logs at debug level when ``pg_terminate_backend`` fails.

    Regression: the prior bare ``suppress(Exception)`` made permission errors
    invisible — operators investigating "DROP DATABASE keeps hitting
    ObjectInUse" had no way to discover that their PG role lacked
    ``pg_signal_backend`` membership.
    """

    def test_failure_is_logged_at_debug(self, db_mod, caplog):
        import logging

        fake_cr = MagicMock()
        fake_cr.execute.side_effect = RuntimeError(
            "permission denied for pg_signal_backend"
        )

        target_logger = logging.getLogger("odoo.service.db")
        prior_level = target_logger.level
        target_logger.setLevel(logging.DEBUG)
        try:
            with caplog.at_level(logging.DEBUG, logger="odoo.service.db"):
                db_mod.lifecycle._drop_conn(fake_cr, "any_db")
        finally:
            target_logger.setLevel(prior_level)

        assert any(
            "pg_terminate_backend failed" in r.message
            for r in caplog.records
            if r.name == "odoo.service.db"
        ), (
            f"Expected debug log; got records: {[(r.name, r.message) for r in caplog.records]}"
        )

    def test_failure_does_not_propagate(self, db_mod):
        """Exceptions are still swallowed — termination is best-effort."""
        fake_cr = MagicMock()
        fake_cr.execute.side_effect = RuntimeError("anything")
        db_mod.lifecycle._drop_conn(fake_cr, "any_db")


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
        with (
            patch.object(db_mod.restore, "exp_db_exist", return_value=False),
            patch.object(db_mod.restore, "_create_empty_database"),
            patch.object(db_mod.lifecycle, "_drop_database"),
            patch(
                "odoo.service.db.restore.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=1, stderr="x"),
            ) as mock_run,
        ):
            with pytest.raises(RuntimeError):
                db_mod.restore_db("newdb", zip_dump)

        cmd = mock_run.call_args.args[0]
        assert "-v" in cmd and "ON_ERROR_STOP=1" in cmd, (
            f"psql restore must pass -v ON_ERROR_STOP=1; got {cmd!r}"
        )
        assert cmd[cmd.index("-v") + 1] == "ON_ERROR_STOP=1", (
            f"-v must be immediately followed by ON_ERROR_STOP=1; got {cmd!r}"
        )


class TestRestoreDbNameValidation:
    """``restore_db`` must enforce the same name shape/length as the other
    name-accepting entry points, before creating anything.  Otherwise a 64+
    char name reaches ``CREATE DATABASE`` where PostgreSQL silently truncates
    it to 63 bytes — the footgun ``DBNAME_MAX_LENGTH`` exists to prevent.
    """

    def test_rejects_overlong_name_before_any_side_effect(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod.restore, "exp_db_exist") as mock_exist,
            patch.object(db_mod.restore, "_create_empty_database") as mock_create,
        ):
            with pytest.raises(ValueError, match="63 characters"):
                db_mod.restore_db("a" * 70, "/dev/null")
        mock_exist.assert_not_called()
        mock_create.assert_not_called()

    def test_rejects_invalid_shape_before_any_side_effect(self, db_mod, bypass_db_mgmt):
        with (
            patch.object(db_mod.restore, "exp_db_exist") as mock_exist,
            patch.object(db_mod.restore, "_create_empty_database") as mock_create,
        ):
            with pytest.raises(ValueError, match="must start with"):
                db_mod.restore_db("../etc/passwd", "/dev/null")
        mock_exist.assert_not_called()
        mock_create.assert_not_called()

    def test_valid_name_passes_validation(self, db_mod, bypass_db_mgmt):
        """A well-formed name must NOT be rejected by the new check — the
        guard must reach the existing-DB pre-flight (which we stub to True)."""
        with (
            patch.object(db_mod.restore, "exp_db_exist", return_value=True),
            patch.object(db_mod.restore, "_create_empty_database"),
        ):
            with pytest.raises(RuntimeError, match="already exists"):
                db_mod.restore_db("valid_db.name-1", "/dev/null")


class TestRetryTerminateThenDdl:
    """The terminate-then-act retry loop shared by drop / duplicate / rename.

    Replaces three copy-pasted loops; pinned directly so the contract
    (retry only on ObjectInUse, propagate everything else, exhaust to
    RuntimeError carrying the last error) is enforced in one place.
    """

    def test_returns_on_first_success(self, db_mod):
        cr = MagicMock()
        run = MagicMock()
        with (
            patch.object(db_mod.lifecycle, "_drop_conn") as drop_conn,
            patch("odoo.service.db.lifecycle.time.sleep"),
        ):
            db_mod.lifecycle._retry_terminate_then_ddl(cr, "db", "OP: db", run)
        run.assert_called_once()
        drop_conn.assert_called_once_with(cr, "db")

    def test_retries_on_object_in_use_then_succeeds(self, db_mod):
        import psycopg

        cr = MagicMock()
        run = MagicMock(side_effect=[psycopg.errors.ObjectInUse("busy"), None])
        with (
            patch.object(db_mod.lifecycle, "_drop_conn") as drop_conn,
            patch("odoo.service.db.lifecycle.time.sleep") as sleep,
        ):
            db_mod.lifecycle._retry_terminate_then_ddl(cr, "db", "OP: db", run)
        assert run.call_count == 2
        assert drop_conn.call_count == 2
        sleep.assert_called_once()

    def test_exhaustion_raises_runtimeerror_with_last_error(self, db_mod):
        import psycopg

        cr = MagicMock()
        run = MagicMock(side_effect=psycopg.errors.ObjectInUse("forever"))
        with (
            patch.object(db_mod.lifecycle, "_drop_conn"),
            patch("odoo.service.db.lifecycle.time.sleep"),
        ):
            with pytest.raises(RuntimeError, match="forever"):
                db_mod.lifecycle._retry_terminate_then_ddl(cr, "db", "OP: db", run)
        assert run.call_count == db_mod.lifecycle._DROP_DATABASE_MAX_RETRIES

    def test_non_object_in_use_propagates_without_retry(self, db_mod):
        cr = MagicMock()
        run = MagicMock(side_effect=ValueError("hard fail"))
        with (
            patch.object(db_mod.lifecycle, "_drop_conn"),
            patch("odoo.service.db.lifecycle.time.sleep") as sleep,
        ):
            with pytest.raises(ValueError, match="hard fail"):
                db_mod.lifecycle._retry_terminate_then_ddl(cr, "db", "OP: db", run)
        run.assert_called_once()
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
        with (
            patch.object(db_mod.lifecycle, "_drop_conn"),
            patch("odoo.service.db.lifecycle.time.sleep") as sleep,
        ):
            with pytest.raises(RuntimeError):
                db_mod.lifecycle._retry_terminate_then_ddl(cr, "db", "OP: db", run)
        assert run.call_count == db_mod.lifecycle._DROP_DATABASE_MAX_RETRIES
        assert sleep.call_count == db_mod.lifecycle._DROP_DATABASE_MAX_RETRIES - 1


class TestRestoreArchiveExpansionBound:
    """``ZipFile.extractall`` has no size ceiling and the archive is uploaded by
    the caller.  ``tempfile`` commonly resolves to a tmpfs, so an unbounded
    expansion consumes RAM rather than disk."""

    def _bomb(self, tmp_path, mb):
        path = tmp_path / "bomb.zip"
        blob = b"A" * (1024 * 1024)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            with z.open("dump.sql", "w") as fh:
                for _ in range(mb):
                    fh.write(blob)
        return path

    def test_budget_scales_with_compressed_size_but_has_a_floor(self, db_mod, tmp_path):
        small = tmp_path / "small.zip"
        small.write_bytes(b"x" * 1024)
        assert (
            db_mod.restore._unpack_budget(str(small))
            == db_mod.restore._RESTORE_MIN_UNPACKED_BYTES
        )
        big = tmp_path / "big.zip"
        big.write_bytes(b"x" * (50 * 1024 * 1024))
        assert db_mod.restore._unpack_budget(str(big)) == (
            50 * 1024 * 1024 * db_mod.restore._RESTORE_MAX_EXPANSION_RATIO
        )

    def test_extraction_stops_at_the_budget(self, db_mod, tmp_path):
        # 24 MB against an 8 MB budget: enough to overshoot three times over,
        # where the previous 200 MB spent 0.42s building a bomb whose extra
        # 176 MB changed no outcome.  Confirmed still fatal to the mutation the
        # test exists for (removing the budget check).
        path = self._bomb(tmp_path, 24)
        dest = tmp_path / "out"
        dest.mkdir()
        with zipfile.ZipFile(path) as z:
            with pytest.raises(RuntimeError, match="expands to more than"):
                db_mod.restore._extract_members_bounded(
                    z, ["dump.sql"], str(dest), 8 * 1024 * 1024
                )

    def test_counts_bytes_produced_not_the_declared_header_size(self, db_mod, tmp_path):
        """A member whose header under-reports its size must buy nothing: the
        budget is spent against the bytes actually written."""
        path = self._bomb(tmp_path, 40)
        with zipfile.ZipFile(path, "a") as z:
            z.getinfo("dump.sql").file_size = 1
        dest = tmp_path / "out"
        dest.mkdir()
        with zipfile.ZipFile(path) as z:
            with pytest.raises(RuntimeError, match="expands to more than"):
                db_mod.restore._extract_members_bounded(
                    z, ["dump.sql"], str(dest), 4 * 1024 * 1024
                )

    def test_nested_members_land_intact_within_budget(self, db_mod, tmp_path):
        """The bounded extractor replaces ``extractall``, so it must still create
        parent directories — a real backup's filestore members are nested
        (``filestore/27/27c0...``) and carry no explicit directory entries."""
        path = tmp_path / "ok.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("dump.sql", "SELECT 1;\n")
            z.writestr("filestore/27/27c0abc", b"payload-a")
            z.writestr("filestore/3d/3daebe", b"payload-b")
        dest = tmp_path / "out"
        dest.mkdir()
        with zipfile.ZipFile(path) as z:
            written = db_mod.restore._extract_members_bounded(
                z,
                ["dump.sql", "filestore/27/27c0abc", "filestore/3d/3daebe"],
                str(dest),
                10 * 1024 * 1024,
            )
        assert (dest / "filestore/27/27c0abc").read_bytes() == b"payload-a"
        assert (dest / "filestore/3d/3daebe").read_bytes() == b"payload-b"
        assert written == len("SELECT 1;\n") + len(b"payload-a") + len(b"payload-b")


class TestDatabaseIdentifierPercent:
    """``database_identifier`` feeds a ``SQL`` template whose ``code`` is
    ``%``-formatted, so a literal ``%`` (legal in a PG identifier, reachable via
    ``db_template``) must be doubled or ``SQL.__init__`` raises ``TypeError``."""

    def test_percent_in_identifier_does_not_raise(self, db_mod):
        cr = MagicMock()
        cr.connection = None
        sql = db_mod.database_identifier(cr, "weird%name")
        assert (sql.code % sql.params) == '"weird%name"'


class TestCreateEmptyDatabaseHardening:
    def _mock_pg(self, db_mod, *, create_raises=None):
        """Patch ``odoo.db.db_connect`` and return (patch_cm, connect_mock, cr).

        ``_create_empty_database`` opens the maintenance cursor via
        ``closing(db.cursor())`` — which yields ``db.cursor()`` directly — so the
        cursor mock is the ``cursor.return_value`` itself (not an ``__enter__``).
        """
        import odoo.db

        cr = MagicMock()
        cr.connection = MagicMock()
        if create_raises is not None:
            cr.execute.side_effect = create_raises
        conn = MagicMock()
        conn.cursor.return_value = cr
        return patch.object(odoo.db, "db_connect", return_value=conn), conn, cr

    @pytest.mark.parametrize("template", ["template0", "tpl_custom"])
    def test_the_new_database_is_created_from_the_template_not_vice_versa(
        self, db_mod, bypass_db_mgmt, template
    ):
        """``CREATE DATABASE <new> ... TEMPLATE <template>`` — in that order.

        Both quoted identifiers go through ``database_identifier``, and every
        other test here stubs it with a CONSTANT ``return_value``, so which
        argument lands in which slot is unobserved: swapping them
        (``database_identifier(cr, name)`` -> ``...(cr, chosen_template)``) left
        the whole 887-test suite green.  Keying the stub on its argument, and
        recording the order, is what pins it.

        Parametrized over both templates on purpose: ``_create_empty_database``
        branches on ``chosen_template == "template0"`` and spells the identifier
        pair out separately in each arm, so a test that drives only one arm
        leaves the other unpinned — which is how the first version of this test
        missed the very mutation it was written for.
        """
        import odoo.tools

        seen: list[str] = []

        def identifier(_cr, name):
            seen.append(name)
            return name

        fake_db, _fake_cr = fake_pg_connection()
        with (
            patch.object(
                odoo.tools,
                "config",
                _MockConfig(
                    {"list_db": True, "db_template": template, "unaccent": False}
                ),
            ),
            patch("odoo.service.db.lifecycle.odoo.db.db_connect", return_value=fake_db),
            patch("odoo.service.db.lifecycle.database_identifier", identifier),
            patch("odoo.service.db.lifecycle._check_faketime_mode"),
        ):
            db_mod._create_empty_database("newdb")

        assert seen[:2] == ["newdb", template], (
            f"CREATE DATABASE quoted {seen[:2]}; the new database must come "
            f"first and the template second, or a create silently targets the "
            f"template (or clones the wrong source)"
        )

    def test_rejects_malformed_db_template(self, db_mod, bypass_db_mgmt):
        """A ``%``-bearing (malformed) template fails fast with a clear
        ``ValueError`` rather than a cryptic error deep in CREATE DATABASE."""
        cm, _conn, _cr = self._mock_pg(db_mod)
        with cm:
            with pytest.raises(ValueError, match="Invalid database name"):
                db_mod._create_empty_database("newdb", template="bad%name")

    def test_setup_if_exists_false_skips_setup_on_collision(
        self, db_mod, bypass_db_mgmt
    ):
        """On a name collision with ``setup_if_exists=False`` (strict
        create/restore), ``DatabaseExists`` is raised WITHOUT connecting to the
        pre-existing DB to run extensions/GRANT on it."""
        import psycopg

        from odoo.tools import SQL

        cm, _conn, _cr = self._mock_pg(
            db_mod, create_raises=psycopg.errors.DuplicateDatabase("exists")
        )
        with (
            cm as db_connect_mock,
            patch.object(
                db_mod.lifecycle, "database_identifier", return_value=SQL("x")
            ),
        ):
            with pytest.raises(db_mod.DatabaseExists):
                db_mod._create_empty_database(
                    "taken", template="template0", setup_if_exists=False
                )
        assert db_connect_mock.call_args_list == [call("postgres")]


class TestRpcDbExistGate:
    """``db_exist`` is reachable unauthenticated (``/jsonrpc``, ``/xmlrpc/2/db``).

    Ungated it is a per-name existence oracle over every database owned by the
    PG role — the enumeration ``list_db = False`` and ``common.exp_authenticate``
    deny — and, because ``exp_db_exist`` connects, a way to make an
    unauthenticated caller open a pooled connection to a database this instance
    does not serve.  ``_rpc_db_exist`` filters BEFORE connecting; the bare
    ``exp_db_exist`` stays ungated for trusted in-process callers.
    """

    def _cfg(self, **over):
        cfg = _MockConfig({"list_db": True, "db_template": "template1"})
        cfg.update(over)
        return cfg

    def test_dispatch_uses_the_gated_wrapper(self, db_mod):
        assert db_mod.rpc._DISPATCH["db_exist"] is db_mod.listing._rpc_db_exist
        assert db_mod.rpc._DISPATCH["db_exist"] is not db_mod.exp_db_exist

    def test_list_db_false_answers_false_for_everything(self, db_mod):
        """``list_db = False`` turns off DB management; ``db_exist`` must not
        stay a working oracle while ``list`` raises AccessDenied.

        It answers ``False`` rather than raising ``AccessDenied``: this verb is
        declared to return a bool and is reachable unauthenticated, so raising
        would break every caller on precisely the configuration being hardened —
        and an exception that distinguishes "management disabled" from "no such
        database" leaks strictly more than a flat ``False``.
        """
        import odoo.tools

        with (
            patch.object(odoo.tools, "config", self._cfg(list_db=False)),
            patch.object(db_mod.listing, "list_dbs", return_value=["served"]),
            patch.object(db_mod.listing, "exp_db_exist", return_value=True) as inner,
        ):
            assert db_mod.listing._rpc_db_exist("served") is False
            assert db_mod.listing._rpc_db_exist("nope") is False
        inner.assert_not_called()

    def test_unexposed_existing_db_answers_false_without_connecting(self, db_mod):
        import odoo.tools

        with (
            patch.object(odoo.tools, "config", self._cfg()),
            patch.object(db_mod.listing, "list_dbs", return_value=["served"]),
            patch.object(db_mod.listing, "exp_db_exist") as inner,
        ):
            assert db_mod.listing._rpc_db_exist("other_tenant_db") is False
        inner.assert_not_called()

    def test_exposed_db_is_answered(self, db_mod):
        import odoo.tools

        with (
            patch.object(odoo.tools, "config", self._cfg()),
            patch.object(db_mod.listing, "list_dbs", return_value=["served"]),
            patch.object(db_mod.listing, "exp_db_exist", return_value=True) as inner,
        ):
            assert db_mod.listing._rpc_db_exist("served") is True
        inner.assert_called_once_with("served")

    @pytest.mark.parametrize("name", ["postgres", "template0", "template1"])
    def test_system_and_template_dbs_are_never_disclosed(self, db_mod, name):
        """``SYSTEM_DBS`` and the creation template are never servable (the same
        floor ``http.helpers.db_filter`` applies), so never disclosed."""
        import odoo.tools

        with (
            patch.object(odoo.tools, "config", self._cfg()),
            patch.object(db_mod.listing, "list_dbs", return_value=[name]),
            patch.object(db_mod.listing, "exp_db_exist") as inner,
        ):
            assert db_mod.listing._rpc_db_exist(name) is False
        inner.assert_not_called()

    @pytest.mark.parametrize("name", ["", "-leading", "a" * 64, "sp ace", "semi;colon"])
    def test_malformed_names_are_rejected_before_pg(self, db_mod, name):
        import odoo.tools

        with (
            patch.object(odoo.tools, "config", self._cfg()),
            patch.object(db_mod.listing, "list_dbs") as listed,
            patch.object(db_mod.listing, "exp_db_exist") as inner,
        ):
            assert db_mod.listing._rpc_db_exist(name) is False
        listed.assert_not_called()
        inner.assert_not_called()


class TestListDbIncompatiblePoolSideEffects:
    """``list_db_incompatible`` must leave pools as it found them.

    It is an INSPECTION helper called on every render of the database manager /
    selector (``web.controllers.database._render_template``), both ``auth="none"``.
    It used to ``close_db`` every database it looked at, in a ``finally`` inside
    the loop, so one unauthenticated request evicted the pool of every database on
    the instance — including healthy, actively-served ones.  Upstream only closed
    the databases it found incompatible.

    Measured before the fix on a live server: one GET of ``/web/database/selector``
    produced one ``Closed 1 pool(s) for <db>`` per database (3 requests -> 3
    evictions), and the next cursor on an evicted database cost ~5.2 ms against
    ~0.24 ms warm.  In-flight work was never at risk (a checked-out connection
    survives its pool's close, and registries are untouched), so the whole cost was
    reconnect latency — which is exactly what these tests pin away.
    """

    @pytest.fixture
    def probe(self, db_mod):
        """Drive ``list_db_incompatible`` with mocked pool + version lookups.

        Returns a factory taking ``{db: is_compatible}`` and ``preexisting``
        (databases that already had a pool), and yielding the databases the call
        closed.
        """

        def _run(compat: dict, preexisting: set):
            import odoo

            closed = []
            cur = MagicMock()
            cur.__enter__ = lambda s: s
            cur.__exit__ = lambda s, *a: False

            def fake_table_exists(cr, table):
                return compat[cr._dbname] is not None

            def fake_connect(name):
                conn = MagicMock()
                c = MagicMock()
                c._dbname = name
                c.fetchone.return_value = (compat[name],) if compat[name] else None
                conn.cursor.return_value = c
                return conn

            with (
                patch.object(odoo.db, "db_connect", side_effect=fake_connect),
                patch.object(
                    odoo.db, "is_pooled", side_effect=lambda n: n in preexisting
                ),
                patch.object(odoo.db, "close_db", side_effect=closed.append),
                patch.object(
                    odoo.db.schema, "table_exists", side_effect=fake_table_exists
                ),
                patch.object(
                    db_mod.listing, "version_info", (19, 0, 0, "final", 0, "")
                ),
            ):
                incompatible = db_mod.list_db_incompatible(list(compat))
            return incompatible, closed

        return _run

    def test_compatible_preexisting_pool_survives(self, probe):
        """The regression: a served database keeps the pool it already had."""
        incompatible, closed = probe({"live": "19.0.1.0"}, preexisting={"live"})
        assert incompatible == []
        assert closed == [], (
            "list_db_incompatible evicted the pool of a healthy, already-pooled "
            "database — the unauthenticated pool-churn regression"
        )

    def test_compatible_pool_we_opened_is_closed(self, probe):
        """A pool this call created is still cleaned up — no leak."""
        incompatible, closed = probe({"idle": "19.0.1.0"}, preexisting=set())
        assert incompatible == []
        assert closed == ["idle"]

    def test_incompatible_is_always_closed(self, probe):
        """Upstream's rule survives: an incompatible database is not kept pooled."""
        incompatible, closed = probe({"old": "18.0.1.0"}, preexisting={"old"})
        assert incompatible == ["old"]
        assert closed == ["old"]

    def test_mixed_set_closes_only_the_right_ones(self, probe):
        incompatible, closed = probe(
            {"live": "19.0.1.0", "old": "18.0.1.0", "idle": "19.0.1.0"},
            preexisting={"live", "old"},
        )
        assert incompatible == ["old"]
        assert sorted(closed) == ["idle", "old"]


class TestRetryOnObjectInUse:
    """``CREATE DATABASE ... TEMPLATE t`` needs zero sessions on ``t``.

    Upstream's default template (``template0``) is ``datallowconn = false``, so
    nothing can be connected and the race never fires.  ``--db-template`` is a
    supported upstream option though, and a populated template is connectable —
    this workspace's ``tpl_p314o19marin`` is ``datallowconn = true``.  Verified
    against the live cluster: one idle ``psql`` session on it made
    ``_create_empty_database`` raise a bare ``psycopg.errors.ObjectInUse``
    ("source database ... is being accessed by other users"), unretried and
    untranslated, failing every database creation including the boot path.
    """

    def test_retries_then_succeeds(self, db_mod):
        import psycopg

        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise psycopg.errors.ObjectInUse("still in use")

        with patch.object(db_mod.lifecycle.time, "sleep"):
            db_mod.lifecycle._retry_on_object_in_use("TEST OP", flaky)
        assert len(calls) == 3

    def test_gives_up_as_runtimeerror_naming_the_op(self, db_mod):
        import psycopg

        def always():
            raise psycopg.errors.ObjectInUse("source database is being accessed")

        with (
            patch.object(db_mod.lifecycle.time, "sleep"),
            pytest.raises(RuntimeError) as exc,
        ):
            db_mod.lifecycle._retry_on_object_in_use(
                "CREATE DB: x (template t)", always
            )
        assert "CREATE DB: x (template t)" in str(exc.value)
        assert "still in use after" in str(exc.value)

    def test_other_errors_abort_immediately(self, db_mod):
        def boom():
            raise ValueError("unrelated")

        with pytest.raises(ValueError):
            db_mod.lifecycle._retry_on_object_in_use("TEST OP", boom)

    def test_before_attempt_runs_once_per_try(self, db_mod):
        import psycopg

        before = []
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise psycopg.errors.ObjectInUse("busy")

        with patch.object(db_mod.lifecycle.time, "sleep"):
            db_mod.lifecycle._retry_on_object_in_use(
                "TEST OP", flaky, before_attempt=lambda: before.append(1)
            )
        assert len(before) == 3

    def test_terminate_variant_still_evicts_each_attempt(self, db_mod):
        """``_retry_terminate_then_ddl`` keeps its per-attempt ``_drop_conn``."""
        import psycopg

        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 2:
                raise psycopg.errors.ObjectInUse("busy")

        cr = MagicMock()
        with (
            patch.object(db_mod.lifecycle, "_drop_conn") as drop_conn,
            patch.object(db_mod.lifecycle.time, "sleep"),
        ):
            db_mod.lifecycle._retry_terminate_then_ddl(
                cr, "target", "DROP DB: target", flaky
            )
        assert drop_conn.call_count == 2


class TestCreateEmptyDatabaseTemplateContention:
    def test_create_retries_object_in_use(self, db_mod, bypass_db_mgmt):
        """A transiently busy template is retried, not surfaced raw."""
        import psycopg

        attempts = []

        def execute(sql, *a, **kw):
            text = str(sql)
            if "CREATE DATABASE" in text:
                attempts.append(1)
                if len(attempts) < 3:
                    raise psycopg.errors.ObjectInUse(
                        'source database "tpl" is being accessed by other users'
                    )

        conn, _cr = fake_pg_connection(execute=execute)

        import odoo

        with (
            patch.object(odoo.db, "db_connect", return_value=conn),
            patch.object(
                db_mod.lifecycle, "database_identifier", side_effect=lambda c, n: n
            ),
            patch.object(db_mod.lifecycle, "_check_faketime_mode"),
            patch.object(db_mod.lifecycle.time, "sleep"),
            patch.object(
                odoo.tools,
                "config",
                _MockConfig({"list_db": True, "db_template": "tpl", "unaccent": False}),
            ),
        ):
            db_mod._create_empty_database("newdb", setup_if_exists=False)
        assert len(attempts) == 3, "CREATE DATABASE was not retried on ObjectInUse"

    def test_create_does_not_terminate_template_sessions(self, db_mod, bypass_db_mgmt):
        """Unlike DROP/RENAME/DUPLICATE, CREATE must not evict the blocker.

        The blocker is a third party's session on a template this call only
        READS — very likely the operator maintaining it.
        """
        import odoo

        conn, _cr = fake_pg_connection()

        with (
            patch.object(odoo.db, "db_connect", return_value=conn),
            patch.object(
                db_mod.lifecycle, "database_identifier", side_effect=lambda c, n: n
            ),
            patch.object(db_mod.lifecycle, "_check_faketime_mode"),
            patch.object(db_mod.lifecycle, "_drop_conn") as drop_conn,
            patch.object(
                odoo.tools,
                "config",
                _MockConfig({"list_db": True, "db_template": "tpl", "unaccent": False}),
            ),
        ):
            db_mod._create_empty_database("newdb", setup_if_exists=False)
        drop_conn.assert_not_called()


class TestZipDumpDoesNotStageFilestore:
    """The zip backup must stream, not assemble itself in ``TMPDIR`` first.

    The previous implementation ``copytree``'d the entire filestore into a
    ``TemporaryDirectory`` alongside an uncompressed ``dump.sql`` and only then
    zipped that tree.  ``TMPDIR`` is commonly a tmpfs (16 GiB on this workspace),
    so the staging copy was charged to RAM: measured, a 201 MiB filestore drove
    ``/tmp`` up 204 MiB, against 3 MiB with ``with_filestore=False`` — which
    isolates the copytree as the cause.
    """

    @pytest.fixture
    def live_filestore(self, tmp_path):
        fs = tmp_path / "filestore" / "db"
        (fs / "aa").mkdir(parents=True)
        (fs / "aa" / "blob1").write_bytes(b"x" * 1024)
        (fs / "aa" / "blob2").write_bytes(b"y" * 1024)
        return fs

    def _dump(self, db_mod, filestore, stream, with_filestore=True):
        import odoo

        class _Cfg(_MockConfig):
            def filestore(self, name):
                return str(filestore)

        def fake_pg_dump(cmd, env, out):
            out.write(b"-- SQL DUMP\nSELECT 1;\n")

        with (
            patch.object(odoo.tools, "config", _Cfg({"list_db": True})),
            patch.object(db_mod.dump, "find_pg_tool", return_value="/bin/true"),
            patch.object(db_mod.dump, "exec_pg_environ", return_value={}),
            patch.object(
                db_mod.dump, "dump_db_manifest", return_value={"odoo_dump": "1"}
            ),
            patch.object(
                db_mod.dump, "_run_pg_dump_streaming", side_effect=fake_pg_dump
            ),
            patch.object(odoo.db, "db_connect"),
            patch.object(db_mod.dump.shutil, "copytree") as copytree,
        ):
            db_mod.dump_db("db", stream, "zip", with_filestore)
        return copytree

    def test_no_copytree_and_archive_is_complete(self, db_mod, live_filestore):
        buf = io.BytesIO()
        copytree = self._dump(db_mod, live_filestore, buf)
        copytree.assert_not_called()

        buf.seek(0)
        with zipfile.ZipFile(buf) as z:
            names = set(z.namelist())
            assert "dump.sql" in names
            assert "manifest.json" in names
            assert {"filestore/aa/blob1", "filestore/aa/blob2"} <= names
            assert z.read("dump.sql") == b"-- SQL DUMP\nSELECT 1;\n"
            assert z.read("filestore/aa/blob1") == b"x" * 1024

    def test_without_filestore_only_sql_and_manifest(self, db_mod, live_filestore):
        buf = io.BytesIO()
        self._dump(db_mod, live_filestore, buf, with_filestore=False)
        buf.seek(0)
        with zipfile.ZipFile(buf) as z:
            assert set(z.namelist()) == {"manifest.json", "dump.sql"}

    def test_sql_precedes_filestore_in_the_archive(self, db_mod, live_filestore):
        """SQL first, filestore after — so the inconsistency window leaves an
        unreferenced file rather than a row whose file is missing."""
        buf = io.BytesIO()
        self._dump(db_mod, live_filestore, buf)
        buf.seek(0)
        with zipfile.ZipFile(buf) as z:
            order = z.namelist()
        assert order.index("dump.sql") < min(
            i for i, n in enumerate(order) if n.startswith("filestore/")
        )

    def test_symlink_escaping_the_filestore_is_skipped(
        self, db_mod, live_filestore, tmp_path
    ):
        """A stray link must not pull host files into a backup."""
        secret = tmp_path / "secret.txt"
        secret.write_text("do not back me up")
        (live_filestore / "aa" / "escape").symlink_to(secret)

        buf = io.BytesIO()
        self._dump(db_mod, live_filestore, buf)
        buf.seek(0)
        with zipfile.ZipFile(buf) as z:
            assert "filestore/aa/escape" not in z.namelist()
            assert b"do not back me up" not in b"".join(z.read(n) for n in z.namelist())

    def test_stream_none_returns_seekable_archive(self, db_mod, live_filestore):
        import odoo

        class _Cfg(_MockConfig):
            def filestore(self, name):
                return str(live_filestore)

        def fake_pg_dump(cmd, env, out):
            out.write(b"SELECT 1;\n")

        with (
            patch.object(odoo.tools, "config", _Cfg({"list_db": True})),
            patch.object(db_mod.dump, "find_pg_tool", return_value="/bin/true"),
            patch.object(db_mod.dump, "exec_pg_environ", return_value={}),
            patch.object(
                db_mod.dump, "dump_db_manifest", return_value={"odoo_dump": "1"}
            ),
            patch.object(
                db_mod.dump, "_run_pg_dump_streaming", side_effect=fake_pg_dump
            ),
            patch.object(odoo.db, "db_connect"),
        ):
            fh = db_mod.dump_db("db", None, "zip")
        try:
            assert fh.tell() == 0
            with zipfile.ZipFile(fh) as z:
                assert "dump.sql" in z.namelist()
        finally:
            fh.close()


class TestPublicReadVerbsAreMemoized:
    """``list_countries`` / ``list_lang`` are reachable with no authentication
    and no master password (verified over ``/jsonrpc``), and answer with a
    constant of the installation.  Re-parsing the shipped data on every
    anonymous call was pure waste — 1.17 ms per ``list_countries``.
    """

    def test_countries_xml_parsed_once(self, db_mod):
        db_mod.listing._scan_countries.cache_clear()
        try:
            with patch.object(
                db_mod.listing.ET, "parse", wraps=db_mod.listing.ET.parse
            ) as parse:
                first = db_mod.exp_list_countries()
                second = db_mod.exp_list_countries()
            assert parse.call_count == 1, "the country XML was re-parsed per call"
            assert first == second
        finally:
            db_mod.listing._scan_countries.cache_clear()

    def test_countries_result_is_not_shared_across_calls(self, db_mod):
        """Callers get a fresh mutable list; the cache cannot be corrupted."""
        db_mod.listing._scan_countries.cache_clear()
        try:
            first = db_mod.exp_list_countries()
            first.append(["zz", "Mutated"])
            first[0][0] = "hacked"
            second = db_mod.exp_list_countries()
            assert ["zz", "Mutated"] not in second
            assert second[0][0] != "hacked"
        finally:
            db_mod.listing._scan_countries.cache_clear()

    def test_countries_shape_is_list_of_lists(self, db_mod):
        """The RPC contract is ``[[code, name], ...]``, not tuples."""
        result = db_mod.exp_list_countries()
        assert isinstance(result, list)
        assert all(isinstance(row, list) and len(row) == 2 for row in result)

    def test_languages_csv_read_once(self):
        from odoo.tools import locale_utils

        locale_utils._scan_languages.cache_clear()
        try:
            with patch.object(
                locale_utils, "file_open", wraps=locale_utils.file_open
            ) as fo:
                first = locale_utils.scan_languages()
                second = locale_utils.scan_languages()
            assert fo.call_count == 1, "res.lang.csv was re-read per call"
            assert first == second
            assert isinstance(first, list)
        finally:
            locale_utils._scan_languages.cache_clear()

    def test_languages_result_is_not_shared_across_calls(self):
        from odoo.tools import locale_utils

        locale_utils._scan_languages.cache_clear()
        try:
            first = locale_utils.scan_languages()
            first.append(("zz_ZZ", "Mutated"))
            assert ("zz_ZZ", "Mutated") not in locale_utils.scan_languages()
        finally:
            locale_utils._scan_languages.cache_clear()

    def test_language_read_failure_is_not_cached(self):
        """A transient read failure must not become the process's permanent answer.

        ``functools.cache`` memoizes return values, so a fallback returned from
        INSIDE the cached function would pin itself forever.  The cached parse
        therefore raises and the wrapper owns the fallback.
        """
        from odoo.tools import locale_utils

        locale_utils._scan_languages.cache_clear()
        try:
            with patch.object(locale_utils, "file_open", side_effect=OSError("EIO")):
                degraded = locale_utils.scan_languages()
            assert degraded == [("en_US", "English")]

            recovered = locale_utils.scan_languages()
            assert len(recovered) > 1, (
                "a transient res.lang.csv failure was cached as the permanent answer"
            )
        finally:
            locale_utils._scan_languages.cache_clear()


class TestExpDropGate:
    """``exp_drop`` refuses an unexposed database the way its siblings do.

    It returned ``False`` instead of raising, which made the return value carry
    two meanings — "not exposed" and "no such database" — and the web caller
    (``web.controllers.database.drop``) collapsed both into
    ``Database %r was not found``.  An operator dropping a database they could
    see was told it did not exist, while ``exp_dump`` answered Access Denied for
    that same name.  Returning ``False`` bought no secrecy: ``drop`` is
    master-password gated, and a caller holding it can enumerate via ``list``.
    """

    def _patched(self, db_mod, exposed, dropped=True):
        import odoo

        return [
            patch.object(odoo.tools, "config", _MockConfig({"list_db": True})),
            patch.object(db_mod.listing, "list_dbs", return_value=exposed),
            patch.object(db_mod.lifecycle, "_drop_database", return_value=dropped),
        ]

    def test_unexposed_database_raises_access_denied(self, db_mod):
        from odoo.exceptions import AccessDenied

        with ExitStack() as stack:
            for p in self._patched(db_mod, ["visible"]):
                stack.enter_context(p)
            with pytest.raises(AccessDenied):
                db_mod.exp_drop("hidden")

    def test_unexposed_database_is_never_actually_dropped(self, db_mod):
        from odoo.exceptions import AccessDenied

        with ExitStack() as stack:
            for p in self._patched(db_mod, ["visible"])[:-1]:
                stack.enter_context(p)
            drop = stack.enter_context(patch.object(db_mod.lifecycle, "_drop_database"))
            with pytest.raises(AccessDenied):
                db_mod.exp_drop("hidden")
        drop.assert_not_called()

    def test_false_now_means_only_that_the_database_was_absent(self, db_mod):
        """The disambiguation the change buys: one meaning per return value."""
        with ExitStack() as stack:
            for p in self._patched(db_mod, ["gone"], dropped=False):
                stack.enter_context(p)
            assert db_mod.exp_drop("gone") is False

    def test_exposed_and_present_returns_true(self, db_mod):
        with ExitStack() as stack:
            for p in self._patched(db_mod, ["live"], dropped=True):
                stack.enter_context(p)
            assert db_mod.exp_drop("live") is True

    def test_gate_matches_its_siblings_exactly(self, db_mod):
        """Same allowlist, same reaction — the drift this closes."""
        from odoo.exceptions import AccessDenied

        with ExitStack() as stack:
            for p in self._patched(db_mod, ["visible"]):
                stack.enter_context(p)
            stack.enter_context(patch.object(db_mod.lifecycle, "_rename_database"))
            for call in (
                lambda: db_mod.exp_drop("hidden"),
                lambda: db_mod.exp_rename("hidden", "other"),
            ):
                with pytest.raises(AccessDenied):
                    call()


class TestUnpackBudgetAcceptsFileObjects:
    """``_unpack_budget`` sizes both a path and an open file object.

    ``odoo db load <url>`` streams a download into a ``SpooledTemporaryFile``
    and passes the object (not a path) to ``restore_db``; ``zipfile`` accepts
    it, but the expansion-budget sizing used ``Path(dump_file).stat()`` and
    raised ``TypeError`` on a file object, so the URL restore created the empty
    DB and then always failed and rolled it back.
    """

    def test_path_sizing_unchanged(self, db_mod, zip_dump):
        expected = pathlib.Path(zip_dump).stat().st_size
        assert db_mod.restore._source_size(zip_dump) == expected

    def test_spooled_temporary_file_is_sized_without_a_path(self, db_mod):
        import io as _io

        buf = _io.BytesIO(b"0123456789")
        assert db_mod.restore._source_size(buf) == 10
        # position is restored so the following zipfile read starts at 0
        assert buf.tell() == 0

    def test_spooled_temporary_file_position_is_preserved(self, db_mod):
        sp = tempfile.SpooledTemporaryFile(max_size=1024)  # noqa: SIM115  closed by GC; a `with` would hide the seek assertions below
        sp.write(b"abc" * 100)
        sp.seek(7)
        assert db_mod.restore._source_size(sp) == 300
        assert sp.tell() == 7

    def test_unpack_budget_does_not_raise_on_a_file_object(self, db_mod):
        """The exact failure B1 reproduced: previously a TypeError here."""
        sp = tempfile.SpooledTemporaryFile(max_size=1024)  # noqa: SIM115  as above
        sp.write(b"x" * 2048)
        sp.seek(0)
        budget = db_mod.restore._unpack_budget(sp)
        assert isinstance(budget, int) and budget > 0
