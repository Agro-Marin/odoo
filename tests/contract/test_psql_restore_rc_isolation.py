import os
import subprocess

import pytest

from .._pg import psql_path
from .conftest import requires_pg, requires_psql

_FAILING_SQL = """
SELECT 1 FROM a_table_that_does_not_exist;
CREATE TABLE rc_isolation_marker (id int);
"""

_POISON_RC = "\\set ON_ERROR_STOP off\n"


def _run_psql(scratch_db, sql_path, rc_path, *, with_x: bool):
    args = [psql_path(), "-d", scratch_db]
    if with_x:
        args.append("-X")
    args += ["-q", "-v", "ON_ERROR_STOP=1", "-f", str(sql_path)]
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PGDATABASE": scratch_db, "PSQLRC": str(rc_path)},
    )


@requires_pg
@requires_psql
class TestRestoreIgnoresHostPsqlrc:
    def _prepare(self, tmp_path):
        sql = tmp_path / "dump.sql"
        sql.write_text(_FAILING_SQL)
        rc = tmp_path / "poison.psqlrc"
        rc.write_text(_POISON_RC)
        return sql, rc

    def _marker_exists(self, scratch_db):
        out = subprocess.run(
            [
                psql_path(),
                "-d",
                scratch_db,
                "-X",
                "-tAc",
                "SELECT to_regclass('public.rc_isolation_marker') IS NOT NULL",
            ],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "PGDATABASE": scratch_db},
        )
        return out.stdout.strip() == "t"

    def test_with_x_the_poison_rc_is_ignored_and_the_error_aborts(
        self, scratch_db, tmp_path
    ):
        sql, rc = self._prepare(tmp_path)
        result = _run_psql(scratch_db, sql, rc, with_x=True)
        self_cleanup(scratch_db)
        assert result.returncode != 0, (
            "with -X, ON_ERROR_STOP must hold despite the host psqlrc"
        )
        assert not self._marker_exists(scratch_db), (
            "the statement after the error must not have run"
        )

    def test_without_x_the_poison_rc_really_disables_the_invariant(
        self, scratch_db, tmp_path
    ):
        sql, rc = self._prepare(tmp_path)
        result = _run_psql(scratch_db, sql, rc, with_x=False)
        marker = self._marker_exists(scratch_db)
        self_cleanup(scratch_db)
        assert result.returncode == 0
        assert marker, "without -X the poison rc should have let the script continue"


def self_cleanup(scratch_db):
    subprocess.run(
        [
            psql_path(),
            "-d",
            scratch_db,
            "-X",
            "-q",
            "-c",
            "DROP TABLE IF EXISTS rc_isolation_marker",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "PGDATABASE": scratch_db},
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
