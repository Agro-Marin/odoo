import base64
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

# The log channel stays "odoo.service.db" across the split: operators and
# log-reading tests key on it, and _db_helpers / _dump_scanner already spell
# it literally for the same reason.
_logger = logging.getLogger("odoo.service.db")


BACKUP_FORMATS = frozenset({"zip", "dump"})


def _pg_dump_total_timeout() -> float:
    return env_float("ODOO_PG_DUMP_TOTAL_TIMEOUT", 3600.0, logger=_logger)


@check_db_management_enabled
def exp_dump(db_name: str, backup_format: str) -> str:
    """Dump the database and return its base64-encoded content.

    Encodes in 3 MiB chunks against an on-disk tempfile, so the raw bytes never
    sit in memory; peak is still ~8N/3 (accumulator + final ``str`` during
    ``decode``), so a multi-GB dump doubles RSS — use ``dump_db(..., stream=...)``
    for true streaming.

    Note the web backup UI does NOT call this: it uses ``dump_db(name, None, ...)``
    and hands the temp file to werkzeug directly, avoiding the base64 round-trip.
    The only true-streaming caller is the ``odoo db dump`` CLI.
    """
    check_db_exposed(db_name)
    CHUNK_SIZE = 3 * 1024 * 1024
    encoded = bytearray()
    with tempfile.TemporaryFile(mode="w+b") as t:
        dump_db(db_name, t, backup_format)
        t.seek(0)
        while chunk := t.read(CHUNK_SIZE):
            encoded.extend(base64.b64encode(chunk))
    return encoded.decode("ascii")


@check_db_management_enabled
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
        raise RuntimeError(
            f"pg_dump exceeded {timeout:.0f}s wall-clock timeout and was "
            f"terminated.  Set ODOO_PG_DUMP_TOTAL_TIMEOUT for slower DBs."
        ) from e
    if result.returncode != 0:
        raise RuntimeError(
            f"pg_dump failed (exit {result.returncode}): "
            f"{result.stderr.decode(errors='replace').strip()}"
        )


_STALL_SIGKILL_GRACE_S = 10.0


_STDERR_DRAIN_JOIN_S = 10.0


def _run_pg_dump_streaming(cmd: list[str], env: dict, stream: IO[bytes]) -> None:
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stderr_chunks: list[bytes] = []

    def _drain_stderr() -> None:
        try:
            while chunk := proc.stderr.read(4096):
                stderr_chunks.append(chunk)
        except OSError, ValueError:
            pass

    stderr_thread = threading.Thread(
        target=_drain_stderr, name="odoo.service.db.pg_dump.stderr", daemon=True
    )
    stderr_thread.start()

    total_timeout = _pg_dump_total_timeout()
    stall_killed = [False]

    def _kill_on_stall() -> None:
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

    stall_timer = threading.Timer(total_timeout, _kill_on_stall)
    stall_timer.daemon = True
    stall_timer.start()
    try:
        shutil.copyfileobj(proc.stdout, stream)
    finally:
        stall_timer.cancel()
        proc.stdout.close()
        stderr_thread.join(timeout=_STDERR_DRAIN_JOIN_S)
        if stderr_thread.is_alive():
            _logger.warning(
                "pg_dump stderr drain still running after %.0fs; leaving the "
                "pipe to the interpreter",
                _STDERR_DRAIN_JOIN_S,
            )
        else:
            proc.stderr.close()
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
    stderr_output = b"".join(stderr_chunks)
    if stall_killed[0] and proc.returncode != 0:
        raise RuntimeError(
            f"pg_dump exceeded {total_timeout:.0f}s wall-clock timeout and was "
            f"terminated.  Set ODOO_PG_DUMP_TOTAL_TIMEOUT for slower DBs."
        )
    if proc.returncode != 0:
        raise RuntimeError(
            f"pg_dump failed (exit {proc.returncode}): "
            f"{stderr_output.decode(errors='replace').strip()}"
        )


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
        # force_zip64 is mandatory, not defensive: streaming into a member
        # through ``ZipFile.open(..., "w")`` commits the local header before a
        # single byte is read, so zipfile cannot infer that the member needs
        # ZIP64 the way ``ZipFile.write()`` does from a stat().  Without it a
        # ``dump.sql`` that overruns 4 GiB raises "File size too large, try
        # using force_zip64" at member close — after minutes of dumping, and
        # only once the database grows past the threshold.  ``allowZip64`` on
        # the archive covers the central directory, not this.
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
            # SIM115: `t` IS the return value — the caller owns and closes it.
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
