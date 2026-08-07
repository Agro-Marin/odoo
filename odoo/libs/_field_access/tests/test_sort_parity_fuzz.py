import random
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from odoo.libs._field_access import sort_ids_by_cache, sort_ids_by_values
from odoo.libs._field_access._fallback import (
    sort_ids_by_cache as sort_ids_by_cache_py,
)
from odoo.libs._field_access._fallback import (
    sort_ids_by_values as sort_ids_by_values_py,
)

_PENDING = object()


def _reference(ids, values, reverse, null_high):
    if null_high is None:
        pairs = sorted(
            zip(ids, values, strict=True), key=lambda p: p[1], reverse=reverse
        )
        return tuple(p[0] for p in pairs)
    null_key = (1 if null_high else 0, "")
    val_rank = 0 if null_high else 1
    keyed = [
        (i, null_key if (v is None or v is False) else (val_rank, v))
        for i, v in zip(ids, values, strict=True)
    ]
    keyed.sort(key=lambda p: p[1], reverse=reverse)
    return tuple(p[0] for p in keyed)


def _int_column(rng, n):
    pool = [0, 1, -1, 7, 2**63 - 1, -(2**63)]
    return [
        rng.choice(pool) if rng.random() < 0.7 else rng.randrange(-50, 50)
        for _ in range(n)
    ]


def _bigint_column(rng, n):
    return [rng.randrange(-(2**70), 2**70) for _ in range(n)]


def _float_column(rng, n):
    pool = [0.0, -0.0, 1.5, -2.25, float("inf"), float("-inf"), 1e300, 5e-324]
    return [
        rng.choice(pool) if rng.random() < 0.6 else rng.uniform(-10, 10)
        for _ in range(n)
    ]


def _mixed_numeric_column(rng, n):
    return [rng.choice([0, 1, -3, 0.0, 2.5, -1.5, True]) for _ in range(n)]


def _str_column(rng, n):
    pool = [
        "",
        "a",
        "A",
        "abc",
        "abd",
        "√©tage",
        "é",
        "é",
        "\U0001f600",
        "￿",
        "z" * 40,
        " ",
        "0",
    ]
    return [rng.choice(pool) for _ in range(n)]


def _date_column(rng, n):
    base = date(2020, 6, 15)
    return [base + timedelta(days=rng.randrange(-4000, 4000)) for _ in range(n)]


def _datetime_column(rng, n):
    base = datetime(2020, 6, 15, 12, 30, 45)
    return [
        base
        + timedelta(
            seconds=rng.randrange(-(10**8), 10**8),
            microseconds=rng.randrange(0, 1_000_000),
        )
        for _ in range(n)
    ]


_COLUMNS = {
    "int": _int_column,
    "bigint": _bigint_column,
    "float": _float_column,
    "mixed-numeric": _mixed_numeric_column,
    "str": _str_column,
    "date": _date_column,
    "datetime": _datetime_column,
}


def _with_nulls(rng, values):
    return [rng.choice([None, False]) if rng.random() < 0.25 else v for v in values]


@pytest.mark.parametrize("kind", sorted(_COLUMNS))
def test_fuzz_parity_by_kind(kind):
    make = _COLUMNS[kind]
    for seed in range(30):
        rng = random.Random(f"{kind}-{seed}")
        n = rng.randrange(0, 41)
        ids = tuple(range(n))
        base = make(rng, n)
        for null_high in (None, False, True):
            values = base if null_high is None else _with_nulls(rng, list(base))
            for reverse in (False, True):
                tag = (kind, seed, reverse, null_high)
                expected = _reference(ids, values, reverse, null_high)
                assert (
                    sort_ids_by_values(ids, values, reverse, null_high) == expected
                ), tag
                assert (
                    sort_ids_by_values_py(ids, values, reverse, null_high) == expected
                ), tag
                cache = dict(zip(ids, values, strict=True))
                assert (
                    sort_ids_by_cache(cache, ids, _PENDING, reverse, null_high)
                    == expected
                ), tag
                assert (
                    sort_ids_by_cache_py(cache, ids, _PENDING, reverse, null_high)
                    == expected
                ), tag


def test_incomparable_column_raises_like_python():
    ids = (0, 1)
    values = [1, "a"]
    with pytest.raises(TypeError):
        sorted(values)
    with pytest.raises(TypeError):
        sort_ids_by_values(ids, values, False)
    with pytest.raises(TypeError):
        sort_ids_by_values_py(ids, values, False)


def test_none_without_null_handling_raises_like_python():
    ids = (0, 1, 2)
    values = [3, None, 1]
    with pytest.raises(TypeError):
        sorted(values)
    with pytest.raises(TypeError):
        sort_ids_by_values(ids, values, False)


def test_cache_miss_and_pending_return_none_in_both():
    ids = (0, 1, 2)
    cache_missing = {0: 5, 2: 1}
    cache_pending = {0: 5, 1: _PENDING, 2: 1}
    for cache in (cache_missing, cache_pending):
        assert sort_ids_by_cache(cache, ids, _PENDING, False) is None
        assert sort_ids_by_cache_py(cache, ids, _PENDING, False) is None


def test_aware_datetimes_sort_by_instant_like_python():
    early = datetime(2024, 1, 1, 23, 0, tzinfo=UTC)
    late = datetime(2024, 1, 2, 1, 0, tzinfo=timezone(timedelta(hours=5)))
    assert late.timestamp() - early.timestamp() == -10800
    ids = (10, 20)
    values = [early, late]
    expected = _reference(ids, values, False, None)
    assert expected == (20, 10)
    assert sort_ids_by_values(ids, values, False) == expected


def test_mixed_naive_aware_datetimes_raise_like_python():
    ids = (0, 1)
    values = [datetime(2024, 1, 1), datetime(2024, 1, 1, tzinfo=UTC)]
    with pytest.raises(TypeError):
        sorted(values)
    with pytest.raises(TypeError):
        sort_ids_by_values(ids, values, False)
