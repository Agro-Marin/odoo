import random
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from odoo.libs._field_access._fallback import (
    sort_ids_by_cache as sort_ids_by_cache_py,
)

odoo_rust = pytest.importorskip(
    "odoo_rust", exc_type=ImportError
)  # a parity test needs both sides
sort_ids_by_cache = odoo_rust.sort_ids_by_cache

_PENDING = object()


def _rust(ids, values, reverse, null_high=True):
    return sort_ids_by_cache(
        dict(zip(ids, values, strict=True)), ids, _PENDING, reverse, null_high
    )


def _py(ids, values, reverse, null_high=True):
    return sort_ids_by_cache_py(
        dict(zip(ids, values, strict=True)), ids, _PENDING, reverse, null_high
    )


def _reference(ids, values, reverse, null_high):
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
        "\x00",
        "abc\x00",
        "abcdefg\x00",
        "abcdefgh",
        "abcdefgh\x00",
        "a\x00b",
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
        for null_high in (False, True):
            for values in (base, _with_nulls(rng, list(base))):
                for reverse in (False, True):
                    tag = (kind, seed, reverse, null_high)
                    expected = _reference(ids, values, reverse, null_high)
                    assert _rust(ids, values, reverse, null_high) == expected, tag
                    assert _py(ids, values, reverse, null_high) == expected, tag


def test_temporal_extremes_survive_the_packed_representation():
    moments = [
        datetime(1, 1, 1, 0, 0, 0, 0),
        datetime(1, 1, 1, 0, 0, 0, 1),
        datetime(2020, 2, 29, 12, 0, 0, 0),
        datetime(2020, 12, 31, 23, 59, 59, 999_999),
        datetime(9999, 12, 31, 23, 59, 59, 999_998),
        datetime(9999, 12, 31, 23, 59, 59, 999_999),
    ]
    ids = tuple(range(1, len(moments) + 1))
    shuffled = list(moments)
    random.Random(4).shuffle(shuffled)
    order = {m: i for i, m in enumerate(moments)}
    expected = tuple(
        i for _, i in sorted(zip(shuffled, ids, strict=True), key=lambda p: order[p[0]])
    )
    assert _rust(ids, list(shuffled), False) == expected
    assert _py(ids, list(shuffled), False) == expected


def test_a_date_sorts_at_midnight_of_its_day():
    day = date(2026, 8, 28)
    ids = (1, 2, 3)
    dates = [date(2026, 8, 29), day, date(2026, 8, 27)]
    assert _rust(ids, dates, False) == (3, 2, 1)

    midnight = datetime(2026, 8, 28, 0, 0, 0, 0)
    times = [datetime(2026, 8, 28, 0, 0, 0, 1), midnight, datetime(2026, 8, 27, 23, 59)]
    assert _rust(ids, times, False) == (3, 2, 1)


def test_incomparable_column_raises_like_python():
    ids = (0, 1)
    values = [1, "a"]
    with pytest.raises(TypeError):
        sorted(values)  # type: ignore[type-var]
    with pytest.raises(TypeError):
        _rust(ids, values, False)
    with pytest.raises(TypeError):
        _py(ids, values, False)


def test_cache_miss_and_pending_return_none_in_both():
    ids = (0, 1, 2)
    cache_missing = {0: 5, 2: 1}
    cache_pending = {0: 5, 1: _PENDING, 2: 1}
    for cache in (cache_missing, cache_pending):
        assert sort_ids_by_cache(cache, ids, _PENDING, False, True) is None
        assert sort_ids_by_cache_py(cache, ids, _PENDING, False, True) is None


def test_aware_datetimes_sort_by_instant_like_python():
    early = datetime(2024, 1, 1, 23, 0, tzinfo=UTC)
    late = datetime(2024, 1, 2, 1, 0, tzinfo=timezone(timedelta(hours=5)))
    assert late.timestamp() - early.timestamp() == -10800
    ids = (10, 20)
    values = [early, late]
    expected = _reference(ids, values, False, True)
    assert expected == (20, 10)
    assert _rust(ids, values, False) == expected


def test_mixed_naive_aware_datetimes_raise_like_python():
    ids = (0, 1)
    values = [datetime(2024, 1, 1), datetime(2024, 1, 1, tzinfo=UTC)]
    with pytest.raises(TypeError):
        sorted(values)
    with pytest.raises(TypeError):
        _rust(ids, values, False)


class _RandomOrder:
    """A `__lt__` that is not a total order. `sorted()` returns some
    permutation; Rust's `sort_by` would panic, and `PanicException` is a
    `BaseException` that no `except Exception` sees."""

    def __init__(self, rng):
        self._rng = rng

    def __lt__(self, other):
        return self._rng.random() < 0.5


def test_a_non_total_order_returns_a_permutation_like_python():
    n = 3000
    ids = tuple(range(n))
    for null_high in (False, True):
        rng = random.Random(f"random-order-{null_high}")
        values = [_RandomOrder(rng) for _ in range(n)]
        result = _rust(ids, values, False, null_high)
        assert sorted(result) == list(ids)


class _LateFailure:
    calls = 0

    def __init__(self, value):
        self.value = value

    def __lt__(self, other):
        type(self).calls += 1
        if type(self).calls > 500:
            raise ValueError("late")
        return self.value < other.value


def test_a_comparison_error_midway_propagates_like_python():
    ids = tuple(range(3000))
    rng = random.Random("late")
    values = [_LateFailure(rng.random()) for _ in ids]
    _LateFailure.calls = 0
    with pytest.raises(ValueError, match="late"):
        _rust(ids, values, False)
    _LateFailure.calls = 0
    with pytest.raises(ValueError, match="late"):
        _py(ids, values, False)


class _ContrarianEq:
    """Null-aware keys are `(rank, value)` tuples, whose comparison asks
    `__eq__` before `__lt__`; the fallback must go through the same
    protocol as the reference, which a hand-written `__lt__`-only
    comparator did not."""

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return True

    def __hash__(self):
        return 0

    def __lt__(self, other):
        return self.value < other.value


def test_null_aware_fallback_uses_the_references_tuple_keys():
    ids = (0, 1, 2, 3)
    values = [_ContrarianEq(3), None, _ContrarianEq(1), _ContrarianEq(2)]
    for reverse in (False, True):
        expected = _reference(ids, values, reverse, True)
        assert _rust(ids, values, reverse, True) == expected
        assert _py(ids, values, reverse, True) == expected
