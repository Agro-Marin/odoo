import enum
import logging
import re
import typing
import warnings
from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING

import psycopg
from psycopg import sql as _sql

from odoo.libs.json import dumps as json_dumps

if TYPE_CHECKING:
    from odoo.db import Cursor
    from odoo.fields import Field
else:
    Field = typing.Any
    Cursor = typing.Any


from odoo.libs.sql import (
    escape_psql,
    make_identifier,
    make_index_name,
    pg_varchar,
    reverse_order,
)
from odoo.libs.utils import named_to_positional_printf

__all__ = [
    "SQL",
    "create_index",
    "drop_view_if_exists",
    "escape_psql",
    "index_exists",
    "make_identifier",
    "make_index_name",
    "pattern_to_translated_trigram_pattern",
    "pg_varchar",
    "reverse_order",
    "value_to_translated_trigram_pattern",
]

_schema = logging.getLogger("odoo.schema")

IDENT_RE = re.compile(r"^[a-z0-9_][a-z0-9_$\-]*\Z", re.IGNORECASE)

_PRINTF_DIRECTIVE_RE = re.compile(r"%(.)", re.DOTALL)

_WILDCARD_ESCAPE_RE = re.compile(r"(_|%|\\)")
_TRIGRAM_PATTERN_RE = re.compile(
    r"""
    (
        (?:.)*?           # 0 or more characters including newline
        (?<!\\)(?:\\\\)*  # 0 or even number of backslashes
    )
    (?:_|%|$)             # a non-escaped wildcard character or end of string
    """,
    re.VERBOSE | re.DOTALL,
)
_PG_UNESCAPE_RE = re.compile(r"\\(.|$)", re.DOTALL)

_CONFDELTYPES = {
    "RESTRICT": "r",
    "NO ACTION": "a",
    "CASCADE": "c",
    "SET NULL": "n",
    "SET DEFAULT": "d",
}


class SQL:
    """An object that wraps SQL code with its parameters, like::

        sql = SQL("UPDATE TABLE foo SET a = %s, b = %s", 'hello', 42)
        cr.execute(sql)

    The code is given as a ``%``-format string, and supports either positional
    arguments (with `%s`) or named arguments (with `%(name)s`). The arguments
    are meant to be merged into the code using the `%` formatting operator.
    The character ``%`` must always be escaped (as ``%%``), even if
    the code does not have parameters, like in ``SQL("foo LIKE 'a%%'")``.

    The SQL wrapper is designed to be composable: the arguments can be either
    actual parameters, or SQL objects themselves::

        sql = SQL(
            "UPDATE TABLE %s SET %s",
            SQL.identifier(tablename),
            SQL("%s = %s", SQL.identifier(columnname), value),
        )

    The combined SQL code is given by ``sql.code``, while the corresponding
    combined parameters are given by the tuple ``sql.params``. This allows to
    combine any number of SQL terms without having to separately combine their
    parameters, which can be tedious, bug-prone, and is the main downside of
    `psycopg.sql <https://www.psycopg.org/psycopg3/docs/basic/adapt.html>`.

    The second purpose of the wrapper is to discourage SQL injections.
    If ``code`` is a string literal (not a dynamic string), then the SQL object
    made with ``code`` is guaranteed to be safe, provided the SQL objects
    within its parameters are themselves safe.

    The wrapper may also contain some metadata ``to_flush``.  If not ``None``,
    its value is a field which the SQL code depends on.  The metadata of a
    wrapper and its parts can be accessed via the ``sql.to_flush`` property.
    """

    __slots__ = ("__code", "__params", "__to_flush")

    __code: str
    __params: tuple
    __to_flush: tuple[Field, ...]

    def __init__(
        self,
        code: str | SQL = "",
        /,
        *args: object,
        to_flush: Field | Iterable[Field] | None = None,
        **kwargs: object,
    ) -> None:
        if isinstance(code, SQL):
            if args or kwargs or to_flush:
                msg = "SQL() unexpected arguments when code has type SQL"
                raise TypeError(msg)
            self.__code = code.__code
            self.__params = code.__params
            self.__to_flush = code.__to_flush
            return

        if args and kwargs:
            msg = "SQL() takes either positional arguments, or named arguments"
            raise TypeError(msg)

        if kwargs:
            code, args = named_to_positional_printf(code, kwargs)
        elif not args:
            code % ()
            self.__code = code
            self.__params = ()
            if to_flush is None:
                self.__to_flush = ()
            elif hasattr(to_flush, "__iter__"):
                self.__to_flush = tuple(to_flush)
            else:
                self.__to_flush = (to_flush,)
            return

        code_list = []
        params_list = []
        to_flush_list = []
        for arg in args:
            if isinstance(arg, SQL):
                code_list.append(arg.__code)
                params_list.extend(arg.__params)
                to_flush_list.extend(arg.__to_flush)
            elif isinstance(arg, tuple):
                if arg:
                    element_codes = []
                    for element in arg:
                        if isinstance(element, SQL):
                            element_codes.append(element.__code)
                            params_list.extend(element.__params)
                            to_flush_list.extend(element.__to_flush)
                        else:
                            element_codes.append("%s")
                            params_list.append(element)
                    code_list.append("(%s)" % ", ".join(element_codes))
                else:
                    code_list.append("(NULL)")
            else:
                code_list.append("%s")
                params_list.append(arg)
        if to_flush is not None:
            if hasattr(to_flush, "__iter__"):
                to_flush_list.extend(to_flush)
            else:
                to_flush_list.append(to_flush)

        self.__code = code.replace("%%", "%%%%") % tuple(code_list)
        self.__params = tuple(params_list)
        self.__to_flush = tuple(to_flush_list)

    @property
    def code(self) -> str:
        """Return the combined SQL code string."""
        return self.__code

    @property
    def params(self) -> tuple:
        """Return the combined SQL code params as a tuple of values."""
        return self.__params

    @property
    def to_flush(self) -> Iterable[Field]:
        """Return the fields to flush from ``self`` and all of its parts."""
        return self.__to_flush

    def render(self) -> str:
        """Render to a fully-formatted SQL string with parameters inlined.

        Uses psycopg's adapter system for safe value quoting.  Useful for
        embedding a parameterized SQL fragment into a larger raw SQL string
        (e.g. inside an f-string that will later be passed to ``cr.execute()``
        with its own separate parameters).

        The result is a ``%``-format template like :attr:`code`, not a finished
        query: every literal ``%`` stays escaped as ``%%``, so the output can be
        fed back to ``SQL(...)`` or spliced into a larger template.  That is what
        both in-tree callers do (``project`` burndown/CFD reports:
        ``SQL(fragment.render().replace(...))``).

        Escaping the parameter-less case only -- as this used to -- made the two
        branches disagree: ``SQL("x LIKE 'a%%'")`` rendered ``x LIKE 'a%%'``
        while ``SQL("x LIKE 'a%%' AND y = %s", 1)`` rendered ``x LIKE 'a%'``,
        which then blew up as ``TypeError: not enough arguments for format
        string`` when re-wrapped in ``SQL()``.  Inlined parameter *values* that
        contain ``%`` (e.g. an ILIKE pattern) need the same escaping, hence the
        blanket re-escape after substitution.
        """
        if not self.__params:
            return self.__code
        inlined = self.__code % tuple(str(_sql.quote(v)) for v in self.__params)
        return inlined.replace("%", "%%")

    def inlined(self, cr: Cursor) -> SQL:
        """Return an equivalent ``SQL`` with the bound parameters embedded as
        SQL literals, preserving the wrapper's metadata (``to_flush``).

        read_group grouping keys need this: PostgreSQL matches SELECT /
        GROUP BY / ORDER BY expressions by byte-identical text, but under
        psycopg3's server-side binding each ``%s`` renders as a distinct
        ``$N``, so a param-bearing expression (a translated field's language
        code, a company-dependent field's fallback) would make GROUP BY differ
        from SELECT and be rejected.  Unlike :meth:`render` (which returns a
        plain string), the result stays a composable, executable ``SQL``: the
        substitution is placeholder-aware, so pre-escaped ``%%`` in the code
        survives unchanged (a raw ``code % params`` would collapse it) and
        ``%`` characters inside the quoted literals are re-escaped.

        :param cr: cursor whose connection provides the adaptation context for
            quoting the literals (injection-safe for arbitrary values).
        """
        if not self.__params:
            return self
        params = iter(self.__params)

        def substitute(match: re.Match) -> str:
            directive = match[1]
            if directive == "%":
                return "%%"
            if directive == "s":
                literal = _sql.Literal(next(params)).as_string(cr._cnx)
                return literal.replace("%", "%%")
            raise ValueError(
                f"SQL.inlined(): unsupported format directive "
                f"%{directive} in {self.__code!r}"
            )

        code = _PRINTF_DIRECTIVE_RE.sub(substitute, self.__code)
        return SQL(code, to_flush=self.__to_flush)

    def __repr__(self) -> str:
        return f"SQL({', '.join(map(repr, [self.__code, *self.__params]))})"

    def __bool__(self) -> bool:
        return bool(self.__code)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, SQL)
            and self.__code == other.__code
            and self.__params == other.__params
        )

    def __hash__(self) -> int:
        return hash((self.__code, self.__params))

    def __iter__(self):
        """Yield ``self.code`` and ``self.params``, for backward-compatible
        deconstruction of the object::

            sql = SQL(...)
            code, params = sql
        """
        warnings.warn(
            "Deprecated since 19.0, use code and params properties directly",
            DeprecationWarning,
            stacklevel=2,
        )
        yield self.code
        yield self.params

    def join(self, args: Iterable) -> SQL:
        """Join SQL objects or parameters with ``self`` as a separator."""
        items = args if isinstance(args, list) else list(args)
        if len(items) == 0:
            return SQL.EMPTY
        if len(items) == 1 and isinstance(items[0], SQL):
            return items[0]
        if not self.__params:
            return SQL(self.__code.join("%s" for _ in items), *items)
        result = [self] * (len(items) * 2 - 1)
        for index, arg in enumerate(items):
            result[index * 2] = arg
        return SQL("%s" * len(result), *result)

    EMPTY: SQL

    @classmethod
    def identifier(
        cls,
        name: str,
        subname: str | None = None,
        to_flush: Field | None = None,
    ) -> SQL:
        """Return an SQL object that represents an identifier.

        The validation below is a SQL-injection barrier: an identifier is
        interpolated into the query verbatim (only double-quote-wrapped), so it
        must be a real identifier.  This MUST be a ``raise``, not an ``assert`` —
        asserts are stripped under ``python -O`` (a common production setting),
        which would let a crafted name break out of the quoting.
        """
        if not (name.isidentifier() or IDENT_RE.match(name)):
            raise ValueError(f"{name!r} invalid for SQL.identifier()")
        if subname is None:
            return cls(f'"{name}"', to_flush=to_flush)
        if not (subname.isidentifier() or IDENT_RE.match(subname)):
            raise ValueError(f"{subname!r} invalid for SQL.identifier()")
        return cls(f'"{name}"."{subname}"', to_flush=to_flush)

    @classmethod
    def literal(cls, value: str) -> SQL:
        """Return an SQL object holding *value* as a quoted string literal.

        The counterpart of :meth:`identifier` for the rare expression that must
        carry its string **in the query text** rather than as a parameter:
        PostgreSQL matches a ``GROUP BY`` expression against the ``SELECT`` list
        by text, and a bound parameter gets a distinct ``$N`` in each position,
        so ``date_trunc(%s, col)`` appearing in both fails GROUP BY validation.

        Callers pass allow-listed values (a granularity, a timezone name); the
        validation below is the SQL-injection barrier for the case where one day
        they do not, and it MUST be a ``raise`` rather than an ``assert`` for the
        same reason as :meth:`identifier` -- asserts vanish under ``python -O``.

        This replaces splicing the quoted text into an ``SQL()`` *format* string
        (``SQL("date_trunc(%s, %%s)" % quoted, expr)``), where the doubled ``%``
        is invisible to a reader, a value containing ``%`` silently becomes a
        format directive, and the escaping lives at each call site instead of
        one place.

        ``%`` is rejected along with the quote and the backslash: the result is
        an :class:`SQL` *code* fragment, and code is printf-substituted when it
        is composed into a larger query, so a stray ``%`` would be read as a
        format directive (or raise on the ``code % ()`` validation here).

        :raises TypeError: when *value* is not a :class:`str`
        :raises ValueError: when *value* contains ``'``, ``\\`` or ``%``
        """
        if not isinstance(value, str):
            raise TypeError(
                f"SQL.literal() expected str, got {type(value).__name__}: {value!r}"
            )
        if "'" in value or "\\" in value or "%" in value:
            raise ValueError(f"{value!r} invalid for SQL.literal()")
        return cls(f"'{value}'")

    @classmethod
    def in_(cls, lhs: SQL, values: Iterable) -> SQL:
        """Return ``lhs = ANY(values)`` — a membership test that is correct for
        the empty set.

        Prefer this over ``SQL("... IN %s", tuple(values))``. The bare ``IN %s``
        form relies on this class expanding a tuple into ``(%s, %s, ...)`` and,
        for an empty tuple, into ``IN (NULL)`` — correct for ``IN`` (matches
        nothing) but a trap the moment it is negated (see :meth:`not_in`), and a
        crash if a tuple is passed where an array is expected. This helper binds
        the values as a single ``ANY`` array parameter (the psycopg3-native
        idiom, already used across the codebase) and renders an empty set as a
        constant ``FALSE`` (matches nothing), sidestepping both hazards.

        :param lhs: the left-hand SQL expression (e.g. ``SQL.identifier("col")``).
        :param values: any collection of values to test membership against.
        """
        values = list(values)
        if not values:
            return cls("FALSE")
        return cls("%s = ANY(%s)", lhs, values)

    @classmethod
    def not_in(cls, lhs: SQL, values: Iterable) -> SQL:
        """Return ``lhs <> ALL(values)`` — a negated membership test that is
        correct for the empty set.

        This is the case the tuple-expansion path gets silently wrong: an empty
        ``NOT IN`` must match **every** row, but ``x NOT IN (NULL)`` (what an
        empty tuple expands to) matches **nothing**. Here an empty set renders as
        a constant ``TRUE`` (matches everything). For a non-empty set,
        ``<> ALL(array)`` reproduces ``NOT IN``'s SQL semantics exactly,
        including its NULL handling (a NULL ``lhs``, or a NULL in ``values``,
        yields NULL — the row is excluded — just like ``NOT IN``).

        :param lhs: the left-hand SQL expression (e.g. ``SQL.identifier("col")``).
        :param values: any collection of values to exclude.
        """
        values = list(values)
        if not values:
            return cls("TRUE")
        return cls("%s <> ALL(%s)", lhs, values)


SQL.EMPTY = SQL()


def existing_tables(cr: Cursor, tablenames: Iterable[str]) -> list[str]:
    """Return the names of existing tables among ``tablenames``."""
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
            ["r", "v", "m"],
        )
    )
    return [row[0] for row in cr.fetchall()]


def table_exists(cr: Cursor, tablename: str) -> bool:
    """Return whether the given table exists."""
    return len(existing_tables(cr, {tablename})) == 1


class TableKind(enum.Enum):
    Regular = "r"
    Temporary = "t"
    View = "v"
    Materialized = "m"
    Foreign = "f"
    Other = None


def table_kind(cr: Cursor, tablename: str) -> TableKind | None:
    """Return the kind of a table, if ``tablename`` is a regular or foreign
    table, or a view (ignores indexes, sequences, toast tables, and partitioned
    tables; unlogged tables are considered regular)
    """
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
    if not cr.rowcount:
        return None

    kind, persistence = cr.fetchone()
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
    cr: Cursor, tablename: str, comment: str | None = None, columns: tuple = ()
) -> None:
    """Create the table for a model."""
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
    """Return a dict mapping column names to their configuration.

    Each value is a dict with keys ``column_name``, ``udt_name``,
    ``character_maximum_length``, and ``is_nullable`` (matching the legacy
    ``information_schema.columns`` contract).  Uses ``pg_catalog`` directly
    for better performance.
    """
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
    """Return whether the given column exists."""
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
    """Create a column with the given type."""
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
    """Convert the column to the given type."""
    using = SQL("%s::%s", SQL.identifier(columnname), SQL(columntype))
    _convert_column(cr, tablename, columnname, columntype, using)


def convert_column_translatable(
    cr: Cursor, tablename: str, columnname: str, columntype: str
) -> None:
    """Convert the column from/to a 'jsonb' translated field column."""
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
    """Drop views depending on a field so the ORM can resize it in-place."""
    for v, k in get_depending_views(cr, table, column):
        quoted = '"%s"' % v.replace('"', '""')
        cr.execute(
            SQL(
                "DROP %s IF EXISTS %s CASCADE",
                SQL("MATERIALIZED VIEW" if k == "m" else "VIEW"),
                SQL(quoted),
            )
        )
        _schema.debug("Drop view %r", v)


def get_depending_views(cr: Cursor, table: str, column: str) -> list[tuple[str, str]]:
    """Return ``(view_name, relkind)`` for every view depending on a column.

    ``relname`` is returned **raw**, not through ``quote_ident``.  The single
    consumer, :func:`drop_depending_views`, passes it to ``SQL.identifier``,
    which does its own quoting -- so pre-quoting produced a name that already
    carried literal double quotes and was then rejected outright::

        ValueError: '"MixedCaseView"' invalid for SQL.identifier()

    That only stayed hidden because ``quote_ident`` is a no-op for the ordinary
    lowercase names the ORM generates; any view needing quotes (mixed case, a
    reserved word, a space) turned a column-type migration into a hard failure
    inside :func:`_convert_column`'s fallback path.
    """
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
    """Add a NOT NULL constraint on the given column."""
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
    """Drop the NOT NULL constraint on the given column."""
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
    """Set a SQL DEFAULT on the given column.

    This ensures the database fills in a default value even when the ORM
    omits the column from INSERT (e.g. when the module that added the
    field is not loaded but the NOT NULL constraint remains).
    """
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
    """Return the given constraint's definition."""
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
    return cr.fetchone()[0] if cr.rowcount else None


def add_constraint(
    cr: Cursor, tablename: str, constraintname: str, definition: str
) -> None:
    """Add a constraint on the given table."""
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
    """Drop the given constraint."""
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
    """Create the given foreign key."""
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
    """Return all FK constraints on (tablename, columnname).

    Each result is a tuple (conname, target_table, target_column, confdeltype).
    """
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
    """Return all FK constraints on the given tables in a single query.

    Each result is a tuple
    (conname, source_table, source_column, target_table, target_column, confdeltype).
    """
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


def fix_foreign_key(
    cr: Cursor,
    tablename1: str,
    columnname1: str,
    tablename2: str,
    columnname2: str,
    ondelete: str,
) -> bool:
    """Update the foreign keys between tables to match the given one, and
    return ``True`` if the given foreign key has been recreated.
    """
    deltype = _CONFDELTYPES.get(ondelete.upper(), "a")
    found = False
    for conname, target_table, target_col, del_type in _get_fk_constraints(
        cr, tablename1, columnname1
    ):
        if not found and (target_table, target_col, del_type) == (
            tablename2,
            columnname2,
            deltype,
        ):
            found = True
        else:
            drop_constraint(cr, tablename1, conname)
    if found:
        return False
    add_foreign_key(cr, tablename1, columnname1, tablename2, columnname2, ondelete)
    return True


def index_exists(cr: Cursor, indexname: str) -> bool:
    """Return whether the given index exists **in the current schema**.

    The schema predicate is not incidental: ``pg_indexes`` spans every schema in
    the database, so without it an unrelated index of the same name in another
    schema reported a false positive here -- and :func:`create_index` returns
    early on a true, so the index the caller asked for was silently never
    created in the schema that needed it.  Every other catalogue lookup in this
    module is already scoped this way; this one was the outlier.

    ``relkind`` matches ``'i'`` *and* ``'I'`` to keep the previous result set
    intact: ``pg_indexes`` is itself defined as ``i.relkind = ANY('i','I')``, so
    dropping the partitioned-index kind would have turned this fix into a
    regression -- an existing partitioned index would report missing and
    :func:`create_index` would try to recreate it.
    """
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
    """Read the index definition from the database.

    Scoped and kind-matched exactly like :func:`index_exists`, which the callers
    pair this with.  Two mismatches used to make the pair disagree:

    * ``pg_indexes`` spans every schema, and the join was on bare
      ``c.relname = idx.indexname``.  A same-named index in another schema
      produced a second row, so ``fetchone()`` could hand back a *different*
      index's definition -- which the schema layer then compares against the
      expected one and "repairs".  Joining on ``idx.schemaname`` too keeps the
      row set to this schema.
    * ``relkind = 'i'`` dropped partitioned indexes (``'I'``), so an existing
      partitioned index reported present via :func:`index_exists` but definition
      ``None`` here.
    """
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
    return cr.fetchone() if cr.rowcount else (None, None)


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
    """Create the given index unless it already exists.

    :param expressions: the indexed expressions/columns
    :param method: the index type (default: btree)
    :param where: WHERE clause for a partial index (default: none)
    :param comment: comment to set on the index
    :param unique: whether the index is unique (default: False)
    """
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
    comment: str = "",
) -> None:
    """Create an index."""
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
    """Drop the given index if it exists."""
    cr.execute(SQL("DROP INDEX IF EXISTS %s", SQL.identifier(indexname)))
    _schema.debug("Table %r: dropped index %r", tablename, indexname)


def drop_view_if_exists(cr: Cursor, viewname: str) -> None:
    kind = table_kind(cr, viewname)
    if kind == TableKind.View:
        cr.execute(SQL("DROP VIEW %s CASCADE", SQL.identifier(viewname)))
    elif kind == TableKind.Materialized:
        cr.execute(SQL("DROP MATERIALIZED VIEW %s CASCADE", SQL.identifier(viewname)))


def increment_fields_skiplock(records: object, *fields: str) -> bool:
    """Increment the given integer ``fields`` on ``records``, skipping locked rows.

    Does not invalidate the cache, since the update is not critical.

    :param records: recordset to update
    :param fields: integer fields to increment
    :returns: whether the fields were incremented on any record.
    :rtype: bool
    """
    if not records:
        return False

    for field in fields:
        if records._fields[field].type != "integer":
            raise ValueError(
                f"increment_fields_skiplock: field {field!r} is not an integer"
            )

    cr = records.env.cr
    tablename = records._table
    cr.execute(
        SQL(
            """
        UPDATE %s
           SET %s
         WHERE id IN (SELECT id FROM %s WHERE id = ANY(%s) FOR UPDATE SKIP LOCKED)
        """,
            SQL.identifier(tablename),
            SQL(", ").join(
                SQL(
                    "%s = COALESCE(%s, 0) + 1",
                    SQL.identifier(field),
                    SQL.identifier(field),
                )
                for field in fields
            ),
            SQL.identifier(tablename),
            records.ids,
        )
    )
    return bool(cr.rowcount)


def value_to_translated_trigram_pattern(value: str) -> str:
    """Escape value to match a translated field's trigram index content

    The trigram index function jsonb_path_query_array("column_name", '$.*')::text
    uses all translations' representations to build the indexed text. So the
    original text needs to be JSON-escaped correctly to match it.

    :param str value: value provided in domain
    :return: a pattern to match the indexed text
    """
    if len(value) < 3:
        return "%"

    json_escaped = json_dumps(value, ensure_ascii=False)[1:-1]

    wildcard_escaped = _WILDCARD_ESCAPE_RE.sub(r"\\\1", json_escaped)

    return f"%{wildcard_escaped}%"


def pattern_to_translated_trigram_pattern(pattern: str) -> str:
    """Escape pattern to match a translated field's trigram index content

    The trigram index function jsonb_path_query_array("column_name", '$.*')::text
    uses all translations' representations to build the indexed text. So the
    original pattern needs to be JSON-escaped correctly to match it.

    :param str pattern: value provided in domain
    :return: a pattern to match the indexed text
    """
    sub_patterns = _TRIGRAM_PATTERN_RE.findall(pattern)

    sub_texts = [_PG_UNESCAPE_RE.sub(r"\1", t) for t in sub_patterns]

    json_escaped = [
        json_dumps(t, ensure_ascii=False)[1:-1] for t in sub_texts if len(t) >= 3
    ]

    wildcard_escaped = [_WILDCARD_ESCAPE_RE.sub(r"\\\1", t) for t in json_escaped]

    return f"%{'%'.join(wildcard_escaped)}%" if wildcard_escaped else "%"
