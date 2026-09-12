"""Service guards must preserve PostgreSQL's real transaction state."""

import pytest

from odoo.service.db._dump_scanner import _get_disallowed_psql_meta_command

from .conftest import requires_pg


@requires_pg
@pytest.mark.parametrize("value", ["off", "false", "0", "'off'", "'false'", "'0'"])
def test_scanner_refuses_multiline_settings_that_change_postgresql_lexing(
    scratch_cursor, value
):
    sql = (
        f'SET LOCAL "standard_conforming_strings" /* lexical boundary */\n TO {value};'
    )
    assert _get_disallowed_psql_meta_command(sql) is not None
    scratch_cursor.execute(sql)
    scratch_cursor.execute("SHOW standard_conforming_strings")
    assert scratch_cursor.fetchone() == ("off",)
