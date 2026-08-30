import typing

if typing.TYPE_CHECKING:
    from ...fields.base import Field
    from ...runtime import Environment


def is_cache_detached(field: Field, env: Environment, captured) -> bool:
    """Whether `captured` is no longer the live cache dict for `field`.

    The scan fast paths below bind a field's cache dict once and then call
    `field.__get__` for the misses, which runs arbitrary user code.
    `FieldCache.invalidate_all` *deletes* `_data[field]` rather than clearing it
    in place, so a getter that reaches `env.invalidate_all()` leaves the bound
    dict orphaned -- still holding every pre-invalidation value. Reading on from
    it returns stale values with no error: `mapped`, `grouped`, `sorted` and
    `filtered` each did, and `filtered` silently dropped records whose
    truthiness had flipped.

    `Field._get_cache` is memoised per environment and the memo is dropped by
    the same detach hook, so this is a dict lookup and an identity test. The
    callers use it to fall back to the descriptor, which re-resolves the cache
    per record and is what upstream does unconditionally.
    """
    return field._get_cache(env) is not captured


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
