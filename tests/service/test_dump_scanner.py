"""Pure-pytest tests for ``odoo.service._dump_scanner``.

The scanner decides ONE question: would ``psql -f`` execute a backslash
meta-command in this ``dump.sql``?  A restore replays an attacker-supplied file
through ``psql``, which interprets ``\\!`` as a shell escape, so any place this
lexer disagrees with psql's is a remote code execution, not a near miss.

These tests lived in ``test_db.py`` and reached the functions through a
``odoo.service.db`` re-export.  They are the coverage for the restore RCE and
nobody hunting for it would have grepped a 3500-line file about database verbs
— the same argument that moved ``TestAdminGates`` out of ``test_server.py``.
``tests/contract/test_psql_scanner_differential.py`` already imported this
module honestly; this file now does too.

The scanner is only as good as its agreement with the real program.  That
comparison cannot be made here — it needs a live ``psql`` — and lives in
``tests/contract/test_psql_scanner_differential.py`` (separate invocation).
Treat the two as one suite: this file pins the lexer's own behaviour, that one
pins it against the lexer it is imitating.

Run with::

    python -m pytest tests/service/test_dump_scanner.py -v
"""

import pathlib
import tempfile
from unittest.mock import patch

import pytest

from odoo.service import _dump_scanner


@pytest.fixture(scope="module")
def db_mod():
    """The module under test.

    Named ``db_mod`` because these classes were written against
    ``odoo.service.db``'s re-exports; the underlying functions are the same
    objects, so the tests are unchanged by the move.
    """
    return _dump_scanner


class TestDumpSqlMetaCommandScanner:
    """``psql -f`` interprets backslash meta-commands, and the restored
    ``dump.sql`` is attacker-controlled, so the scanner must reject anything
    ``psql`` would execute (``\\!`` shell, ``\\i``/``\\o``/``\\copy`` files,
    ``\\gexec``, ``\\connect``) while never flagging content that ``psql`` treats
    as data/text (COPY blocks, string literals, dollar-quoted bodies, comments).
    """

    @pytest.mark.parametrize(
        "sql",
        [
            "\\! touch /tmp/pwn\n",
            "SELECT 1;\\! id\n",
            "SELECT 1;\n\\i /etc/passwd\n",
            "SELECT 1 \\gexec\n",
            "\\connect postgres\n",
            "\\o /tmp/out\nSELECT 1;\n",
            "COPY t FROM stdin;\n1\ta\n\\.\n\\! id\n",
        ],
    )
    def test_flags_interpreted_meta_commands(self, db_mod, sql):
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1;\n",
            "\\restrict TOK\nSELECT 1;\n\\unrestrict TOK\n",
            "COPY t FROM stdin;\n1\tdata\\x\\.more\n\\.\nSELECT 1;\n",
            "CREATE FUNCTION f() AS $$ BEGIN RETURN 'x; \\y'; END; $$ LANGUAGE plpgsql;\n",
            "SELECT E'a\\nb\\\\c';\n",
            "-- a comment with \\! and \\i\nSELECT 1;\n",
            "/* block \\! comment ; \\i */\nSELECT 1;\n",
            "SELECT 'literal ; \\! not a command';\n",
        ],
    )
    def test_allows_data_and_pg_dump_commands(self, db_mod, sql):
        assert db_mod._find_disallowed_psql_meta_command(sql) is None

    def test_assert_dump_sql_safe_raises_on_evil_file(self, db_mod):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".sql", delete=False, encoding="utf-8"
        ) as f:
            f.write("\\! touch /tmp/pwn\nSELECT 1;\n")
            path = f.name
        try:
            with pytest.raises(RuntimeError, match="Refusing to restore"):
                db_mod._assert_dump_sql_safe(path)
        finally:
            pathlib.Path(path).unlink()

    def test_assert_dump_sql_safe_passes_clean_file(self, db_mod):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".sql", delete=False, encoding="utf-8"
        ) as f:
            f.write("\\restrict TOK\nCREATE TABLE t (id int);\n\\unrestrict TOK\n")
            path = f.name
        try:
            db_mod._assert_dump_sql_safe(path)
        finally:
            pathlib.Path(path).unlink()


class TestDumpSqlMetaCommandArguments:
    """An ALLOWED meta-command does not make its argument inert.

    The scanner used to accept ``\\restrict`` / ``\\unrestrict`` / ``\\.`` on the
    verb alone and then resume **SQL** lexing on the rest of the line.  psql does
    neither: it lexes that text as the command's ARGUMENT, with its own quoting
    and with backtick command substitution.  Both divergences were live RCE
    bypasses of this whole module (verified against psql 18.4):

    * ``\\restrict `cmd` `` — psql runs ``cmd`` in a SHELL while expanding the
      argument, BEFORE it validates it.  The ``\\restrict`` then fails, so the
      restore aborts — after the command has already run.
    * ``\\restrict /*`` + ``\\unrestrict /*`` — psql takes ``/*`` as the restrict
      key and is back in ordinary SQL on line 3, while the scanner is inside a
      nested block comment for the remainder of the file: every later ``\\!`` was
      skipped as "comment", and psql exited **0**, so the restore reported
      success.

    Real ``pg_dump`` output carries exactly ``\\restrict <alphanumeric key>``,
    the matching ``\\unrestrict``, and ``\\.`` alone on its line — so pinning the
    argument shape closes both without touching a legitimate backup.
    """

    @pytest.mark.parametrize(
        "sql",
        [
            "\\restrict `touch /tmp/pwn`\n",
            "\\unrestrict `touch /tmp/pwn`\n",
            "\\restrict /*\n\\unrestrict /*\n\\! id\n",
            "\\restrict $$\n\\unrestrict $$\n\\! id\n",
            "\\restrict '\n\\! id\n",
            '\\restrict "\n\\! id\n',
            "\\unrestrict /*\n\\! id\n",
            "\\. /*\n\\! id\n",
            "\\. `touch /tmp/pwn`\n",
            "\\restrict\n",
            "\\restrict k1 extra\n",
        ],
    )
    def test_flags_malformed_meta_command_arguments(self, db_mod, sql):
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    def test_report_names_the_argument_not_just_the_verb(self, db_mod):
        """The verb alone ("\\restrict") would read as a false positive on the
        pg_dump wrapper; the operator has to see the argument to act on it."""
        hit = db_mod._find_disallowed_psql_meta_command("\\restrict `id`\n")
        assert hit is not None
        assert "`id`" in hit[1]

    @pytest.mark.parametrize(
        "sql",
        [
            "\\restrict abc123\nSELECT 1;\n\\unrestrict abc123\n",
            "\\restrict tH7nmJAc12qRGNgZNXhGPXxv78E3UN0d5YagNMhRvb9i2u49YBGiEpyi0gW9RHO\n",
            "\\restrict abc123\r\n",
            "\\restrict abc123",
            "COPY t (a) FROM stdin;\n1\n\\.\nSELECT 1;\n",
        ],
    )
    def test_allows_real_pg_dump_shapes(self, db_mod, sql):
        assert db_mod._find_disallowed_psql_meta_command(sql) is None

    def test_argument_text_is_not_lexed_as_sql(self, db_mod):
        """The scanner must not carry a lexical context out of argument text.

        A quote in a REJECTED argument is moot (the restore stops), so this pins
        the positive case: after a well-formed ``\\restrict`` the scanner is back
        in plain SQL and still catches what follows.
        """
        sql = "\\restrict k1\nSELECT 1;\n\\! id\n"
        hit = db_mod._find_disallowed_psql_meta_command(sql)
        assert hit == (3, "\\!")


class TestDumpSqlScannerLineBound:
    """The scanner's "peak is one line" guarantee only holds if the line length
    is enforced — the attacker picks it.

    A newline-free ``dump.sql`` restores exactly the O(file) memory peak the
    streaming rewrite existed to remove (measured: a 419 MB single line drove RSS
    to 879 MB), inside the very worker a memory soft limit watches.
    """

    def _write(self, tmp_path, text):
        p = tmp_path / "dump.sql"
        p.write_text(text, encoding="latin-1")
        return str(p)

    def test_overlong_line_is_refused(self, db_mod, tmp_path, monkeypatch):
        monkeypatch.setenv("ODOO_DUMP_SCAN_MAX_LINE", str(4 * 1024 * 1024))
        path = self._write(tmp_path, "SELECT '" + "A" * (5 * 1024 * 1024) + "';\n")
        with pytest.raises(RuntimeError, match="longer than"):
            db_mod._assert_dump_sql_safe(path)

    def test_line_at_the_limit_is_accepted(self, db_mod, tmp_path, monkeypatch):
        """The cap must reject only what it must: a long-but-bounded line — a wide
        ``COPY`` data row — is ordinary in a real dump (~1.7 MB measured)."""
        monkeypatch.setenv("ODOO_DUMP_SCAN_MAX_LINE", str(4 * 1024 * 1024))
        path = self._write(tmp_path, "SELECT '" + "A" * (2 * 1024 * 1024) + "';\n")
        db_mod._assert_dump_sql_safe(path)

    def test_cap_does_not_blind_the_scanner(self, db_mod, tmp_path, monkeypatch):
        """A meta-command BEFORE an over-long line must still be reported as the
        meta-command it is, not masked by the length refusal."""
        monkeypatch.setenv("ODOO_DUMP_SCAN_MAX_LINE", str(4 * 1024 * 1024))
        path = self._write(
            tmp_path, "\\! touch /tmp/pwn\nSELECT '" + "A" * (9 * 1024 * 1024) + "';\n"
        )
        with pytest.raises(RuntimeError, match="meta-command"):
            db_mod._assert_dump_sql_safe(path)

    def test_malformed_env_override_falls_back_to_the_default(
        self, db_mod, tmp_path, monkeypatch
    ):
        """Every ODOO_* knob in this package degrades to its default on garbage
        rather than aborting the operation."""
        monkeypatch.setenv("ODOO_DUMP_SCAN_MAX_LINE", "not-a-number")
        path = self._write(tmp_path, "SELECT 1;\n")
        db_mod._assert_dump_sql_safe(path)

    def test_overlong_copy_data_line_is_accepted(self, db_mod, tmp_path, monkeypatch):
        """The cap applies to SQL-context lines only.  A COPY-DATA line over the
        cap — e.g. an in-database ``ir.attachment.db_datas`` row — is bulk data
        psql reads verbatim (never lexed, the ``\\.`` terminator is 2 chars), so
        refusing it would block a legitimate dump.  Stream past it instead."""
        monkeypatch.setenv("ODOO_DUMP_SCAN_MAX_LINE", str(4 * 1024 * 1024))
        big = "QUJD" * (2 * 1024 * 1024)
        path = self._write(
            tmp_path,
            "CREATE TABLE ir_attachment (id int, db_datas text);\n"
            "COPY ir_attachment (id, db_datas) FROM stdin;\n"
            f"1\t{big}\n\\.\nSELECT 1;\n",
        )
        db_mod._assert_dump_sql_safe(path)

    def test_overlong_copy_data_does_not_blind_a_later_meta_command(
        self, db_mod, tmp_path, monkeypatch
    ):
        """Streaming past an over-cap COPY-DATA line must not swallow the ``\\!``
        that follows once a short ``\\.`` closes the data block: the attacker's
        only way out of copy-data mode is a 2-char ``\\.`` line, which is scanned
        normally, so the meta-command after it is still caught."""
        monkeypatch.setenv("ODOO_DUMP_SCAN_MAX_LINE", str(4 * 1024 * 1024))
        big = "QUJD" * (2 * 1024 * 1024)
        path = self._write(
            tmp_path,
            f"COPY t (a) FROM stdin;\n{big}\n\\.\n\\! touch /tmp/pwn\n",
        )
        with pytest.raises(RuntimeError, match="meta-command"):
            db_mod._assert_dump_sql_safe(path)

    def test_overlong_sql_line_still_refused(self, db_mod, tmp_path, monkeypatch):
        """Outside copy-data context, an over-cap line is still unscannable within
        the bound and absent from any real dump — refuse it (the drain path must
        NOT apply here)."""
        monkeypatch.setenv("ODOO_DUMP_SCAN_MAX_LINE", str(4 * 1024 * 1024))
        path = self._write(tmp_path, "SELECT '" + "A" * (8 * 1024 * 1024) + "';\n")
        with pytest.raises(RuntimeError, match="longer than"):
            db_mod._assert_dump_sql_safe(path)


class TestDumpSqlScannerLexerDivergence:
    """The scanner only protects the restore if its lexical contexts match
    ``psql``'s exactly.

    Any input that makes the scanner *enter* a context psql is not in is a total
    bypass, not a near miss: the phantom context's terminator never arrives, so
    the whole rest of the dump is swallowed as "data" and reported safe while
    psql executes it.  Both cases below were verified end-to-end against
    PostgreSQL 18 — ``psql -f`` ran the shell command, the second one while still
    exiting 0, so the restore reported success and nothing was rolled back.
    """

    @pytest.mark.parametrize("ident", ["a$b$c", "money$usd$x", "éx$q$z", "_a$t$b"])
    def test_dollar_inside_identifier_does_not_open_a_quoted_body(self, db_mod, ident):
        sql = f"CREATE TABLE {ident} (x int);\n\\! touch /tmp/pwn\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    @pytest.mark.parametrize(
        "expr",
        [
            "SELECT 1 AS 9a$b$c",
            "SELECT 1 AS a1$t$",
            "SELECT 1 AS 0fooE$t$x",
            "SELECT 1 AS ÿ$_$",
            "SELECT 1 AS +9fooE$$z",
        ],
    )
    def test_digit_led_run_restarts_at_the_identifier(self, db_mod, expr):
        sql = f"{expr};\n\\! touch /tmp/pwn\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    def test_number_really_does_open_a_dollar_quote(self, db_mod):
        """The mirror image: after a pure NUMBER, ``$tag$`` IS a delimiter.
        PostgreSQL 18 reports the error in ``SELECT 1$t$x$t$`` at the token
        ``$t$x$t$``, so a backslash inside that body is data, not a command."""
        sql = "SELECT 1$t$ a \\! b $t$;\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is None

    def test_missing_a_dollar_body_is_not_a_safe_fallback(self, db_mod):
        """Refusing to open a dollar body is NOT the conservative direction.

        The scanner then lexes the body's contents as SQL, and a lone quote in
        there (``it's``) opens a phantom string literal that swallows every later
        meta-command.  This input defeated an earlier fix whose identifier
        lookback was capped for performance — the cap was itself a bypass.
        """
        run = "1" + "0" * 300
        sql = f"SELECT {run}$$ it's $$\n\\! touch /tmp/pwn\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    def test_dollar_quote_after_a_token_boundary_still_opens(self, db_mod):
        """The fix must not blind the scanner to REAL dollar-quoted bodies: a
        backslash inside a function body is data and must stay unflagged."""
        sql = (
            "CREATE FUNCTION f() RETURNS text AS $_$ SELECT 'a; \\! b'; $_$ "
            "LANGUAGE sql;\n"
        )
        assert db_mod._find_disallowed_psql_meta_command(sql) is None

    def test_identifier_containing_dollar_is_not_flagged(self, db_mod):
        """A legitimate dump may contain ``$`` identifiers; they are ordinary
        SQL, so they must not be rejected either."""
        sql = "CREATE TABLE money$usd (x int);\nINSERT INTO money$usd VALUES (1);\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is None

    def test_copy_from_stdin_without_semicolon_does_not_enter_data_mode(self, db_mod):
        sql = "COPY nosuchtable FROM stdin\n\\! touch /tmp/pwn\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    def test_meta_command_between_copy_and_its_semicolon_is_flagged(self, db_mod):
        """The variant that restores CLEANLY (psql exit 0): the meta-command sits
        between ``COPY ... FROM stdin`` and the ``;`` that executes it."""
        sql = "COPY ok FROM stdin\n\\! touch /tmp/pwn\n;\n1\n\\.\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    def test_terminated_copy_still_treats_following_lines_as_data(self, db_mod):
        """The normal pg_dump shape must keep working: once the ``;`` executes
        the COPY, backslashes in the data block are data, not commands."""
        sql = "COPY t (a,b) FROM stdin;\n1\tdata\\x\\.more\n\\.\nSELECT 1;\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is None

    def test_semicolon_inside_copy_options_does_not_arm_data_mode_early(self, db_mod):
        """A ``;`` inside a string literal is not the statement terminator."""
        sql = "COPY t FROM stdin WITH (DELIMITER ';');\n1\n\\.\nSELECT 1;\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is None

    def test_copy_to_stdout_with_from_stdin_in_line_comment_is_not_data(self, db_mod):
        sql = "COPY (SELECT 1) TO STDOUT; -- FROM stdin\n\\! touch /tmp/pwn\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    def test_copy_to_stdout_with_from_stdin_in_block_comment_is_not_data(self, db_mod):
        sql = "COPY (SELECT 1) TO STDOUT /* FROM stdin */;\n\\! touch /tmp/pwn\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    def test_copy_to_stdout_with_from_stdin_in_string_literal_is_not_data(self, db_mod):
        sql = "COPY (SELECT 'FROM stdin') TO STDOUT;\n\\! touch /tmp/pwn\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    def test_from_stdin_after_the_terminating_semicolon_is_not_data(self, db_mod):
        """``FROM stdin`` belonging to a LATER (unterminated) statement must not
        retro-arm the COPY that already ended at its ``;``."""
        sql = "COPY (SELECT 1) TO STDOUT; SELECT 'x' FROM stdin\n\\! touch /tmp/pwn\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    def test_statement_not_starting_with_copy_never_enters_data_mode(self, db_mod):
        """Only a statement whose FIRST token is ``COPY`` can make the server
        answer PGRES_COPY_IN."""
        sql = "SELECT * FROM stdin;\n\\! touch /tmp/pwn\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    def test_quoted_copy_identifier_is_not_the_copy_command(self, db_mod):
        sql = '"COPY" t FROM stdin;\n\\! touch /tmp/pwn\n'
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    def test_copy_from_stdin_is_case_insensitive(self, db_mod):
        """The real pg_dump shape must be recognised whatever the casing."""
        sql = "copy T (a) FrOm StDiN;\n1\tdata\\x\n\\.\nSELECT 1;\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is None

    def test_copy_preceded_by_a_comment_on_the_same_line_still_enters_data_mode(
        self, db_mod
    ):
        """A comment contributes no token, so ``COPY`` is still the statement's
        first one — the data block's backslashes stay data."""
        sql = "/* c */ COPY t (a) FROM stdin;\n1\t\\N\n\\.\nSELECT 1;\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is None

    def test_copy_from_stdin_spanning_two_lines_still_enters_data_mode(self, db_mod):
        sql = "COPY t (a)\n  FROM stdin;\n1\t\\N\n\\.\nSELECT 1;\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is None

    def test_e_prefix_inside_an_identifier_is_not_an_escape_string(self, db_mod):
        """``fooE'x'`` is the identifier ``fooE`` plus a PLAIN literal, in which
        a backslash escapes nothing — so the literal ends at the next quote and
        what follows is live SQL."""
        sql = "SELECT fooE'x';\n\\! touch /tmp/pwn\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is not None

    def test_real_escape_string_still_swallows_its_backslashes(self, db_mod):
        sql = "SELECT E'a\\nb\\\\c';\nSELECT 1;\n"
        assert db_mod._find_disallowed_psql_meta_command(sql) is None

    def test_token_start_tracking_stays_linear(self, db_mod):
        """Deciding "identifier or delimiter?" must stay O(1) per character.

        ``dump.sql`` is attacker-supplied and unbounded, so a line of N identifier
        characters followed by N ``$`` must not cost O(N**2).

        The step size and the threshold have to be chosen together or the test
        cannot discriminate.  It previously DOUBLED the input and allowed an 8x
        time increase — but doubling the input of a quadratic scanner costs
        exactly 4x, which is under that ceiling in both branches of the old
        ``max(small * 8, 0.5)``.  Verified by injecting a genuinely O(N**2) loop
        into ``_find_disallowed_psql_meta_command``: the old assertion passed.

        QUADRUPLING instead separates the two hypotheses: linear predicts ~4x,
        quadratic ~16x, so the 8x ceiling sits a full 2x clear of each.  Timings
        are the MINIMUM of several runs — the robust statistic for wall-clock,
        since scheduler noise can only ever add time.

        That last argument is right per MEASUREMENT and insufficient for the
        RATIO, which divides two independently-noisy minima, so the errors
        compound in both directions.  Measured on a 22-core box under 2x CPU
        oversubscription with ``runs=3``: 15 samples spread 1.25-7.58 against
        the 8.0 ceiling, and a 40-run loop produced a real failure.  Raising
        ``runs`` to 9 under identical load pulled the spread to 2.91-4.91 - the
        margin the reasoning above assumes.  The whole test costs ~0.1 s, so the
        extra samples are free; do not lower this to "speed it up".
        """
        import time

        def timed(size, runs=9):
            sql = "SELECT " + ("a" * size) + ("$" * size) + ";\n\\! touch /tmp/x\n"
            best = float("inf")
            for _ in range(runs):
                t0 = time.perf_counter()
                assert db_mod._find_disallowed_psql_meta_command(sql) is not None
                best = min(best, time.perf_counter() - t0)
            return best

        timed(2000)  # warm the interpreter; discarded
        small, large = timed(10_000), timed(40_000)
        assert large < small * 8, (
            f"{small=:.6f} {large=:.6f} — 4x the input cost {large / small:.1f}x the "
            f"time; linear predicts ~4x, quadratic ~16x"
        )


class TestDumpSqlScannerStreaming:
    """The restore scanner must not hold the dump in memory: ``dump.sql`` is
    unbounded and attacker-supplied, and the worker running the restore is the
    one a memory soft limit watches."""

    def test_scanner_state_survives_line_boundaries(self, db_mod):
        """Every multi-line lexical context must carry across a ``feed`` call,
        else a ``\\!`` inside one would be read as a live meta-command (false
        positive) or one after it missed (false negative)."""
        cases = [
            ("/* multi\n line \\! comment */\nSELECT 1;\n", False),
            ("SELECT $$ body\nwith \\! inside\n$$;\n", False),
            ("SELECT 'multi\nline \\! literal';\n", False),
            ('CREATE TABLE "multi\nline \\! ident" ();\n', False),
            ("COPY t FROM stdin;\n\\! not-a-command\n\\.\nSELECT 1;\n", False),
            ("/* open\ncomment */\n\\! after\n", True),
            ("SELECT $$a\nb$$;\n\\i /etc/passwd\n", True),
            ("SELECT 'a\nb';\n\\connect evil\n", True),
        ]
        for sql, expect_hit in cases:
            got = db_mod._find_disallowed_psql_meta_command(sql)
            assert (got is not None) is expect_hit, (sql, got)

    def test_feeding_line_by_line_matches_whole_string(self, db_mod):
        sql = (
            "-- header\nCOPY t FROM stdin;\n1\tx\\y\n\\.\n"
            "CREATE FUNCTION f() AS $b$ SELECT '\\!'; $b$ LANGUAGE sql;\n"
            "SELECT 1;\n\\gexec\n"
        )
        whole = db_mod._find_disallowed_psql_meta_command(sql)
        scanner = db_mod._PsqlSqlScanner()
        streamed = None
        for line in db_mod._iter_physical_lines(sql):
            streamed = scanner.feed(line)
            if streamed is not None:
                break
        assert whole == streamed
        assert whole is not None and whole[1] == "\\gexec"

    def test_never_slurps_the_file(self, db_mod, tmp_path):
        """Pin the streaming contract: a whole-file ``read()`` regression would
        reintroduce ~2x-dump-size RSS on every restore (measured: a 142 MB
        ``dump.sql`` cost +271 MB slurped vs +0.5 MB streamed)."""
        p = tmp_path / "dump.sql"
        p.write_text("SELECT 1;\n" * 50_000, encoding="latin-1")
        real_open = type(p).open

        class NoSlurp:
            """File proxy that streams but refuses to be read in full.

            Also pins the stronger invariant the size cap depends on: every
            ``readline`` must carry an explicit limit.  An unbounded ``readline``
            is as unbounded as ``read`` when the dump has no newlines, which is
            exactly the case the cap exists for.
            """

            def __init__(self, fh):
                self._fh = fh

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self._fh.__exit__(*exc)

            def __iter__(self):
                return iter(self._fh)

            def readline(self, *a, **kw):
                limit = a[0] if a else kw.get("size")
                assert limit is not None and limit > 0, (
                    "_assert_dump_sql_safe must bound each readline, else a "
                    "newline-free dump is slurped one 'line' at a time"
                )
                return self._fh.readline(*a, **kw)

            def read(self, *a, **kw):
                raise AssertionError(
                    "_assert_dump_sql_safe must stream, not read() the dump"
                )

        def spy_open(self, *a, **kw):
            return NoSlurp(real_open(self, *a, **kw))

        with patch.object(type(p), "open", spy_open):
            db_mod._assert_dump_sql_safe(str(p))

    def test_peak_memory_is_independent_of_dump_size(self, db_mod, tmp_path):
        """Scanning a 4x-larger dump must not cost 4x the peak allocation."""
        import tracemalloc

        def peak_for(n_lines):
            p = tmp_path / f"dump_{n_lines}.sql"
            p.write_text("SELECT 1;\n" * n_lines, encoding="latin-1")
            tracemalloc.start()
            db_mod._assert_dump_sql_safe(str(p))
            _cur, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            return peak

        small, large = peak_for(25_000), peak_for(100_000)
        assert large < small * 2, (small, large)

    def test_iter_physical_lines_splits_only_on_newline(self, db_mod):
        """``str.splitlines`` also breaks on \\v/\\f/\\x85/\\u2028, which the
        scanner treats as ordinary characters — splitting there would desync
        its statement-start bookkeeping inside a literal."""
        text = "a\x0bb\x85c d\ne\n"
        assert list(db_mod._iter_physical_lines(text)) == ["a\x0bb\x85c d\n", "e\n"]


# ---------------------------------------------------------------------------
# The refusal message — the line number is the whole diagnosis
# ---------------------------------------------------------------------------


class TestTheReportedLineNumber:
    """A refusal names a line, and that number is all an operator gets.

    ``_assert_dump_sql_safe`` aborts the restore with ``(lineno, text)``; the
    archive itself is attacker-supplied and may be enormous, so a wrong line
    sends whoever is investigating to the wrong place in a file they cannot skim.

    Nothing asserted it.  A mutation sweep over the scanner found five survivors
    that are *only* line-number regressions — the attack is still refused, at the
    wrong line — and each went unnoticed by 938 tests including the generative
    fuzz, because the fuzz asserts the one-way property (psql executed => the
    scanner rejected) and a refusal at any line satisfies it.

    ``self.lineno`` is advanced by the main loop and by every ``_resume_*``
    helper, so the cases below step through each lexical context that can carry a
    newline before the offending command.
    """

    @staticmethod
    def _expected_line(sql):
        """Where ``\\!`` really is, counted independently of the scanner."""
        return sql[: sql.index("\\!")].count("\n") + 1

    @pytest.mark.parametrize(
        ("label", "sql"),
        [
            ("first line", "\\! id\n"),
            ("second line", "SELECT 1;\n\\! id\n"),
            ("after a line comment", "SELECT 1; -- c\n\\! id\n"),
            ("after a block comment", "SELECT 1; /* c */\n\\! id\n"),
            ("after a multi-line block comment", "/* a\n   b\n   c */\n\\! id\n"),
            ("after a string literal", "SELECT 'x';\n\\! id\n"),
            ("after a multi-line string literal", "SELECT 'a\nb\nc';\n\\! id\n"),
            ("after an escape string literal", "SELECT E'x';\n\\! id\n"),
            ("after a dollar body", "SELECT $$b$$;\n\\! id\n"),
            ("after a multi-line dollar body", "SELECT $$a\nb$$;\n\\! id\n"),
            ("after a tagged dollar body", "SELECT $t$a\nb$t$;\n\\! id\n"),
            ("after a quoted identifier", 'SELECT "col";\n\\! id\n'),
            # The delimiter must close AT END OF LINE for these to bind. Each
            # branch of the main loop ends in `continue`, and turning one into
            # `pass` falls through to `i += 1`, skipping the character the resume
            # helper stopped on. When that character is the newline, the line
            # counter never advances and the refusal names the line before.
            # A `;` between the delimiter and the newline absorbs the skip, which
            # is why the four cases above do not catch it.
            ("string literal closing at end of line", "SELECT 'x'\n\\! id\n"),
            ("dollar body closing at end of line", "SELECT $$b$$\n\\! id\n"),
            ("tagged dollar closing at end of line", "SELECT $t$b$t$\n\\! id\n"),
            ("quoted identifier closing at end of line", 'SELECT "c"\n\\! id\n'),
            ("block comment closing at end of line", "SELECT 1 /* c */\n\\! id\n"),
            ("after a COPY block", "COPY t FROM stdin;\n1\n2\n\\.\n\\! id\n"),
            ("deep in the file", "SELECT 1;\n" * 40 + "\\! id\n"),
        ],
    )
    def test_the_refusal_names_the_line_the_command_is_on(self, db_mod, label, sql):
        found = db_mod._find_disallowed_psql_meta_command(sql)
        assert found is not None, f"{label}: the command was not flagged at all"
        assert found[0] == self._expected_line(sql), (
            f"{label}: refused at line {found[0]}, but the command is on line "
            f"{self._expected_line(sql)}"
        )


class TestTheScannerAlwaysTerminates:
    """A lexer over attacker-supplied input must not be able to spin.

    The scan runs before a restore, on a file whose content the caller chose.  A
    main loop that fails to advance ``i`` does not fail the restore — it hangs
    the worker, and a mutation sweep found exactly that: one one-token change
    turned the bounded loop unbounded, and the suite "noticed" only by never
    finishing.

    Run on a worker thread with a deadline so a regression FAILS here in seconds
    rather than stalling the run.  ``pytest.ini``'s ``faulthandler_timeout``
    would eventually name it, but naming it after five minutes is not the same as
    failing.

    **What this does and does not buy.**  Measured over the seven scanner
    mutations that a sweep left alive, six now fail — including the one that used
    to hang the whole file, which this class turns into a 30-second failure.  The
    seventh (``if nl == -1`` in the meta-command branch) still hangs, because an
    EARLIER test in this file happens to feed it a looping input and reaches it
    first; a corpus here cannot help with that, and reordering the file to run
    this class first would only work until the next test was added above it (and
    not at all under a shuffled collection).  For that residue,
    ``faulthandler_timeout`` naming the test is the guarantee.
    """

    #: Shapes that stress the advance: unterminated everything, empty contexts,
    #: adjacent delimiters, and a backslash with nothing after it.
    PATHOLOGICAL = [
        "",
        "\\",
        "\\\n",
        "SELECT 'unterminated",
        "SELECT $$unterminated",
        "SELECT $tag$unterminated",
        "/* unterminated",
        'SELECT "unterminated',
        "SELECT E'unterminated",
        "COPY t FROM stdin;\n1\n",  # no terminating \.
        "--",
        "-" * 5000,
        "$" * 5000,
        "\\" * 5000,
        "'" * 5000,
        '"' * 5000,
        "$$" * 2500,
        "/*" * 2500,
        "\\restrict",
        "\\restrict abc123",  # opened, never closed
        # The ALLOWED meta-commands, alone and unpaired. These are the ones that
        # reach the "skip to end of line" path, so a regression there loops on
        # them and on nothing else: the corpus missed that until a mutation of
        # `if nl == -1` hung on a bare `\.` while every other input returned.
        "\\.",
        "\\.\n",
        "\\unrestrict abc123",
        "\\unrestrict abc123\n",
        "\\restrict abc123\n\\unrestrict abc123",
        "SELECT 1;" + "\n" * 5000,
    ]

    @staticmethod
    @pytest.fixture(scope="class")
    def scanned(db_mod):
        """Scan the corpus on a worker thread, with a deadline.

        Every assertion in this class reads from here rather than calling the
        scanner itself.  A test that scans on the MAIN thread defeats the point:
        it hangs the run instead of failing, which is exactly the outcome the
        class exists to convert into a failure.  (Verified — the first version of
        this class had a non-vacuity check that did that, and a mutation of the
        line-comment branch hung the whole file for 240s.)
        """
        import threading

        # A list of (input, verdict), not a dict: the corpus deliberately holds
        # near-duplicates and a dict would silently collapse them.
        results = []

        def run():
            results.extend(
                (sql, db_mod._find_disallowed_psql_meta_command(sql))
                for sql in TestTheScannerAlwaysTerminates.PATHOLOGICAL
            )

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout=30)
        return results if not worker.is_alive() else None

    def test_every_pathological_input_returns(self, scanned):
        assert scanned is not None, (
            "the scanner did not finish the pathological corpus within 30s — its "
            "main loop stopped advancing on some input, which on a real restore "
            "hangs the worker on attacker-supplied content"
        )
        assert len(scanned) == len(self.PATHOLOGICAL)

    def test_the_corpus_is_not_trivially_empty(self, scanned):
        """Non-vacuity: at least some of these must reach real lexing."""
        assert scanned is not None, "corpus did not finish; see the sibling test"
        assert [sql for sql, found in scanned if found is not None], (
            "no pathological input was flagged; the corpus is inert"
        )
