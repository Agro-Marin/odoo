import pytest

from odoo.service._dump_scanner import _find_disallowed_psql_meta_command

from .conftest import requires_pg, requires_psql

ATTACKS = {
    "plain-bang": "\\! touch {C}\n",
    "bang-after-semicolon": "SELECT 1; \\! touch {C}\n",
    "restrict-blockcomment-desync": ("\\restrict /*\n\\unrestrict /*\n\\! touch {C}\n"),
    "restrict-dollarquote-desync": ("\\restrict $$\n\\unrestrict $$\n\\! touch {C}\n"),
    "restrict-backtick": "\\restrict `touch {C}`\n",
    "unrestrict-backtick": "\\unrestrict `touch {C}`\n",
    "restrict-then-bang": "\\restrict k1 \\! touch {C}\n",
}

BENIGN = {
    "inside-string": "SELECT '\\! touch {C}';\n",
    "inside-dollar-body": "SELECT $$\\! touch {C}$$;\n",
    "inside-line-comment": "-- \\! touch {C}\nSELECT 1;\n",
    "inside-block-comment": "/* \\! touch {C} */\nSELECT 1;\n",
    "in-copy-data": (
        "CREATE TEMP TABLE ct (a text);\nCOPY ct (a) FROM stdin;\n\\! touch {C}\n\\.\n"
    ),
}

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
