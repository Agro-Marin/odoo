import typing
from functools import partial

from psycopg import sql as psycopg_sql

from odoo.db import FunctionStatus, has_trigram, has_unaccent
from odoo.tools import SQL

from ._registry_stubs import _RegistryStubs

if typing.TYPE_CHECKING:
    from odoo.db import BaseCursor


def _unaccent(
    x: SQL | str | psycopg_sql.Composable,
) -> SQL | str | psycopg_sql.Composed:
    if isinstance(x, SQL):
        return SQL("unaccent(%s)", x)
    if isinstance(x, psycopg_sql.Composable):
        return psycopg_sql.SQL("unaccent({})").format(x)
    return f"unaccent({x})"


_UNACCENT_PROBE_RANGES = ((0x80, 0x3000), (0xFB00, 0xFB50), (0xFF00, 0xFF70))


class _UnaccentTables:
    by_db: dict[str, dict[int, str]] = {}


def _get_unaccent_table(cr: BaseCursor, db_name: str) -> dict[int, str]:
    table = _UnaccentTables.by_db.get(db_name)
    if table is None:
        chars = [chr(c) for lo, hi in _UNACCENT_PROBE_RANGES for c in range(lo, hi)]
        cr.execute(
            "SELECT c AS source, unaccent(c) AS folded FROM unnest(%s::text[]) AS c",
            (chars,),
        )
        table = {
            ord(row["source"]): row["folded"]
            for row in cr.dictfetchall()
            if row["folded"] != row["source"]
        }
        _UnaccentTables.by_db[db_name] = table
    return table


def forget_unaccent_table(db_name: str) -> None:
    _UnaccentTables.by_db.pop(db_name, None)


def forget_all_unaccent_tables() -> None:
    _UnaccentTables.by_db.clear()


def _identity(x: typing.Any) -> typing.Any:
    return x


def _unaccent_python(x: str, table: dict[int, str]) -> str:
    return x.translate(table)


class _RegistryCapabilitiesMixin(_RegistryStubs):
    __slots__ = ()

    has_unaccent: FunctionStatus

    has_trigram: bool
    unaccent: typing.Callable[..., SQL | str | psycopg_sql.Composed]

    unaccent_python: typing.Callable[[str], str]

    def _probe_capabilities(self, cr: BaseCursor, db_name: str) -> None:
        self.has_unaccent = has_unaccent(cr)
        self.has_trigram = has_trigram(cr)
        table = _get_unaccent_table(cr, db_name) if self.has_unaccent else None

        self.unaccent = _unaccent if self.has_unaccent else _identity
        self.unaccent_python = (
            partial(_unaccent_python, table=table) if table is not None else _identity
        )
