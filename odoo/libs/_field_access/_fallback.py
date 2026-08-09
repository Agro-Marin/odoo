from operator import itemgetter as _itemgetter

_itemgetter_1 = _itemgetter(1)

_I64_MIN = -(2**63)
_I64_MAX = 2**63 - 1


def _as_i64(value: object) -> int | None:
    if isinstance(value, int) and _I64_MIN <= value <= _I64_MAX:
        return value
    return None


def to_prefetch_ids(
    record_id: object,
    prefetch_ids: tuple,
    field_cache: dict,
    prefetch_max: int,
) -> tuple | None:
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
    results: list = []
    miss_indices: list[int] = []
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
    passing_ids: list = []
    miss_indices: list[int] = []
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
    values: list = []
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
    values: list = []
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
    if len(values) != len(ids):
        raise ValueError("batch_group_ids: `values` must have the same length as `ids`")
    result: dict[object, list] = {}
    for id_, val in zip(ids, values, strict=True):
        group = result.get(val)
        if group is None:
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
    try:
        value = env_dict["_field_cache_memo"][field][record_id]
    except KeyError:
        return sentinel
    if value is pending:
        return sentinel
    return value
