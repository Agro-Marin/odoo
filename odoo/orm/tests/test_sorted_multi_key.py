import itertools

from odoo.libs._field_access import sort_ids_by_values
from odoo.libs._field_access._fallback import (
    sort_ids_by_values as sort_ids_by_values_py,
)

_IDS = tuple(range(24))
_TIED = [i % 3 for i in _IDS]


def _cpython(ids, values, reverse):
    return tuple(
        i
        for i, _ in sorted(
            zip(ids, values, strict=True), key=lambda pair: pair[1], reverse=reverse
        )
    )


def test_primitive_is_stable_in_both_directions():
    for reverse in (False, True):
        assert sort_ids_by_values(_IDS, _TIED, reverse) == _cpython(
            _IDS, _TIED, reverse
        ), reverse


def test_rust_and_python_reference_agree():
    for reverse in (False, True):
        assert sort_ids_by_values(_IDS, _TIED, reverse) == sort_ids_by_values_py(
            _IDS, _TIED, reverse
        )


def test_successive_passes_equal_a_tuple_key_sort():
    key_a = [i % 3 for i in _IDS]
    key_b = [(i * 7) % 5 for i in _IDS]
    by_id = dict(zip(_IDS, key_a, strict=True))

    for reverse in (False, True):
        composite = tuple(
            i
            for i, _ in sorted(
                zip(_IDS, list(zip(key_a, key_b, strict=True)), strict=True),
                key=lambda pair: pair[1],
                reverse=reverse,
            )
        )
        first = sort_ids_by_values(_IDS, key_b, reverse)
        second = sort_ids_by_values(first, [by_id[i] for i in first], reverse)
        assert second == composite, reverse


def test_three_keys_with_mixed_directions():
    key_a = [i % 2 for i in _IDS]
    key_b = [i % 3 for i in _IDS]
    key_c = list(_IDS)
    directions = (False, True, False)

    columns = [key_a, key_b, key_c]
    ids = _IDS
    for values, desc in reversed(list(zip(columns, directions, strict=True))):
        by_id = dict(zip(_IDS, values, strict=True))
        ids = sort_ids_by_values(ids, [by_id[i] for i in ids], desc)

    expected = tuple(
        sorted(
            _IDS,
            key=lambda i: (key_a[i], -key_b[i], key_c[i]),
        )
    )
    assert ids == expected


def test_null_ranking_survives_stacking():
    values = [None if i % 4 == 0 else i % 5 for i in _IDS]
    for reverse, null_high in itertools.product((False, True), (False, True)):
        result = sort_ids_by_values(_IDS, values, reverse, null_high)
        nulls = [i for i in result if values[i] is None]
        non_nulls = [i for i in result if values[i] is not None]
        assert sorted(nulls) == sorted(i for i in _IDS if values[i] is None)
        positions = [result.index(i) for i in nulls]
        assert positions == list(range(min(positions), max(positions) + 1))
        assert bool(min(positions) == 0) == (null_high == reverse), (
            reverse,
            null_high,
            result,
        )
        assert len(non_nulls) + len(nulls) == len(_IDS)
