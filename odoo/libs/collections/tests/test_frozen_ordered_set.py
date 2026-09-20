from collections.abc import Set as AbstractSet
from copy import deepcopy
from typing import Any, cast

import pytest

from odoo.libs.collections.ordered_set import FrozenOrderedSet


def test_order_is_stable_and_values_are_deduplicated():
    values = FrozenOrderedSet([3, 1, 3, 2])
    assert list(values) == [3, 1, 2]
    expected: AbstractSet[int] = {1, 2, 3}
    assert values == expected
    assert hash(values) == hash(frozenset([1, 2, 3]))


def test_public_storage_and_attributes_cannot_be_mutated():
    values = FrozenOrderedSet([1])
    with pytest.raises(TypeError):
        cast("Any", values._map)[2] = None
    with pytest.raises(TypeError, match="immutable"):
        values._map = {}
    with pytest.raises(TypeError, match="immutable"):
        del values._map


def test_set_algebra_and_copy_return_immutable_sets():
    values = FrozenOrderedSet([2, 1])
    for result in (
        values | {3},
        values & {1},
        values - {1},
        values ^ {1, 3},
        deepcopy(values),
    ):
        assert isinstance(result, FrozenOrderedSet)
        assert not hasattr(result, "add")
    assert list(deepcopy(values)) == [2, 1]


def test_intersection_keeps_left_operand_order():
    values = FrozenOrderedSet([3, 2, 1])
    assert list(values & [1, 3]) == [3, 1]
    assert list(values & (value for value in [1, 3])) == [3, 1]
