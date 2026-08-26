"""What a field hook is called, and the three ways it can be called wrong.

ADR-0049 fixes `_<attr>_<field>` for the method a field attribute names. The gate
holds 285 of them and had no test, which for a naming rule is the dangerous
shape: naming gates are the ones most likely to be widened by someone tidying a
regex, and the floor absorbs the widening silently.

Three kinds, and the difference between them is the whole design:

    misnamed    one field names the hook, and the hook is not called after it
    misleading  several fields name one hook, and it is called after one of them
    unmarked    a free-standing builder returns a domain and does not say so

`misleading` is the subtle one. A compute serving two fields is legitimate; a
compute serving two fields while carrying ONE of their names tells a reader it
computes only that one. That is a live case — `loyalty.program`'s
`_compute_coupon_count_display` wrote `coupon_count_label` too, and splitting it
gave each field its exact dependency set as well as its exact name.
"""

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


# --------------------------------------------------------------------------
# misnamed
# --------------------------------------------------------------------------


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
    """A family missing from `ATTRS` is a rule nothing enforces."""
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


# --------------------------------------------------------------------------
# misleading
# --------------------------------------------------------------------------


def test_a_hook_serving_several_fields_and_named_for_one_is_reported(tmp_path):
    """The `loyalty.program` shape, which is why this kind exists."""
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
    """Serving several fields is legitimate; claiming to serve one is not.

    A shared hook whose name belongs to no single field tells the reader the
    truth, so there is nothing to report.
    """
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
    """The key is (model, attr, method), not (attr, method).

    Two models reaching the same method name are two hooks, not one hook serving
    two fields. The fixture is chosen so the two readings give different KINDS
    rather than different counts: `A.total` names `_compute_total` correctly and
    `B.label` does not, so the answer is one `misnamed`. Merge the models and the
    method appears to serve `{total, label}` with `total` among them — which is
    the `misleading` rule, and a mutation dropping the model from the key was
    invisible until this fixture stopped using the same field name in both.
    """
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


# --------------------------------------------------------------------------
# unmarked — ADR-0054's head-first domain builder
# --------------------------------------------------------------------------


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
    """`_search_<field>` is ADR-0049's shape and 0054 leaves it alone.

    A domain is a search hook's contract, so naming it after the domain would be
    the redundant half, not the informative one.
    """
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
    """The case the `_search_` exemption exists for, and the only one that tests it.

    A hook bound by a visible `search=` is already exempt through `hooked`, so a
    fixture that declares both cannot see whether the prefix rule works — a
    mutation deleting it survived until this was added. The gate's own comment
    names the real shape: "a hook whose field lives in another module is not
    visible as a `search=` here".
    """
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


# --------------------------------------------------------------------------
# Scope and refusal
# --------------------------------------------------------------------------


def test_a_field_outside_a_model_is_not_a_field_hook(tmp_path):
    """`_model_of` is what makes the key a model; without it any class counts."""
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
    """0 misnamed hooks is what a perfectly named tree looks like.

    So a scan that reached no Python at all must refuse rather than hand the
    ratchet a number it would read as a catastrophic improvement — the same
    contract every counting gate here holds, and the reason
    `test_every_gate_refuses_an_empty_tree` sweeps for it.
    """
    with pytest.raises(RuntimeError, match="refusing to report a count"):
        gate.measure(roots=[tmp_path])


def test_the_attribute_families_are_all_declared():
    """A rule that is not in `ATTRS` is a rule the gate cannot see."""
    assert set(gate.ATTRS) >= {"compute", "search", "inverse", "default", "domain"}
