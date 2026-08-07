import typing

if typing.TYPE_CHECKING:
    from ...fields.base import Field
    from ...runtime import Environment

_IDENTITY_TYPES = frozenset(
    {
        "boolean",
        "date",
        "datetime",
        "selection",
        "integer",
        "float",
        "monetary",
    }
)
_CHAR_TEXT_TYPES = frozenset({"char", "text"})

_TRUTHY_TYPES = frozenset(
    {
        "boolean",
        "integer",
        "float",
        "monetary",
        "char",
        "text",
        "html",
        "date",
        "datetime",
        "selection",
        "binary",
        "json",
        "properties",
        "properties_definition",
        "reference",
        "many2one_reference",
    }
)

_SORTABLE_TYPES = frozenset(
    {
        "char",
        "text",
        "integer",
        "float",
        "monetary",
        "date",
        "datetime",
        "selection",
    }
)

_READ_TYPES = frozenset(
    {
        "boolean",
        "selection",
        "date",
        "datetime",
        "char",
        "text",
        "integer",
        "float",
        "monetary",
    }
)


def caches_lang_dicts(field: Field, env: Environment) -> bool:
    return callable(field.translate) and bool(env.context.get("prefetch_langs"))


def can_scan_identity(field: Field) -> bool:
    return field.type in _IDENTITY_TYPES or (
        field.type in _CHAR_TEXT_TYPES and not callable(field.translate)
    )


def can_scan_truthy(field: Field) -> bool:
    return field.type in _TRUTHY_TYPES and not callable(field.translate)


def can_scan_sorted(field: Field) -> bool:
    return field.type in _SORTABLE_TYPES and not callable(field.translate)


def can_scan_read(field: Field) -> bool:
    return (
        field.store
        and not field.relational
        and not callable(field.translate)
        and field.type in _READ_TYPES
    )
