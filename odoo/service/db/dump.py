import base64
import functools
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import zipfile
from contextlib import suppress
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

import odoo.db
import odoo.release
import odoo.tools
from odoo.tools.misc import exec_pg_environ, find_pg_tool

from .._db_helpers import check_db_management_enabled, validate_db_name
from .._env import env_float
from .listing import check_db_exposed

if TYPE_CHECKING:
    from odoo.db import BaseCursor
else:
    BaseCursor = Any

_logger = logging.getLogger("odoo.service.db")


BACKUP_FORMATS = frozenset({"zip", "dump"})


def _pg_dump_total_timeout() -> float:
    return env_float("ODOO_PG_DUMP_TOTAL_TIMEOUT", 3600.0, logger=_logger)


@check_db_management_enabled
def exp_dump(db_name: str, backup_format: str) -> str:
    check_db_exposed(db_name)
    CHUNK_SIZE = 3 * 1024 * 1024
    encoded = bytearray()
    with tempfile.TemporaryFile(mode="w+b") as t:
        dump_db(db_name, t, backup_format)
        t.seek(0)
        while chunk := t.read(CHUNK_SIZE):
            encoded.extend(base64.b64encode(chunk))
    return encoded.decode("ascii")


def dump_db_manifest(cr: BaseCursor) -> dict[str, Any]:
    v = cr.connection.info.server_version
    pg_version = f"{v // 10000}.{v // 100 % 100}"
    cr.execute(
        "SELECT name, db_version FROM ir_module_module WHERE state = 'installed'"
    )
    modules = dict(cr.fetchall())
    return {
        "odoo_dump": "1",
        "db_name": cr.dbname,
        "version": odoo.release.version,
        "version_info": odoo.release.version_info,
        "major_version": odoo.release.major_version,
        "pg_version": pg_version,
        "modules": modules,
    }


def _timed_out(timeout: float) -> RuntimeError:
    return RuntimeError(
        f"pg_dump exceeded {timeout:.0f}s wall-clock timeout and was "
        f"terminated.  Set ODOO_PG_DUMP_TOTAL_TIMEOUT for slower DBs."
    )


def _failed(returncode: int, stderr: bytes) -> RuntimeError:
    return RuntimeError(
        f"pg_dump failed (exit {returncode}): {stderr.decode(errors='replace').strip()}"
    )


def _run_pg_dump_blocking(cmd: list[str], env: dict, *, stdout: Any) -> None:
    timeout = _pg_dump_total_timeout()
    try:
        result = subprocess.run(
            cmd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise _timed_out(timeout) from e
    if result.returncode != 0:
        raise _failed(result.returncode, result.stderr)


_STALL_SIGKILL_GRACE_S = 10.0


_STDERR_DRAIN_JOIN_S = 10.0


def _drain_pipe(pipe: IO[bytes], sink: list[bytes]) -> None:
    try:
        while chunk := pipe.read(4096):
            sink.append(chunk)
    except OSError, ValueError:
        pass


def _kill_pg_dump_on_stall(
    proc: subprocess.Popen, total_timeout: float, stall_killed: list[bool]
) -> None:
    stall_killed[0] = True
    _logger.error(
        "pg_dump exceeded total wall-clock timeout (%.0fs); sending SIGTERM",
        total_timeout,
    )
    with suppress(ProcessLookupError):
        proc.terminate()
    try:
        proc.wait(timeout=_STALL_SIGKILL_GRACE_S)
    except subprocess.TimeoutExpired:
        _logger.error(
            "pg_dump ignored SIGTERM %.0fs after stall; sending SIGKILL",
            _STALL_SIGKILL_GRACE_S,
        )
        with suppress(ProcessLookupError):
            proc.kill()


def _reap_pg_dump(proc: subprocess.Popen) -> None:
    wait_timeout = env_float("ODOO_PG_DUMP_WAIT_TIMEOUT", 30.0, logger=_logger)
    try:
        proc.wait(timeout=wait_timeout)
    except subprocess.TimeoutExpired:
        _logger.error(
            "pg_dump did not exit within %.0fs after stdout EOF; sending SIGTERM",
            wait_timeout,
        )
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _logger.error("pg_dump still alive; sending SIGKILL")
            proc.kill()
            proc.wait()


def _run_pg_dump_streaming(cmd: list[str], env: dict, stream: IO[bytes]) -> None:
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.stdout, proc.stderr
    assert stdout is not None and stderr is not None

    stderr_chunks: list[bytes] = []
    stderr_thread = threading.Thread(
        target=_drain_pipe,
        args=(stderr, stderr_chunks),
        name="odoo.service.db.pg_dump.stderr",
        daemon=True,
    )
    stderr_thread.start()

    total_timeout = _pg_dump_total_timeout()
    stall_killed = [False]
    stall_timer = threading.Timer(
        total_timeout,
        functools.partial(_kill_pg_dump_on_stall, proc, total_timeout, stall_killed),
    )
    stall_timer.daemon = True
    stall_timer.start()
    try:
        shutil.copyfileobj(stdout, stream)
    finally:
        stall_timer.cancel()
        stdout.close()
        stderr_thread.join(timeout=_STDERR_DRAIN_JOIN_S)
        if stderr_thread.is_alive():
            _logger.warning(
                "pg_dump stderr drain still running after %.0fs; leaving the "
                "pipe to the interpreter",
                _STDERR_DRAIN_JOIN_S,
            )
        else:
            stderr.close()
        _reap_pg_dump(proc)
    if stall_killed[0] and proc.returncode != 0:
        raise _timed_out(total_timeout)
    if proc.returncode != 0:
        raise _failed(proc.returncode, b"".join(stderr_chunks))


def _zip_filestore_into(zipf: zipfile.ZipFile, filestore: str) -> None:
    root = Path(filestore)
    if not root.is_dir():
        return
    root_real = os.path.realpath(root)
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in sorted(filenames):
            fpath = Path(dirpath, fname)
            real = os.path.realpath(fpath)
            if not Path(real).is_file():
                continue
            if os.path.commonpath([root_real, real]) != root_real:
                _logger.warning(
                    "DUMP DB: skipping filestore entry %r, it resolves outside "
                    "the filestore (%r)",
                    str(fpath),
                    real,
                )
                continue
            zipf.write(fpath, str(Path("filestore", fpath.relative_to(root))))


def _write_zip_dump(
    db_name: str,
    stream: IO[bytes],
    cmd: list[str],
    env: dict,
    with_filestore: bool,
) -> None:
    with zipfile.ZipFile(
        stream, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
    ) as zipf:
        db = odoo.db.db_connect(db_name)
        with db.cursor() as cr:
            manifest = dump_db_manifest(cr)
        zipf.writestr("manifest.json", json.dumps(manifest, indent=4))
        with zipf.open("dump.sql", "w", force_zip64=True) as sql_member:
            _run_pg_dump_streaming(cmd, env, sql_member)
        if with_filestore:
            _zip_filestore_into(zipf, odoo.tools.config.filestore(db_name))


@check_db_management_enabled
def dump_db(
    db_name: str,
    stream: IO[bytes] | None,
    backup_format: str = "zip",
    with_filestore: bool = True,
) -> IO[bytes] | None:
    validate_db_name(db_name)
    if backup_format not in BACKUP_FORMATS:
        raise ValueError(
            f"Invalid backup format {backup_format!r}: expected one of "
            f"{', '.join(sorted(BACKUP_FORMATS))}."
        )

    _logger.info(
        "DUMP DB: %s format %s %s",
        db_name,
        backup_format,
        "with filestore" if with_filestore else "without filestore",
    )

    cmd = [find_pg_tool("pg_dump"), "--no-owner", db_name]
    env = exec_pg_environ()

    if backup_format == "zip":
        if stream:
            _write_zip_dump(db_name, stream, cmd, env, with_filestore)
        else:
            t = tempfile.TemporaryFile()  # noqa: SIM115  `t` IS the return value; the caller owns and closes it
            try:
                _write_zip_dump(db_name, t, cmd, env, with_filestore)
                t.seek(0)
            except BaseException:
                t.close()
                raise
            return t
    else:
        cmd.insert(-1, "--format=c")
        if stream:
            _run_pg_dump_streaming(cmd, env, stream)
        else:
            t = tempfile.TemporaryFile()  # noqa: SIM115  returned to the caller, as above
            try:
                _run_pg_dump_blocking(cmd, env, stdout=t)
                t.seek(0)
            except BaseException:
                t.close()
                raise
            return t
    return None
