from __future__ import annotations

import ast
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


def test_an_annotated_field_declaration_is_read_like_any_other(tmp_path):
    found = _measure(
        tmp_path,
        """
class Thing(models.Model):
    _name = "thing"

    partner_id: ResPartner = fields.Many2one("res.partner", compute="_compute_owner")
""",
    )
    assert _kinds(found) == [("misnamed", "_compute_owner")]


def test_an_annotated_sibling_makes_a_hook_multi_field(tmp_path):
    # The annotation is the only difference from
    # test_a_hook_serving_several_fields_and_named_for_none_is_accepted. A scan
    # blind to ast.AnnAssign sees one field here and demands the hook be renamed
    # after it, which is the opposite of what §2.4.1 asks for.
    assert (
        _measure(
            tmp_path,
            """
class Thing(models.Model):
    _name = "thing"

    label = fields.Char(compute="_compute_labels")
    partner_ids: ResPartner = fields.Many2many("res.partner", compute="_compute_labels")
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


def _default_value(expression: str) -> ast.expr:
    call = ast.parse(f"fields.Integer(default={expression})", mode="eval").body
    return call.keywords[0].value


class TestAConstantIsNotAHookName:
    def test_a_bare_constant_is_not_a_hook(self):
        value = _default_value("DEFAULT_TOTAL")
        assert gate._hook_name("default", value) is None

    def test_a_dotted_constant_is_not_a_hook(self):
        value = _default_value("const.DEFAULT_TOTAL")
        assert gate._hook_name("default", value) is None

    def test_a_method_reference_is_still_read_as_a_hook(self):
        assert gate._hook_name("default", _default_value("_default_total")) == (
            "_default_total"
        )
        assert gate._hook_name("default", _default_value("self._default_total")) == (
            "_default_total"
        )

    def test_a_misnamed_default_hook_is_reported_through_the_gate(self, tmp_path):
        found = _measure(
            tmp_path,
            """
class Thing(models.Model):
    _name = "thing"

    total = fields.Integer(default=_default_wrong_name)

    def _default_wrong_name(self):
        pass
""",
        )
        assert [f.method for f in found] == ["_default_wrong_name"]

    def test_the_same_field_defaulted_from_a_constant_is_not(self, tmp_path):
        assert (
            _measure(
                tmp_path,
                """
DEFAULT_WRONG_NAME = 1


class Thing(models.Model):
    _name = "thing"

    total = fields.Integer(default=DEFAULT_WRONG_NAME)
""",
            )
            == []
        )


class TestAHookNameMentionedInAFieldCountsAsBound:
    def _unbound(self, tmp_path, source):
        path = tmp_path / "models" / "thing.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return gate.unbound_prefixes(roots=[tmp_path])

    def test_a_method_named_in_a_selection_is_bound(self, tmp_path):
        names, _calls = self._unbound(
            tmp_path,
            """
class Thing(models.Model):
    _name = "thing"

    kind = fields.Selection(selection=_selection_kinds)

    def _selection_kinds(self):
        return []
""",
        )
        assert names == 0, "the selection mentions it, so it is not unbound"

    def test_a_method_nothing_mentions_is_unbound(self, tmp_path):
        names, _calls = self._unbound(
            tmp_path,
            """
class Thing(models.Model):
    _name = "thing"

    def _selection_reached_by_nothing(self):
        return []
""",
        )
        assert names == 1
