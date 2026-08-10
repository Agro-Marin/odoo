import typing
from functools import partial

from psycopg import sql as psycopg_sql

from odoo.tools import SQL

from ._registry_stubs import _RegistryStubs

if typing.TYPE_CHECKING:
    from odoo.db import BaseCursor
    from odoo.modules.db import FunctionStatus


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
    """Tri-state, NOT a bool: ``MISSING`` / ``PRESENT`` / ``INDEXABLE``.

    ``_registry_schema.check_indexes`` branches on all three -- only
    ``INDEXABLE`` (``unaccent`` declared ``IMMUTABLE``) may be used inside a
    trigram index expression, while ``PRESENT`` merely warns.  Declared ``bool``
    until 19.0-marin, which made that comparison statically unsatisfiable (a
    ``bool`` is 0 or 1, ``INDEXABLE`` is 2) and reported it as
    ``comparison-overlap``; the branch it called dead is the one that runs on
    every database built from a template carrying an immutable ``unaccent``.
    ``has_trigram`` really is a bool -- the asymmetry is why the wrong
    declaration read as plausible.
    """

    has_trigram: bool
    unaccent: typing.Callable[..., SQL | str | psycopg_sql.Composed]
    """SQL-level folding: wraps an expression in ``unaccent(...)``, or returns
    it unchanged when the extension is absent."""

    unaccent_python: typing.Callable[[str], str]
    """The same fold in Python, for comparing values the database is not being
    asked about. Built from a probed translation table rather than a call, so it
    costs no query per use."""

    def _probe_capabilities(self, cr: BaseCursor, db_name: str) -> None:
        from odoo.modules import db as modules_db

        self.has_unaccent = modules_db.has_unaccent(cr)
        self.has_trigram = modules_db.has_trigram(cr)
        table = _get_unaccent_table(cr, db_name) if self.has_unaccent else None

        self.unaccent = _unaccent if self.has_unaccent else _identity
        self.unaccent_python = (
            partial(_unaccent_python, table=table) if table is not None else _identity
        )
