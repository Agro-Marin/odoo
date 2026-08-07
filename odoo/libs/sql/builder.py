"""The ``SQL`` composable query wrapper.

A code+params object that composes safely and discourages injection (a string
literal ``code`` is guaranteed safe). Framework-free: relocated here from
``odoo/tools/sql.py`` under ADR-0004 because it imports no ``odoo`` framework
code at runtime -- only ``odoo.libs`` -- and is general-purpose SQL composition.
"""

from __future__ import annotations

import re
import typing
import warnings
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

from psycopg import sql as _sql

from odoo.libs.utils import named_to_positional_printf

if TYPE_CHECKING:
    from odoo.db import Cursor
    from odoo.fields import Field
else:
    Field = typing.Any
    Cursor = typing.Any

IDENT_RE = re.compile(r"^[a-z0-9_][a-z0-9_$\-]*\Z", re.IGNORECASE)

_PRINTF_DIRECTIVE_RE = re.compile(r"%(.)", re.DOTALL)


class SQL:
    """A wrapper pairing SQL code with its parameters.

    For example::

        sql = SQL("UPDATE TABLE foo SET a = %s, b = %s", "hello", 42)
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
        """Build an SQL wrapper from ``code`` and its positional/named params."""
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

        code_list: list[str] = []
        params_list: list = []
        to_flush_list: list = []
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
        """The combined SQL code string."""
        return self.__code

    @property
    def params(self) -> tuple:
        """The combined SQL parameters, as a tuple of values."""
        return self.__params

    @property
    def to_flush(self) -> Iterable[Field]:
        """The fields to flush from ``self`` and all of its parts."""
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
        """Return an equivalent ``SQL`` with parameters embedded as SQL literals.

        Preserves the wrapper's metadata (``to_flush``).

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
        """Return ``SQL(code, *params)``, reconstructing the constructor call."""
        return f"SQL({', '.join(map(repr, [self.__code, *self.__params]))})"

    def __bool__(self) -> bool:
        """Return whether this wraps non-empty SQL code."""
        return bool(self.__code)

    def __eq__(self, other: object) -> bool:
        """Two ``SQL`` objects are equal iff their code and params match."""
        return (
            isinstance(other, SQL)
            and self.__code == other.__code
            and self.__params == other.__params
        )

    def __hash__(self) -> int:
        """Hash on the (code, params) pair, consistent with :meth:`__eq__`."""
        return hash((self.__code, self.__params))

    def __iter__(self) -> Iterator:
        """Yield ``code`` then ``params``, for backward-compatible unpacking.

        Deconstruct the object as ``code, params = sql``.
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
        r"""Return an SQL object holding *value* as a quoted string literal.

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
        """Return ``lhs = ANY(values)``, a membership test correct for the empty set.

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
        """Return ``lhs <> ALL(values)``, a negated membership test for the empty set.

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
