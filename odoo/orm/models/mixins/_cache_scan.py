import typing

if typing.TYPE_CHECKING:
    from ...fields.base import Field
    from ...runtime import Environment


def caches_lang_dicts(field: Field, env: Environment) -> bool:
    return callable(field.translate) and bool(env.context.get("prefetch_langs"))


def can_scan_identity(field: Field) -> bool:
    return field.cache_is_record_value and not callable(field.translate)


def can_scan_truthy(field: Field) -> bool:
    return field.cache_truthiness_matches and not callable(field.translate)


def can_scan_sorted(field: Field) -> bool:
    return field.cache_is_orderable and not callable(field.translate)


def can_scan_read(field: Field) -> bool:
    return field.store and field.cache_is_read_value and not callable(field.translate)
