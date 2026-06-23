"""Shared ORM helper functions.

Multi-consumer utilities used across several ORM modules. Kept at the orm/
level to avoid circular imports between the models and fields layers.
"""

import typing
from operator import itemgetter

from odoo.tools import SQL

if typing.TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Reversible

    from .models.base import BaseModel


# ID utilities


def _origin_ids_python(ids: Iterable) -> list[int]:
    """Extract origin IDs from an iterable of record IDs (pure Python).

    Keeps each truthy ``int`` id as-is, else its truthy ``id_.origin``; ids
    that are falsy with no origin are skipped. Per :class:`NewId`'s contract
    ``origin`` is always ``int`` or ``None``, so the result is ``list[int]``;
    a non-``int`` origin is misuse and is not filtered here.
    """
    return [oid for id_ in ids if (oid := id_ or getattr(id_, "origin", None))]


try:
    from odoo_rust import origin_ids as _origin_ids_rust  # type: ignore[import-untyped]

    def _origin_ids(ids: Iterable) -> list[int]:
        """Extract origin IDs — Rust fast path for tuples, Python fallback."""
        if isinstance(ids, tuple):
            return _origin_ids_rust(ids)
        return _origin_ids_python(ids)

except ImportError:
    _origin_ids = _origin_ids_python


class OriginIds:
    """Reversible iterable of the origin ids of a collection of ``ids``.

    Actual ids pass through; ids without origin are dropped. For eager
    consumption prefer ``_origin_ids(ids)`` (uses Rust when available,
    ~3x faster for int-only tuples).
    """

    __slots__ = ["ids"]

    def __init__(self, ids: Reversible) -> None:
        self.ids = ids

    def __iter__(self) -> Iterator[int]:
        return iter(_origin_ids(self.ids))

    def __reversed__(self) -> Iterator[int]:
        for id_ in reversed(self.ids):
            if id_ := id_ or getattr(id_, "origin", None):
                yield id_


# Record utilities


def itemgetter_tuple(items: list | tuple) -> typing.Callable[[typing.Any], tuple]:
    """Build an itemgetter that always returns an n-tuple (n = len(items)).

    Unlike :func:`operator.itemgetter`, returns a 1-tuple (not a bare value)
    when ``len(items) == 1``.
    """
    if len(items) == 0:
        return lambda a: ()
    if len(items) == 1:
        return lambda gettable: (gettable[items[0]],)
    return itemgetter(*items)


def to_record_ids(arg) -> list[int]:
    """Return the non-zero record ids of ``arg``.

    ``arg`` may be a recordset, an integer, or an iterable of integers.
    """
    # imported here to avoid circular dep
    from .models.base import BaseModel

    if isinstance(arg, BaseModel):
        return arg.ids
    elif isinstance(arg, bool):
        # bool is a subclass of int; a bare bool carries no record id, and
        # returning ``[True]`` would violate the ``list[int]`` contract.
        return []
    elif isinstance(arg, int):
        return [arg] if arg else []
    else:
        return [id_ for id_ in arg if id_]


def get_columns_from_sql_diagnostics(
    cr: typing.Any, diagnostics: typing.Any, *, check_registry: bool = False
) -> list[str]:
    """Return the column names affected by a failed constraint, for better
    error messages.

    :param diagnostics: PostgreSQL error diagnostics, with ``column_name``,
        ``constraint_name``, ``table_name`` attributes.
    :param check_registry: when ``column_name`` is absent, query
        ``pg_constraint`` to find the columns.
    :return: affected column names, or ``[]`` if undeterminable.
    """
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


# Company domain helpers


def check_company_domain_parent_of(
    self: BaseModel,
    companies: BaseModel | list[int] | int | str,
) -> list:
    """A ``_check_company_domain`` function for single company_id fields.

    Allows a record when ``company_id`` is False (shared) or a parent of any
    of the given companies. ``companies`` is a recordset, list of IDs, single
    ID, or field reference string. Returns a domain list.
    """
    if isinstance(companies, str):
        return [
            "|",
            ("company_id", "=", False),
            ("company_id", "parent_of", companies),
        ]

    companies = to_record_ids(companies)
    if not companies:
        return [("company_id", "=", False)]

    return [
        (
            "company_id",
            "in",
            [
                int(parent)
                for rec in self.env["res.company"].sudo().browse(companies)
                for parent in rec.parent_path.split("/")[:-1]
            ]
            + [False],
        )
    ]


def check_companies_domain_parent_of(
    self: BaseModel,
    companies: BaseModel | list[int] | int | str,
) -> list:
    """A ``_check_company_domain`` function for multi-company company_ids fields.

    Allows a record when any company in ``company_ids`` is a parent of any of
    the given companies. ``companies`` is a recordset, list of IDs, single ID,
    or field reference string. Returns a domain list.
    """
    if isinstance(companies, str):
        return [("company_ids", "parent_of", companies)]

    companies = to_record_ids(companies)
    if not companies:
        return []

    return [
        (
            "company_ids",
            "in",
            [
                int(parent)
                for rec in self.env["res.company"].sudo().browse(companies)
                for parent in rec.parent_path.split("/")[:-1]
            ],
        )
    ]
