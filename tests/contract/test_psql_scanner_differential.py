"""The restore scanner versus the ``psql`` that will actually read the dump.

``_dump_scanner`` is a re-implementation of psql's lexer, written to decide one
thing: would ``psql -f`` EXECUTE a backslash command in this file?  Any place
the two lexers disagree is a bypass, and no amount of testing the scanner
against itself can find one — the audit that added this suite found three
disagreements that every existing unit test was blind to, because the unit tests
encoded the same wrong model of psql that the scanner did.

So this compares the scanner to the real program.  The property is one-way:

    the canary fired  =>  the scanner rejected

The converse is deliberately NOT asserted.  The scanner may refuse things psql
would have ignored (it refuses an over-long SQL line, for instance); a refused
restore is a safe outcome, a silent execution is not.

A separate liveness check guards the other direction at the level that matters:
the shapes a real ``pg_dump`` produces must still be ACCEPTED, or the fix for
the RCE would simply have broken every backup.
"""

import pytest

from odoo.service._dump_scanner import _find_disallowed_psql_meta_command

from .conftest import requires_pg, requires_psql

# Each entry: (name, sql template with {C} for the canary shell command).
# Payloads that psql executes are the interesting ones; the rest guard against
# the scanner becoming trigger-happy on ordinary dump content.
ATTACKS = {
    # Baseline: the thing the whole module exists to stop.
    "plain-bang": "\\! touch {C}\n",
    "bang-after-semicolon": "SELECT 1; \\! touch {C}\n",
    # An ALLOWED verb whose ARGUMENT opens a lexical context.  psql takes "/*"
    # as the restrict key and is back in ordinary SQL on line 3, while a scanner
    # that lexes argument text as SQL sits inside a nested block comment for the
    # rest of the file -- and psql exits 0, so the restore reports SUCCESS.
    "restrict-blockcomment-desync": ("\\restrict /*\n\\unrestrict /*\n\\! touch {C}\n"),
    "restrict-dollarquote-desync": ("\\restrict $$\n\\unrestrict $$\n\\! touch {C}\n"),
    # psql expands a backticked argument by running it in a SHELL, and does so
    # BEFORE validating the argument -- so the command runs even though the
    # \restrict then fails and the restore aborts.
    "restrict-backtick": "\\restrict `touch {C}`\n",
    "unrestrict-backtick": "\\unrestrict `touch {C}`\n",
    # A second meta-command on the same line as an allowed one: psql ends
    # argument text at an unquoted backslash and starts a new command there.
    "restrict-then-bang": "\\restrict k1 \\! touch {C}\n",
}

# Content psql treats as data or text.  The scanner must not execute-flag these,
# and psql must not run them either -- if a canary fires here the payload is
# wrong, not the scanner.
BENIGN = {
    "inside-string": "SELECT '\\! touch {C}';\n",
    "inside-dollar-body": "SELECT $$\\! touch {C}$$;\n",
    "inside-line-comment": "-- \\! touch {C}\nSELECT 1;\n",
    "inside-block-comment": "/* \\! touch {C} */\nSELECT 1;\n",
    "in-copy-data": (
        "CREATE TEMP TABLE ct (a text);\nCOPY ct (a) FROM stdin;\n\\! touch {C}\n\\.\n"
    ),
}

# The shapes a real pg_dump emits.  These must be ACCEPTED: a scanner that
# rejects them has broken every backup, which is worse than the bug it fixes.
LEGIT = {
    "restrict-pair": "\\restrict abc123\nSELECT 1;\n\\unrestrict abc123\n",
    "copy-block-with-null-marker": (
        "CREATE TEMP TABLE ct (a text);\n"
        "COPY ct (a) FROM stdin;\n\\N\nplain\n\\.\nSELECT 1;\n"
    ),
}


def _write(tmp_path, name, template, canary):
    path = tmp_path / f"{name}.sql"
    path.write_text(template.format(C=canary), encoding="latin-1")
    return path


@requires_pg
@requires_psql
class TestScannerAgreesWithPsql:
    @pytest.mark.parametrize("name", sorted(ATTACKS))
    def test_anything_psql_executes_is_rejected(self, name, tmp_path, run_psql):
        canary = tmp_path / f"canary_{name}"
        path = _write(tmp_path, name, ATTACKS[name], canary)
        rejected = _find_disallowed_psql_meta_command(path.read_text("latin-1"))
        run_psql(path)
        if canary.exists():
            assert rejected is not None, (
                f"BYPASS: psql executed the payload {name!r} and the scanner "
                f"reported the file as safe. A restore of this archive would "
                f"run arbitrary shell commands as the Odoo service account."
            )

    def test_the_canary_mechanism_is_live(self, tmp_path, run_psql):
        """Guard against the whole class above passing vacuously.

        Every assertion there is conditional on the canary firing, so if the
        mechanism silently stopped working -- psql not reached, \\! disabled,
        the path unwritable -- the suite would report green while comparing
        nothing.  Pin that at least the baseline attack really does execute.
        """
        canary = tmp_path / "canary_live"
        path = _write(tmp_path, "live", ATTACKS["plain-bang"], canary)
        run_psql(path)
        assert canary.exists(), (
            "psql did not execute \\!, so the differential above proves nothing "
            "(check psql flags, permissions, or a restricted build)"
        )

    @pytest.mark.parametrize("name", sorted(BENIGN))
    def test_data_and_text_are_not_executed_by_either(self, name, tmp_path, run_psql):
        canary = tmp_path / f"canary_{name}"
        path = _write(tmp_path, name, BENIGN[name], canary)
        rejected = _find_disallowed_psql_meta_command(path.read_text("latin-1"))
        run_psql(path)
        assert not canary.exists(), f"payload {name!r} is not benign after all"
        assert rejected is None, (
            f"{name!r} is content psql treats as data/text, but the scanner "
            f"flags it -- a legitimate dump containing this would be refused"
        )

    @pytest.mark.parametrize("name", sorted(LEGIT))
    def test_real_dump_shapes_are_accepted_and_replay_cleanly(
        self, name, tmp_path, run_psql
    ):
        path = _write(tmp_path, name, LEGIT[name], tmp_path / "unused")
        assert _find_disallowed_psql_meta_command(path.read_text("latin-1")) is None, (
            f"the scanner refuses {name!r}, a shape real pg_dump output carries"
        )
        result = run_psql(path)
        assert result.returncode == 0, (
            f"{name!r} does not replay cleanly, so it is not a valid model of "
            f"real dump content: {result.stderr.strip()[:200]}"
        )
