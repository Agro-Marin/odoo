import typing
from operator import itemgetter

from odoo_rust import origin_ids as _origin_ids_rust

from odoo.libs.sql import SQL

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

    from .fields.base import Field
    from .models.base import BaseModel


def _origin_ids_python(ids: Iterable) -> list[int]:
    return [oid for id_ in ids if (oid := id_ or getattr(id_, "origin", None))]


def _origin_ids(ids: Iterable) -> list[int]:
    if isinstance(ids, tuple):
        return _origin_ids_rust(ids)
    return _origin_ids_python(ids)


def resolve_fnames(model: BaseModel, fnames: Iterable[str]) -> list[Field]:
    fields = []
    _fields = model._fields
    for fname in fnames:
        try:
            fields.append(_fields[fname])
        except KeyError:
            raise ValueError(
                f"Invalid field {fname!r} on model {model._name!r}"
            ) from None
    return fields


ORM_CLASS_MEMOS: tuple[str, ...] = (
    "_constraint_methods__",
    "_onchange_methods__",
    "_ondelete_methods__",
    "_precompute_readonly_names__",
    "_properties_field_names__",
    "_stored_computed_fields__",
)


def own_class_memo[T](cls: type, key: str, factory: typing.Callable[[], T]) -> T:
    value = cls.__dict__.get(key)
    if value is None:
        value = factory()
        setattr(cls, key, value)
    return value


def itemgetter_tuple(items: list | tuple) -> typing.Callable[[typing.Any], tuple]:
    if len(items) == 0:
        return lambda a: ()
    if len(items) == 1:
        return lambda gettable: (gettable[items[0]],)
    return itemgetter(*items)


def to_record_ids(arg) -> list[int]:
    from .models.base import BaseModel

    if isinstance(arg, BaseModel):
        return arg.ids
    elif isinstance(arg, bool):
        return []
    elif isinstance(arg, int):
        return [arg] if arg else []
    else:
        return [id_ for id_ in arg if id_]


def get_columns_from_sql_diagnostics(
    cr: typing.Any, diagnostics: typing.Any, *, check_registry: bool = False
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


def check_company_domain_parent_of(
    self: BaseModel,
    companies: BaseModel | list[int] | int | str,
) -> list:
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
