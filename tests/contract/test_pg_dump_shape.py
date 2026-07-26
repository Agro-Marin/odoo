"""What ``pg_dump`` actually emits, versus what the restore scanner allows.

``_dump_scanner._ALLOWED_PSQL_META_COMMANDS`` pins each permitted meta-command
to the ARGUMENT shape a real dump carries — ``\\restrict <alphanumeric key>``,
the matching ``\\unrestrict``, and ``\\.`` alone on its line.  That pinning is
what closes the restore RCE (an argument opening a lexical context, or a
backtick psql expands as a shell command), but it is only safe if it is really
what ``pg_dump`` emits.

Get that wrong in the tight direction and every backup stops restoring; get it
wrong in the loose direction and the RCE reopens.  Neither is detectable from
our own source, so it is measured here against the installed ``pg_dump``.
"""

import re
import subprocess

import pytest

from odoo.service._dump_scanner import (
    _ALLOWED_PSQL_META_COMMANDS,
    _assert_dump_sql_safe,
)

from .conftest import PG_DUMP, requires_pg, requires_pg_dump

# A dump's COPY data is read verbatim by psql and is NOT lexed, so its lines --
# including the ``\N`` NULL marker -- are not meta-commands.  Blocks start with
# a COPY ... FROM stdin statement and end at a line that is exactly ``\.``.
_COPY_START = re.compile(r"^COPY .* FROM stdin;\s*$")


def _meta_command_lines(sql: str) -> list[str]:
    """Every line psql would lex as a meta-command (i.e. outside COPY data)."""
    out, in_copy = [], False
    for line in sql.split("\n"):
        if in_copy:
            if line == "\\.":
                in_copy = False
            continue
        if _COPY_START.match(line):
            in_copy = True
            continue
        if line.startswith("\\"):
            out.append(line)
    return out


@pytest.fixture(scope="module")
def dump_sql(scratch_db):
    """One plain-format dump of a database with real structure.

    Built once: the scratch DB is session-scoped, so populating it per test
    would fail on the second run — and the dump is the same input for every
    assertion below anyway.  Structure chosen to exercise the lexical contexts
    the scanner cares about: a COPY data block (with a ``\\N`` NULL marker and
    an embedded quote), and a dollar-quoted function body.
    """
    subprocess.run(
        [
            "psql",
            "-d",
            scratch_db,
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            """
        CREATE TABLE t (id serial PRIMARY KEY, txt text);
        INSERT INTO t (txt) VALUES ('a'), (NULL), ('has ; and '' quote');
        CREATE FUNCTION f() RETURNS int AS $$ BEGIN RETURN 1; END; $$
          LANGUAGE plpgsql;
        """,
        ],
        check=True,
        capture_output=True,
    )
    proc = subprocess.run(
        [PG_DUMP, "--no-owner", scratch_db], check=True, capture_output=True, text=True
    )
    return proc.stdout


@requires_pg
@requires_pg_dump
class TestPgDumpMetaCommandShape:
    def test_only_allowlisted_verbs_are_emitted(self, dump_sql):
        """If pg_dump grows a new meta-command, the scanner must learn about it
        deliberately — not discover it when a restore starts being refused."""
        sql = dump_sql
        for line in _meta_command_lines(sql):
            verb = line.split(maxsplit=1)[0]
            assert verb in _ALLOWED_PSQL_META_COMMANDS, (
                f"pg_dump emits {verb!r}, which the restore scanner rejects; a "
                f"backup from this pg_dump would refuse to restore. Line: {line!r}"
            )

    def test_every_emitted_argument_matches_its_pinned_pattern(self, dump_sql):
        """The argument shape, not just the verb — this is the half that closed
        the RCE, and the half a tighter-than-reality pattern would break."""
        sql = dump_sql
        for line in _meta_command_lines(sql):
            verb = line.split(maxsplit=1)[0]
            pattern = _ALLOWED_PSQL_META_COMMANDS[verb]
            assert pattern.match(line, len(verb)), (
                f"pg_dump emits {line!r}, whose argument does not match the "
                f"pattern pinned for {verb!r}; real backups would be refused"
            )

    def test_restrict_key_is_alphanumeric(self, dump_sql):
        """``\\restrict``'s key is why the pattern can be as tight as it is.

        psql itself accepts far more (``$$`` and ``/*`` are both accepted keys —
        which is precisely how the desync bypass worked), so the scanner's
        narrowness rests on pg_dump's generator, not on psql's parser.
        """
        sql = dump_sql
        keys = [
            line.split(maxsplit=1)[1].strip()
            for line in _meta_command_lines(sql)
            if line.startswith(("\\restrict ", "\\unrestrict "))
        ]
        for key in keys:
            assert re.fullmatch(r"[A-Za-z0-9]+", key), (
                f"pg_dump's restrict key {key!r} is not alphanumeric; the "
                f"scanner's pinned argument pattern is too tight"
            )
        if keys:
            assert len(set(keys)) == 1, "restrict/unrestrict keys must match"

    def test_a_real_dump_passes_the_scanner(self, dump_sql, tmp_path):
        """End to end: the property every one of the above exists to protect."""
        sql = dump_sql
        path = tmp_path / "dump.sql"
        path.write_text(sql, encoding="latin-1")
        _assert_dump_sql_safe(str(path))  # must not raise
