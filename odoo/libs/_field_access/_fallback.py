"""Python reference implementations of the field-cache access functions.

Despite the module name, this is NOT a runtime fallback: ``odoo_rust`` is a hard
requirement (enforced in ``odoo.init``).  Two roles:

* ``scalar_cache_get`` IS used in production -- its 3-dict-subscript hit path
  beats the PyO3 call boundary, so the façade deliberately takes it from here.
* the batch-op functions are the test oracle for the Rust versions (see
  ``tests/test_field_access.py``): semantically identical, just slower.
"""

from operator import itemgetter as _itemgetter

_itemgetter_1 = _itemgetter(1)

_I64_MIN = -(2**63)
_I64_MAX = 2**63 - 1


def _as_i64(value: object) -> int | None:
    """Return *value* as an i64, or ``None`` if Rust's extract would fail."""
    if isinstance(value, int) and _I64_MIN <= value <= _I64_MAX:
        return value
    return None


def to_prefetch_ids(
    record_id: object,
    prefetch_ids: tuple,
    field_cache: dict,
    prefetch_max: int,
) -> tuple | None:
    """Select the record IDs to prefetch alongside *record_id*.

    Oracle for ``odoo_rust.to_prefetch_ids``, the computational core of
    ``Field._to_prefetch``.  Returns ``None`` when *record_id* is not a positive
    i64 (a NewId or 0), signalling the caller to take its own Python path --
    prefetching only ever makes sense for real, persisted rows.

    An id joins the result when it is a positive i64, is not already cached, and
    has not been added yet.  *record_id* itself is always first, so the record
    that triggered the miss is never dropped no matter what else is filtered out.

    This is deliberately STRICTER than the loop it mirrors in
    ``Field._to_prefetch``, which admits any truthy id (``bool(id_) == kind``).
    That admitted negative ints, ``str`` ids and ints beyond i64 -- values that
    can only produce a nonsense prefetch query -- and, because the Rust path
    rejected them, the two disagreed with no test to catch it.
    """
    rec_id = _as_i64(record_id)
    if rec_id is None or rec_id <= 0:
        return None

    seen = {rec_id}
    result = [record_id]
    for id_ in prefetch_ids:
        if len(result) >= prefetch_max:
            break
        id_val = _as_i64(id_)
        if id_val is None or id_val <= 0:
            continue
        if id_ not in field_cache and id_val not in seen:
            seen.add(id_val)
            result.append(id_)
    return tuple(result)


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
    if len(results) != len(ids):
        raise ValueError(
            "batch_cache_fill: `results` must have the same length as `ids`"
        )
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
    _null_rank = 1 if null_high else 0
    _val_rank = 0 if null_high else 1
    _null_key = (_null_rank, "")
    keys = [_null_key if (v is None or v is False) else (_val_rank, v) for v in values]
    pairs = list(zip(ids, keys, strict=False))
    pairs.sort(key=_itemgetter_1, reverse=reverse)
    return tuple(p[0] for p in pairs)


def sort_ids_by_cache(
    field_cache: dict,
    ids: tuple,
    pending: object,
    reverse: bool,
    null_high: bool | None = None,
) -> tuple | None:
    """Fused cache-read + sort for the single-field ``sorted()`` fast path.

    Reads ``field_cache[id]`` for each id directly instead of building an
    intermediate values list. Returns ``None`` on the first cache miss or
    ``pending`` value (caller falls back to the record-based sort); otherwise
    the sorted id tuple. Semantically ``batch_cache_values`` + ``sort_ids_by_values``.
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
    return sort_ids_by_values(ids, values, reverse, null_high)


def batch_group_ids(ids: tuple, values: list) -> dict[object, list]:
    """Group record IDs by their corresponding values.

    Replaces the `defaultdict(list)` loop in `grouped()` for the no-miss case.

    :param ids: tuple of record IDs
    :param values: list of group keys, same length as ids
    :return: dict mapping each distinct value to a list of IDs with that value
    """
    if len(values) != len(ids):
        raise ValueError("batch_group_ids: `values` must have the same length as `ids`")
    result: dict[object, list] = {}
    _MISSING = object()
    for id_, val in zip(ids, values, strict=True):
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
