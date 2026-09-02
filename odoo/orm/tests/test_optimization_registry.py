import ast
import contextlib
from pathlib import Path

import pytest

from odoo.orm.domain import optimizations
from odoo.orm.domain.ast import (
    _OPTIMIZATION_KEY_KIND,
    _OPTIMIZATIONS_FOR,
    OptimizationLevel,
)
from odoo.orm.domain.constants import ACCEPTED_CONDITION_OPERATORS
from odoo.orm.domain.optimizations import field_type_optimization, operator_optimization
from odoo.orm.fields._field_sql import _FieldSqlMixin
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


_KEPT_FIELD_TYPE_DISPATCH = frozenset(
    {
        ("boolean",),
        ("integer", "float", "monetary"),
        ("many2one", "many2one_reference", "one2many", "many2many"),
    }
)

_FIELD_TYPES_OWNED_BY_A_FIELD_CLASS = frozenset(
    {
        "binary",
        "char",
        "date",
        "datetime",
        "html",
        "many2many",
        "many2one",
        "one2many",
        "properties",
        "text",
    }
)


def _field_type_dispatch_in_optimizations() -> set[tuple[str, ...]]:
    source = Path(optimizations.__file__).read_text(encoding="utf-8")
    registrations: set[tuple[str, ...]] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        name = (
            callee.attr
            if isinstance(callee, ast.Attribute)
            else getattr(callee, "id", "")
        )
        if name != "field_type_optimization" or not node.args:
            continue
        registrations.add(
            tuple(
                element.value
                for element in ast.walk(node.args[0])
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            )
        )
    return registrations


def test_every_field_type_dispatch_left_in_optimizations_is_deliberately_kept():
    dispatched = _field_type_dispatch_in_optimizations()
    assert dispatched == set(_KEPT_FIELD_TYPE_DISPATCH), (
        f"optimizations.py registers field-type optimisations for "
        f"{sorted(dispatched)}; the deliberately-kept set is "
        f"{sorted(_KEPT_FIELD_TYPE_DISPATCH)}. Per-type semantics belong on the "
        f"owning field class, through Field._optimize_condition; the registry keeps "
        f"only what no single field class owns - 'boolean' because ast.py looks that "
        f"key up for any field with is_boolean rather than type == 'boolean', the "
        f"numeric trio because Integer, Float and Monetary are unrelated Field "
        f"subclasses, and the relational quartet because it spans _Relational and "
        f"Many2oneReference, which subclasses Integer"
    )


def test_the_moved_field_types_are_owned_by_a_field_class():
    for field_type in sorted(_FIELD_TYPES_OWNED_BY_A_FIELD_CLASS):
        field_class = Field._by_type__[field_type]
        assert (
            field_class._optimize_condition is not _FieldSqlMixin._optimize_condition
        ), (
            f"{field_class.__name__} answers for field type {field_type!r} but does "
            f"not override _optimize_condition, so its per-type domain semantics are "
            f"dispatched by nothing"
        )
