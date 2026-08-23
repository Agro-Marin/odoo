from __future__ import annotations

import enum
import logging
import typing
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

import psycopg

from odoo.libs.sql import SQL, make_index_name

if TYPE_CHECKING:
    from odoo.db import Cursor
else:
    Cursor = typing.Any

_schema = logging.getLogger("odoo.schema")

_CONFDELTYPES = {
    "RESTRICT": "r",
    "NO ACTION": "a",
    "CASCADE": "c",
    "SET NULL": "n",
    "SET DEFAULT": "d",
}


def existing_tables(cr: Cursor, tablenames: Iterable[str]) -> list[str]:
    cr.execute(
        SQL(
            """
        SELECT c.relname
          FROM pg_class c
         WHERE c.relname = ANY(%s)
           AND c.relkind = ANY(%s)
           AND c.relnamespace = current_schema::regnamespace
    """,
            list(tablenames),
            ["r", "v", "m", "p", "f"],
        )
    )
    return [row[0] for row in cr.fetchall()]


def table_exists(cr: Cursor, tablename: str) -> bool:
    return len(existing_tables(cr, {tablename})) == 1


class TableKind(enum.Enum):
    Regular = "r"
    Temporary = "t"
    View = "v"
    Materialized = "m"
    Foreign = "f"
    Partitioned = "p"
    Other = None


def table_kind(cr: Cursor, tablename: str) -> TableKind | None:
    cr.execute(
        SQL(
            """
        SELECT c.relkind, c.relpersistence
          FROM pg_class c
         WHERE c.relname = %s
           AND c.relnamespace = current_schema::regnamespace
    """,
            tablename,
        )
    )
    row = cr.fetchone()
    if row is None:
        return None

    kind, persistence = row
    if kind == "r":
        return TableKind.Temporary if persistence == "t" else TableKind.Regular

    try:
        return TableKind(kind)
    except ValueError:
        return TableKind.Other


SQL_ORDER_BY_TYPE = defaultdict(
    lambda: 16,
    {
        "int4": 1,
        "varchar": 2,
        "date": 3,
        "jsonb": 4,
        "text": 5,
        "numeric": 6,
        "bool": 7,
        "timestamp": 8,
        "float8": 9,
    },
)


def create_model_table(
    cr: Cursor, tablename: str, comment: str | None = None, columns: Sequence = ()
) -> None:
    colspecs = [
        SQL("id SERIAL NOT NULL"),
        *(
            SQL("%s %s", SQL.identifier(colname), SQL(coltype))
            for colname, coltype, _ in columns
        ),
        SQL("PRIMARY KEY(id)"),
    ]
    queries = [
        SQL(
            "CREATE TABLE %s (%s)",
            SQL.identifier(tablename),
            SQL(", ").join(colspecs),
        ),
    ]
    if comment:
        queries.append(
            SQL(
                "COMMENT ON TABLE %s IS %s",
                SQL.identifier(tablename),
                comment,
            )
        )
    for colname, _, colcomment in columns:
        queries.append(
            SQL(
                "COMMENT ON COLUMN %s IS %s",
                SQL.identifier(tablename, colname),
                colcomment,
            )
        )
    cr.execute(SQL("; ").join(queries))

    _schema.debug("Table %r: created", tablename)


def table_columns(cr: Cursor, tablename: str) -> dict[str, dict]:
    cr.execute(
        SQL(
            """
            SELECT a.attname AS column_name,
                   t.typname AS udt_name,
                   CASE WHEN a.atttypmod > 0 AND t.typname IN ('varchar', 'bpchar')
                        THEN a.atttypmod - 4
                        ELSE NULL
                   END AS character_maximum_length,
                   CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END AS is_nullable
              FROM pg_attribute a
              JOIN pg_class c ON a.attrelid = c.oid
              JOIN pg_type t ON a.atttypid = t.oid
             WHERE c.relname = %s
               AND c.relnamespace = current_schema::regnamespace
               AND a.attnum > 0
               AND NOT a.attisdropped
            """,
            tablename,
        )
    )
    return {row["column_name"]: row for row in cr.dictfetchall()}


def column_exists(cr: Cursor, tablename: str, columnname: str) -> bool:
    cr.execute(
        SQL(
            """
            SELECT 1
              FROM pg_attribute a
              JOIN pg_class c ON a.attrelid = c.oid
             WHERE c.relname = %s
               AND a.attname = %s
               AND c.relnamespace = current_schema::regnamespace
               AND a.attnum > 0
               AND NOT a.attisdropped
            """,
            tablename,
            columnname,
        )
    )
    return bool(cr.rowcount)


def create_column(
    cr: Cursor,
    tablename: str,
    columnname: str,
    columntype: str,
    comment: str | None = None,
) -> None:
    sql = SQL(
        "ALTER TABLE %s ADD COLUMN %s %s %s",
        SQL.identifier(tablename),
        SQL.identifier(columnname),
        SQL(columntype),
        SQL("DEFAULT false" if columntype.upper() == "BOOLEAN" else ""),
    )
    if comment:
        sql = SQL(
            "%s; %s",
            sql,
            SQL(
                "COMMENT ON COLUMN %s IS %s",
                SQL.identifier(tablename, columnname),
                comment,
            ),
        )
    cr.execute(sql)
    _schema.debug(
        "Table %r: added column %r of type %s",
        tablename,
        columnname,
        columntype,
    )


def convert_column(
    cr: Cursor, tablename: str, columnname: str, columntype: str
) -> None:
    using = SQL("%s::%s", SQL.identifier(columnname), SQL(columntype))
    _convert_column(cr, tablename, columnname, columntype, using)


def convert_column_translatable(
    cr: Cursor, tablename: str, columnname: str, columntype: str
) -> None:
    drop_index(cr, make_index_name(tablename, columnname), tablename)
    if columntype == "jsonb":
        using = SQL(
            "CASE WHEN %s IS NOT NULL THEN jsonb_build_object('en_US', %s::varchar) END",
            SQL.identifier(columnname),
            SQL.identifier(columnname),
        )
    else:
        using = SQL("%s->>'en_US'", SQL.identifier(columnname))
    _convert_column(cr, tablename, columnname, columntype, using)


def _convert_column(
    cr: Cursor, tablename: str, columnname: str, columntype: str, using: SQL
) -> None:
    query = SQL(
        "ALTER TABLE %s ALTER COLUMN %s DROP DEFAULT, ALTER COLUMN %s TYPE %s USING %s",
        SQL.identifier(tablename),
        SQL.identifier(columnname),
        SQL.identifier(columnname),
        SQL(columntype),
        using,
    )
    try:
        with cr.savepoint(flush=False):
            cr.execute(query, log_exceptions=False)
    except psycopg.NotSupportedError:
        drop_depending_views(cr, tablename, columnname)
        cr.execute(query)
    _schema.debug(
        "Table %r: column %r changed to type %s",
        tablename,
        columnname,
        columntype,
    )


def drop_depending_views(cr: Cursor, table: str, column: str) -> None:
    for v, k in get_depending_views(cr, table, column):
        cr.execute(
            SQL(
                "DROP %s IF EXISTS %s CASCADE",
                SQL("MATERIALIZED VIEW" if k == "m" else "VIEW"),
                SQL.identifier(v),
            )
        )
        _schema.debug("Drop view %r", v)


def get_depending_views(cr: Cursor, table: str, column: str) -> list[tuple[str, str]]:
    cr.execute(
        SQL(
            """
        SELECT distinct dependee.relname, dependee.relkind
        FROM pg_depend
        JOIN pg_rewrite ON pg_depend.objid = pg_rewrite.oid
        JOIN pg_class as dependee ON pg_rewrite.ev_class = dependee.oid
        JOIN pg_class as dependent ON pg_depend.refobjid = dependent.oid
        JOIN pg_attribute ON pg_depend.refobjid = pg_attribute.attrelid
            AND pg_depend.refobjsubid = pg_attribute.attnum
        WHERE dependent.relname = %s
        AND pg_attribute.attnum > 0
        AND pg_attribute.attname = %s
        AND dependee.relkind in ('v', 'm')
        AND dependee.relnamespace = current_schema::regnamespace
    """,
            table,
            column,
        )
    )
    return cr.fetchall()


def set_not_null(cr: Cursor, tablename: str, columnname: str) -> None:
    query = SQL(
        "ALTER TABLE %s ALTER COLUMN %s SET NOT NULL",
        SQL.identifier(tablename),
        SQL.identifier(columnname),
    )
    cr.execute(query, log_exceptions=False)
    _schema.debug(
        "Table %r: column %r: added constraint NOT NULL", tablename, columnname
    )


def drop_not_null(cr: Cursor, tablename: str, columnname: str) -> None:
    cr.execute(
        SQL(
            "ALTER TABLE %s ALTER COLUMN %s DROP NOT NULL",
            SQL.identifier(tablename),
            SQL.identifier(columnname),
        )
    )
    _schema.debug(
        "Table %r: column %r: dropped constraint NOT NULL",
        tablename,
        columnname,
    )


def set_default(cr: Cursor, tablename: str, columnname: str, value: object) -> None:
    cr.execute(
        SQL(
            "ALTER TABLE %s ALTER COLUMN %s SET DEFAULT %s",
            SQL.identifier(tablename),
            SQL.identifier(columnname),
            value,
        )
    )
    _schema.debug(
        "Table %r: column %r: set default to %r", tablename, columnname, value
    )


def constraint_definition(
    cr: Cursor, tablename: str, constraintname: str
) -> str | None:
    cr.execute(
        SQL(
            """
        SELECT COALESCE(d.description, pg_get_constraintdef(c.oid))
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        LEFT JOIN pg_description d ON c.oid = d.objoid
        WHERE t.relname = %s AND conname = %s
          AND t.relnamespace = current_schema::regnamespace
    """,
            tablename,
            constraintname,
        )
    )
    row = cr.fetchone()
    return row[0] if row else None


def add_constraint(
    cr: Cursor, tablename: str, constraintname: str, definition: str
) -> None:
    query1 = SQL(
        "ALTER TABLE %s ADD CONSTRAINT %s %s",
        SQL.identifier(tablename),
        SQL.identifier(constraintname),
        SQL(definition.replace("%", "%%")),
    )
    query2 = SQL(
        "COMMENT ON CONSTRAINT %s ON %s IS %s",
        SQL.identifier(constraintname),
        SQL.identifier(tablename),
        definition,
    )
    cr.execute(query1, log_exceptions=False)
    cr.execute(query2, log_exceptions=False)
    _schema.debug(
        "Table %r: added constraint %r as %s",
        tablename,
        constraintname,
        definition,
    )


def drop_constraint(cr: Cursor, tablename: str, constraintname: str) -> None:
    cr.execute(
        SQL(
            "ALTER TABLE %s DROP CONSTRAINT %s",
            SQL.identifier(tablename),
            SQL.identifier(constraintname),
        )
    )
    _schema.debug("Table %r: dropped constraint %r", tablename, constraintname)


def add_foreign_key(
    cr: Cursor,
    tablename1: str,
    columnname1: str,
    tablename2: str,
    columnname2: str,
    ondelete: str,
) -> None:
    if ondelete.upper() not in _CONFDELTYPES:
        raise ValueError(
            f"Invalid ON DELETE policy {ondelete!r} for "
            f"{tablename1}.{columnname1}; expected one of "
            f"{sorted(_CONFDELTYPES)}"
        )
    cr.execute(
        SQL(
            "ALTER TABLE %s ADD FOREIGN KEY (%s) REFERENCES %s(%s) ON DELETE %s",
            SQL.identifier(tablename1),
            SQL.identifier(columnname1),
            SQL.identifier(tablename2),
            SQL.identifier(columnname2),
            SQL(ondelete),
        )
    )
    _schema.debug(
        "Table %r: added foreign key %r references %r(%r) ON DELETE %s",
        tablename1,
        columnname1,
        tablename2,
        columnname2,
        ondelete,
    )


_FK_BASE_QUERY = """
    FROM pg_constraint AS fk
    JOIN pg_class AS c1 ON fk.conrelid = c1.oid
    JOIN pg_class AS c2 ON fk.confrelid = c2.oid
    JOIN pg_attribute AS a1 ON a1.attrelid = c1.oid AND fk.conkey[1] = a1.attnum
    JOIN pg_attribute AS a2 ON a2.attrelid = c2.oid AND fk.confkey[1] = a2.attnum
   WHERE fk.contype = 'f'
     AND c1.relnamespace = current_schema::regnamespace
"""


def _get_fk_constraints(
    cr: Cursor, tablename: str, columnname: str
) -> list[tuple[str, str, str, str]]:
    cr.execute(
        SQL(
            "SELECT fk.conname, c2.relname, a2.attname, fk.confdeltype"
            + _FK_BASE_QUERY
            + "AND c1.relname = %s AND a1.attname = %s",
            tablename,
            columnname,
        )
    )
    return cr.fetchall()


def get_fk_constraints_batch(
    cr: Cursor, tablenames: Iterable[str]
) -> list[tuple[str, str, str, str, str, str]]:
    cr.execute(
        SQL(
            "SELECT fk.conname, c1.relname, a1.attname, c2.relname, a2.attname, fk.confdeltype"
            + _FK_BASE_QUERY
            + "AND c1.relname = ANY(%s)",
            list(tablenames),
        )
    )
    return cr.fetchall()


def get_foreign_keys(
    cr: Cursor,
    tablename1: str,
    columnname1: str,
    tablename2: str,
    columnname2: str,
    ondelete: str,
) -> list[str]:
    deltype = _CONFDELTYPES.get(ondelete.upper(), "a")
    return [
        row[0]
        for row in _get_fk_constraints(cr, tablename1, columnname1)
        if row[1:] == (tablename2, columnname2, deltype)
    ]


def index_exists(cr: Cursor, indexname: str) -> bool:
    cr.execute(
        SQL(
            """
            SELECT 1
              FROM pg_class c
             WHERE c.relname = %s
               AND c.relkind IN ('i', 'I')
               AND c.relnamespace = current_schema::regnamespace
            """,
            indexname,
        )
    )
    return bool(cr.rowcount)


def index_definition(cr: Cursor, indexname: str) -> tuple[str | None, str | None]:
    cr.execute(
        SQL(
            """
        SELECT idx.indexdef, d.description
        FROM pg_class c
        JOIN pg_indexes idx ON c.relname = idx.indexname
            AND idx.schemaname = current_schema
        LEFT JOIN pg_description d ON c.oid = d.objoid
        WHERE c.relname = %s AND c.relkind IN ('i', 'I')
          AND c.relnamespace = current_schema::regnamespace
    """,
            indexname,
        )
    )
    row = cr.fetchone()
    return (row[0], row[1]) if row else (None, None)


def create_index(
    cr: Cursor,
    indexname: str,
    tablename: str,
    expressions: list[str],
    method: str = "btree",
    where: str = "",
    *,
    comment: str | None = None,
    unique: bool = False,
) -> None:
    if not expressions:
        raise ValueError("Missing expressions")
    if index_exists(cr, indexname):
        return
    definition = SQL(
        "USING %s (%s)%s",
        SQL(method),
        SQL(", ").join(
            SQL(expression.replace("%", "%%")) for expression in expressions
        ),
        (SQL(" WHERE %s", SQL(where.replace("%", "%%"))) if where else SQL()),
    )
    add_index(cr, indexname, tablename, definition, unique=unique, comment=comment)


def add_index(
    cr: Cursor,
    indexname: str,
    tablename: str,
    definition: str | SQL,
    *,
    unique: bool,
    comment: str | None = None,
) -> None:
    if isinstance(definition, str):
        definition = SQL(definition.replace("%", "%%"))
    else:
        definition = SQL(definition)
    query = SQL(
        "CREATE %sINDEX %s ON %s %s",
        SQL("UNIQUE ") if unique else SQL(),
        SQL.identifier(indexname),
        SQL.identifier(tablename),
        definition,
    )
    query_comment = (
        SQL(
            "COMMENT ON INDEX %s IS %s",
            SQL.identifier(indexname),
            comment,
        )
        if comment
        else None
    )
    cr.execute(query, log_exceptions=False)
    if query_comment:
        cr.execute(query_comment, log_exceptions=False)
    _schema.debug(
        "Table %r: created index %r (%s)", tablename, indexname, definition.code
    )


def drop_index(cr: Cursor, indexname: str, tablename: str) -> None:
    cr.execute(SQL("DROP INDEX IF EXISTS %s", SQL.identifier(indexname)))
    _schema.debug("Table %r: dropped index %r", tablename, indexname)


def drop_view_if_exists(cr: Cursor, viewname: str) -> None:
    kind = table_kind(cr, viewname)
    if kind == TableKind.View:
        cr.execute(SQL("DROP VIEW %s CASCADE", SQL.identifier(viewname)))
    elif kind == TableKind.Materialized:
        cr.execute(SQL("DROP MATERIALIZED VIEW %s CASCADE", SQL.identifier(viewname)))


def constraint_columns(
    cr: Cursor, diagnostics: psycopg.errors.Diagnostic, *, check_registry: bool = False
) -> list[str]:
    if column := diagnostics.column_name:
        return [column]
    if not check_registry:
        return []
    cr.execute(
        SQL(
            """
        SELECT
            ARRAY(
                SELECT attname FROM pg_attribute
                WHERE attrelid = conrelid
                AND attnum = ANY(conkey)
            ) as "columns"
        FROM pg_constraint
        JOIN pg_class t ON t.oid = conrelid
        WHERE conname = %s
            AND t.relname = %s
            AND t.relnamespace = current_schema::regnamespace
    """,
            diagnostics.constraint_name,
            diagnostics.table_name,
        )
    )
    columns = cr.fetchone()
    return columns[0] if columns else []
