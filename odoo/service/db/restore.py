import base64
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import IO, Literal

import odoo.api
import odoo.modules.neutralize
import odoo.tools
from odoo.tools.misc import exec_pg_environ, find_pg_tool

from .._db_helpers import check_db_management_enabled, validate_db_name
from .._dump_scanner import _assert_dump_sql_safe
from .._env import env_float, env_int
from .lifecycle import (
    _assert_filestore_dest_free,
    _create_empty_database,
    _rollback_new_database,
)
from .listing import exp_db_exist

_logger = logging.getLogger("odoo.service.db")


_RESTORE_MAX_EXPANSION_RATIO = 50


_RESTORE_MIN_UNPACKED_BYTES = 100 * 1024 * 1024


_EXTRACT_CHUNK_BYTES = 1024 * 1024


def _extract_members_bounded(
    z: zipfile.ZipFile, members: list[str], dest: str, budget: int
) -> int:
    dest_path = Path(dest)
    written = 0
    for member in members:
        info = z.getinfo(member)
        target = dest_path / member
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src, target.open("wb") as out:
            while chunk := src.read(_EXTRACT_CHUNK_BYTES):
                written += len(chunk)
                if written > budget:
                    raise RuntimeError(
                        f"Refusing to restore: the archive expands to more than "
                        f"{budget} bytes, over {_RESTORE_MAX_EXPANSION_RATIO}x its "
                        f"compressed size. Raise "
                        f"ODOO_RESTORE_MAX_EXPANSION_RATIO if this backup is "
                        f"genuinely that compressible."
                    )
                out.write(chunk)
    return written


def _source_size(dump_file: str | os.PathLike | IO[bytes]) -> int:
    if isinstance(dump_file, (str, os.PathLike)):
        return Path(dump_file).stat().st_size
    pos = dump_file.tell()
    try:
        dump_file.seek(0, os.SEEK_END)
        return dump_file.tell()
    finally:
        dump_file.seek(pos)


def _unpack_budget(dump_file: str | os.PathLike | IO[bytes]) -> int:
    ratio = env_int(
        "ODOO_RESTORE_MAX_EXPANSION_RATIO",
        _RESTORE_MAX_EXPANSION_RATIO,
        minimum=1,
        logger=_logger,
    )
    return max(_source_size(dump_file) * ratio, _RESTORE_MIN_UNPACKED_BYTES)


def _pg_restore_total_timeout() -> float:
    return env_float("ODOO_PG_RESTORE_TOTAL_TIMEOUT", 3600.0, logger=_logger)


@check_db_management_enabled
def exp_restore(db_name: str, data: str, copy: bool = False) -> Literal[True]:
    """Restore a database from a base64-encoded dump string.

    ``data`` is the base64 body of a zip (v8+) or raw pg_dump custom format.
    Whitespace is tolerated: the accumulator below strips it per-chunk and
    buffers un-decoded chars so every ``b64decode`` gets a multiple of 4 chars
    (chunk boundaries landing mid-group on a 76-char wrap used to crash decoding).

    ``copy=True`` forces a new dbuuid so the restore can coexist with the original.
    """
    _STRIP_WS = str.maketrans("", "", " \t\n\r\v\f")
    CHUNK = 8192

    data_file = tempfile.NamedTemporaryFile(delete=False)  # noqa: SIM115  delete=False: the path outlives this scope
    try:
        accum = ""
        for i in range(0, len(data), CHUNK):
            accum += data[i : i + CHUNK].translate(_STRIP_WS)
            n_complete = (len(accum) // 4) * 4
            if n_complete:
                data_file.write(base64.b64decode(accum[:n_complete]))
                accum = accum[n_complete:]
        if accum:
            data_file.write(base64.b64decode(accum))
        data_file.close()
        restore_db(db_name, data_file.name, copy=copy)
    finally:
        data_file.close()
        Path(data_file.name).unlink(missing_ok=True)
    return True


@check_db_management_enabled
def restore_db(
    db: str,
    dump_file: str | os.PathLike | IO[bytes],
    copy: bool = False,
    neutralize_database: bool = False,
) -> None:
    if not isinstance(db, str):
        raise TypeError(f"db must be a str, got {type(db).__name__!r}")
    validate_db_name(db)
    if exp_db_exist(db):
        _logger.warning("RESTORE DB: %s already exists", db)
        raise RuntimeError(f"Database {db!r} already exists")

    fs_dest = odoo.tools.config.filestore(db)
    _assert_filestore_dest_free(fs_dest, f"Cannot restore to {db!r}")

    _logger.info("RESTORING DB: %s", db)
    _create_empty_database(
        db, template="template0", force_unaccent=True, setup_if_exists=False
    )

    filestore_path = None
    try:
        with tempfile.TemporaryDirectory() as dump_dir:
            if zipfile.is_zipfile(dump_file):
                with zipfile.ZipFile(dump_file, "r") as z:
                    dump_dir_resolved = Path(dump_dir).resolve()
                    for member in z.namelist():
                        target = (dump_dir_resolved / member).resolve()
                        if not target.is_relative_to(dump_dir_resolved):
                            raise RuntimeError(
                                f"Refusing to restore: archive member {member!r} "
                                f"escapes the extraction directory"
                            )

                    if "dump.sql" not in z.namelist():
                        raise RuntimeError(
                            "Refusing to restore: the archive contains no "
                            "'dump.sql' member, so it is not an Odoo database "
                            "backup."
                        )

                    filestore = [m for m in z.namelist() if m.startswith("filestore/")]
                    _extract_members_bounded(
                        z,
                        ["dump.sql"] + filestore,
                        dump_dir,
                        _unpack_budget(dump_file),
                    )

                    if filestore:
                        filestore_path = str(Path(dump_dir, "filestore"))

                dump_sql_path = str(Path(dump_dir, "dump.sql"))
                _assert_dump_sql_safe(dump_sql_path)

                pg_cmd = "psql"
                pg_args = [
                    "-X",
                    "-q",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-f",
                    dump_sql_path,
                ]

            else:
                if not isinstance(dump_file, (str, os.PathLike)):
                    raise TypeError(
                        "a raw (non-zip) restore needs a file path, not an open "
                        "file object"
                    )
                pg_cmd = "pg_restore"
                pg_args = ["--no-owner", "--exit-on-error", os.fspath(dump_file)]

            _timeout = _pg_restore_total_timeout()
            try:
                r = subprocess.run(
                    [find_pg_tool(pg_cmd), "--dbname=" + db, *pg_args],
                    env=exec_pg_environ(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=_timeout,
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(
                    f"Restore of {db!r} exceeded {_timeout:.0f}s wall-clock "
                    f"timeout and was terminated.  Set "
                    f"ODOO_PG_RESTORE_TOTAL_TIMEOUT for slower restores."
                ) from e
            if r.returncode != 0:
                _logger.error("RESTORE DB %r failed:\n%s", db, r.stderr)
                raise RuntimeError(
                    f"Couldn't restore database {db!r}:\n{r.stderr.strip()}"
                )

            registry = odoo.modules.registry.Registry.new(db, run_tests=False)
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, odoo.api.SUPERUSER_ID, {})
                if copy:
                    env["ir.config_parameter"].init(force=True)
                if neutralize_database:
                    odoo.modules.neutralize.neutralize_database(cr)

                if filestore_path:
                    filestore_dest = env["ir.attachment"]._filestore()
                    if Path(filestore_dest).exists():
                        raise RuntimeError(
                            f"Filestore {filestore_dest!r} appeared between "
                            f"pre-flight and move (race)."
                        )
                    shutil.move(filestore_path, filestore_dest)

        _logger.info("RESTORE DB: %s", db)
    except Exception:
        _rollback_new_database(db, "RESTORE DB")
        raise
