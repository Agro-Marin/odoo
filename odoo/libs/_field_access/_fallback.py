"""Pure Python fallback for field cache access functions.

Used when the Rust extension (odoo_rust) is not installed.
These implementations are semantically identical to the Rust versions
but slower due to Python loop and function call overhead.
"""

from operator import itemgetter as _itemgetter

_itemgetter_1 = _itemgetter(1)


def batch_cache_get(
    field_cache: dict,
    ids: tuple,
    pending: object,
    none_val: object,
) -> tuple[list, list[int]]:
    """Batch cache lookup for mapped()/grouped() identity-type fast paths.

    Returns (results, miss_indices) where:
    - results[i] = cached value (or none_val if cache value is None)
    - miss_indices = positions where cache was empty or value was PENDING
    """
    results = []
    miss_indices = []
    _get = field_cache.get
    _MISSING = object()
    _append_result = results.append
    _append_miss = miss_indices.append

    for i, id_ in enumerate(ids):
        value = _get(id_, _MISSING)
        if value is _MISSING or value is pending:
            _append_result(none_val)
            _append_miss(i)
        elif value is None:
            _append_result(none_val)
        else:
            _append_result(value)

    return results, miss_indices


def batch_cache_filter(
    field_cache: dict,
    ids: tuple,
    pending: object,
) -> tuple[list, list[int]]:
    """Batch cache truthiness filter for filtered() field-name fast path.

    Returns (passing_ids, miss_indices) where:
    - passing_ids = list of record IDs where cached value is truthy
    - miss_indices = positions where cache miss or PENDING
    """
    passing_ids = []
    miss_indices = []
    _get = field_cache.get
    _MISSING = object()
    _append_pass = passing_ids.append
    _append_miss = miss_indices.append

    for i, id_ in enumerate(ids):
        value = _get(id_, _MISSING)
        if value is _MISSING or value is pending:
            _append_miss(i)
        elif value:
            _append_pass(id_)
        # falsy: neither pass nor miss

    return passing_ids, miss_indices


def batch_cache_values(
    field_cache: dict,
    ids: tuple,
    pending: object,
) -> list | None:
    """All-or-nothing batch cache extraction for sorted() fast path.

    Returns a list of all cached values, or None if any id is missing
    or has a PENDING value.  Early bailout on first miss.
    """
    values = []
    _get = field_cache.get
    _MISSING = object()
    _append = values.append

    for id_ in ids:
        value = _get(id_, _MISSING)
        if value is _MISSING or value is pending:
            return None
        _append(value)

    return values


def batch_cache_fill(
    field_cache: dict,
    ids: tuple,
    results: list,
    name: str,
    pending: object,
    none_val: object,
) -> list[int]:
    """Fill a scalar field value into existing result dicts from the field cache.

    For each index i in 0..len(ids):
    - If results[i] is empty (cleared = missing record): skip.
    - Cache hit (not pending, not None): results[i][name] = value
    - Cache hit is None: results[i][name] = none_val
    - Cache miss or pending: record index i for fallback

    Returns list[int] of miss indices needing Field.__get__ fallback.
    """
    miss_indices = []
    _MISSING = object()
    _get = field_cache.get

    for i, vals in enumerate(results):
        if not vals:
            continue
        value = _get(ids[i], _MISSING)
        if value is _MISSING or value is pending:
            miss_indices.append(i)
        elif value is None:
            vals[name] = none_val
        else:
            vals[name] = value

    return miss_indices


def sort_ids_by_values(
    ids: tuple,
    values: list,
    reverse: bool,
    null_high: bool | None = None,
) -> tuple:
    """Sort record IDs by corresponding cached values.

    Replaces `list(zip(ids, values)) + sort(key=itemgetter(1)) + tuple(...)`
    in `_sorted_by_ids`.  When `null_high` is provided, None/False values are
    treated as nulls and sorted before (False) or after (True) non-nulls.

    :param ids: tuple of record IDs
    :param values: list of cached values, same length as ids
    :param reverse: sort descending if True
    :param null_high: None = no null handling; True = nulls last in ASC;
                      False = nulls first in ASC
    :return: new tuple of IDs in sorted order
    """
    if null_high is None:
        pairs = list(zip(ids, values, strict=False))
        pairs.sort(key=_itemgetter_1, reverse=reverse)
        return tuple(p[0] for p in pairs)
    # null-aware path: wrap values in (rank, val) for sort stability
    _null_rank = 1 if null_high else 0
    _val_rank = 0 if null_high else 1
    _null_key = (_null_rank, "")
    keys = [_null_key if (v is None or v is False) else (_val_rank, v) for v in values]
    pairs = list(zip(ids, keys, strict=False))
    pairs.sort(key=_itemgetter_1, reverse=reverse)
    return tuple(p[0] for p in pairs)


def batch_group_ids(ids: tuple, values: list) -> dict:
    """Group record IDs by their corresponding values.

    Replaces the `defaultdict(list)` loop in `grouped()` for the no-miss case.

    :param ids: tuple of record IDs
    :param values: list of group keys, same length as ids
    :return: dict mapping each distinct value to a list of IDs with that value
    """
    result: dict = {}
    _MISSING = object()
    for id_, val in zip(ids, values, strict=False):
        group = result.get(val, _MISSING)
        if group is _MISSING:
            result[val] = [id_]
        else:
            group.append(id_)
    return result


def scalar_cache_get(
    env_dict: dict,
    field: object,
    record_id: object,
    pending: object,
    sentinel: object,
) -> object:
    """Single-record cache lookup for _make_scalar_get hot path.

    Performs: env_dict["_field_cache_memo"][field][record_id]
    Returns the cached value, or sentinel on any miss or PENDING.
    """
    try:
        value = env_dict["_field_cache_memo"][field][record_id]
    except KeyError:
        return sentinel
    if value is pending:
        return sentinel
    return value
