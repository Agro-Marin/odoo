from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import field_hook_naming as gate


def _measure(tmp_path: Path, source: str) -> list[gate.Violation]:
    path = tmp_path / "models" / "thing.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return gate.measure(roots=[tmp_path])


def _kinds(found) -> list[tuple[str, str]]:
    return sorted((f.kind, f.method) for f in found)


def test_a_correctly_named_hook_is_not_reported(tmp_path):
    assert (
        _measure(
            tmp_path,
            """
class Thing(models.Model):
    _name = "thing"

    total = fields.Integer(compute="_compute_total")
""",
        )
        == []
    )


@pytest.mark.parametrize("attr", ["compute", "search", "inverse"])
def test_every_string_attribute_is_policed(tmp_path, attr):
    found = _measure(
        tmp_path,
        f"""
class Thing(models.Model):
    _name = "thing"

    total = fields.Integer({attr}="_{attr}_wrong_name")
""",
    )
    assert _kinds(found) == [("misnamed", f"_{attr}_wrong_name")]


def test_the_expected_name_is_reported_so_the_fix_is_obvious(tmp_path):
    (found,) = _measure(
        tmp_path,
        """
class Thing(models.Model):
    _name = "thing"

    total = fields.Integer(compute="_compute_sum")
""",
    )
    assert (found.attr, found.field) == ("compute", "total")
    assert "_compute_total" in str(found)


def test_a_hook_serving_several_fields_and_named_for_one_is_reported(tmp_path):
    found = _measure(
        tmp_path,
        """
class Thing(models.Model):
    _name = "thing"

    label = fields.Char(compute="_compute_display")
    display = fields.Char(compute="_compute_display")
""",
    )
    assert _kinds(found) == [("misleading", "_compute_display")]


def test_a_hook_serving_several_fields_and_named_for_none_is_accepted(tmp_path):
    assert (
        _measure(
            tmp_path,
            """
class Thing(models.Model):
    _name = "thing"

    label = fields.Char(compute="_compute_labels")
    display = fields.Char(compute="_compute_labels")
""",
        )
        == []
    )


def test_a_hook_name_is_scoped_to_its_model(tmp_path):
    found = _measure(
        tmp_path,
        """
class A(models.Model):
    _name = "a"

    total = fields.Integer(compute="_compute_total")


class B(models.Model):
    _name = "b"

    label = fields.Char(compute="_compute_total")
""",
    )
    assert _kinds(found) == [("misnamed", "_compute_total")]


def test_a_free_standing_domain_builder_must_say_so_in_front(tmp_path):
    found = _measure(
        tmp_path,
        """
class Thing(models.Model):
    _name = "thing"

    def _selectable_domain(self):
        return [("active", "=", True)]
""",
    )
    assert _kinds(found) == [("unmarked", "_selectable_domain")]


@pytest.mark.parametrize("name", ["_get_domain_selectable", "get_domain_selectable"])
def test_a_head_first_name_is_accepted(tmp_path, name):
    assert (
        _measure(
            tmp_path,
            f"""
class Thing(models.Model):
    _name = "thing"

    def {name}(self):
        return [("active", "=", True)]
""",
        )
        == []
    )


def test_a_search_hook_keeps_its_own_shape(tmp_path):
    assert (
        _measure(
            tmp_path,
            """
class Thing(models.Model):
    _name = "thing"

    total = fields.Integer(search="_search_total")

    def _search_total(self, operator, value):
        return [("id", operator, value)]
""",
        )
        == []
    )


def test_an_unbound_search_hook_is_exempt_by_its_prefix_alone(tmp_path):
    assert (
        _measure(
            tmp_path,
            """
class Thing(models.Model):
    _name = "thing"

    def _search_elsewhere(self, operator, value):
        return [("id", "=", value)]
""",
        )
        == []
    )


def test_a_method_that_returns_no_domain_is_not_a_builder(tmp_path):
    assert (
        _measure(
            tmp_path,
            """
class Thing(models.Model):
    _name = "thing"

    def _selectable_values(self):
        return [1, 2, 3]
""",
        )
        == []
    )


def test_a_field_outside_a_model_is_not_a_field_hook(tmp_path):
    assert (
        _measure(
            tmp_path,
            """
class NotAModel:
    total = fields.Integer(compute="_compute_wrong")
""",
        )
        == []
    )


def test_an_empty_scan_refuses_instead_of_reporting_zero(tmp_path):
    with pytest.raises(RuntimeError, match="refusing to report a count"):
        gate.measure(roots=[tmp_path])


def test_the_attribute_families_are_all_declared():
    assert set(gate.ATTRS) >= {"compute", "search", "inverse", "default", "domain"}
