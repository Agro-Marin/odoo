import contextlib

import pytest

from odoo.orm.domain.ast import (
    _OPTIMIZATION_KEY_KIND,
    _OPTIMIZATIONS_FOR,
    OptimizationLevel,
)
from odoo.orm.domain.constants import ACCEPTED_CONDITION_OPERATORS
from odoo.orm.domain.optimizations import field_type_optimization, operator_optimization
from odoo.orm.fields.base import Field


def _registered_keys() -> set[str]:
    keys: set[str] = set()
    for mapping in _OPTIMIZATIONS_FOR.values():
        keys |= {key for key, entries in mapping.items() if entries}
    return keys


def test_every_registered_key_is_an_operator_or_a_field_type():
    known = ACCEPTED_CONDITION_OPERATORS | set(Field._by_type__)
    unknown = _registered_keys() - known
    assert not unknown, (
        f"optimisation(s) registered under {sorted(unknown)}, which is neither a "
        f"domain operator nor a field type in Field._by_type__; nothing will ever "
        f"look those keys up, so the optimisation is dead on arrival"
    )


def test_each_key_is_valid_for_the_kind_it_was_claimed_as():
    wrong = {
        key: kind
        for key, kind in _OPTIMIZATION_KEY_KIND.items()
        if key in _registered_keys()
        and (
            (kind == "operator" and key not in ACCEPTED_CONDITION_OPERATORS)
            or (kind == "field_type" and key not in Field._by_type__)
        )
    }
    assert not wrong, (
        f"registered under the wrong key space: {wrong}. An operator must be in "
        f"ACCEPTED_CONDITION_OPERATORS and a field type in Field._by_type__"
    )


def test_the_two_key_spaces_do_not_overlap():
    operators = {k for k, v in _OPTIMIZATION_KEY_KIND.items() if v == "operator"}
    field_types = {k for k, v in _OPTIMIZATION_KEY_KIND.items() if v == "field_type"}
    assert not (operators & field_types)


@contextlib.contextmanager
def _isolated_registry():
    level = OptimizationLevel.BASIC
    mapping = _OPTIMIZATIONS_FOR[level]
    saved_kinds = dict(_OPTIMIZATION_KEY_KIND)
    saved_entries = {key: list(value) for key, value in mapping.items()}
    try:
        yield level
    finally:
        _OPTIMIZATION_KEY_KIND.clear()
        _OPTIMIZATION_KEY_KIND.update(saved_kinds)
        mapping.clear()
        mapping.update(saved_entries)


def test_claiming_a_key_for_both_kinds_is_refused():
    with _isolated_registry() as level:
        operator_optimization(["="], level)(lambda *a: None)
        with pytest.raises(ValueError, match="already registered as a domain operator"):
            field_type_optimization(["="], level)(lambda *a: None)


def test_the_probe_above_left_nothing_behind():
    assert _OPTIMIZATION_KEY_KIND.get("=") == "operator"
    for entries in _OPTIMIZATIONS_FOR[OptimizationLevel.BASIC]["="]:
        assert getattr(entries, "__name__", "") != "<lambda>"


def test_an_empty_key_list_is_refused_on_both_doors():
    with pytest.raises(ValueError, match="at least one operator"):
        operator_optimization([])
    with pytest.raises(ValueError, match="at least one field type"):
        field_type_optimization([])


def test_the_field_type_registry_is_populated():
    assert len(Field._by_type__) >= 15, Field._by_type__
