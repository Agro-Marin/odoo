from copy import deepcopy

import pytest

from odoo.libs.collections import FrozenOrderedSet, OrderedSet
from odoo.orm.domain.ast import Domain, DomainCondition


@pytest.mark.parametrize("container", [list, tuple, set, frozenset, OrderedSet])
def test_domains_own_collection_operands(container):
    operand = container([1, 2])
    domain = Domain("id", "in", operand)
    assert isinstance(domain, DomainCondition)
    lookup: dict[Domain, str] = {domain: "found"}
    if hasattr(operand, "append"):
        operand.append(3)
    elif hasattr(operand, "add"):
        operand.add(3)
    assert list(domain.value) == [1, 2]
    assert lookup[Domain("id", "in", container([1, 2]))] == "found"


def test_ordered_operands_remain_immutable_and_copyable():
    domain = Domain("id", "in", OrderedSet([2, 1]))
    assert isinstance(domain, DomainCondition)
    assert isinstance(domain.value, FrozenOrderedSet)
    assert list(domain.value) == [2, 1]
    assert not hasattr(domain.value, "add")
    assert deepcopy(domain.value) == domain.value


def test_nested_operand_is_owned():
    values = [1]
    domain = Domain("parent_id", "any", [("id", "in", values)])
    assert isinstance(domain, DomainCondition)
    before = hash(domain)
    values.append(2)
    assert domain.value[0][2] == (1,)
    assert hash(domain) == before


def test_cycle_is_rejected_before_hashing():
    operand: list[object] = []
    operand.append(operand)
    with pytest.raises(ValueError, match="Cyclic domain operand"):
        Domain("id", "in", operand)


@pytest.mark.parametrize("operator", ["any", "any!", "not any", "not any!"])
def test_freezing_preserves_prefix_operator_order(operator):
    leaves = [("value", "in", [1]), ("value", "in", [2]), ("value", "in", [3])]
    first = Domain("parent_id", operator, ["|", "&", *leaves])
    second = Domain("parent_id", operator, ["&", "|", *leaves])
    assert first != second
    assert len({first, second}) == 2


def test_nested_mapping_operand_is_owned():
    payload = {"ids": [1]}
    domain = Domain("payload", "=", payload)
    assert isinstance(domain, DomainCondition)
    lookup = {domain: "present"}
    payload["ids"].append(2)
    assert domain.value["ids"] == (1,)
    assert lookup[DomainCondition("payload", "=", {"ids": [1]})] == "present"
    with pytest.raises(NotImplementedError):
        domain.value["other"] = 2
