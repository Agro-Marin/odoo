import ast
import textwrap
from pathlib import Path

import pytest
from naming_vocabulary import (
    ABOLISHED,
    RESERVED,
    Violation,
    classify,
    collection_head_order,
    is_model_class,
    measure,
)


def _cls(src: str) -> ast.ClassDef:
    return next(
        n
        for n in ast.walk(ast.parse(textwrap.dedent(src)))
        if isinstance(n, ast.ClassDef)
    )


@pytest.mark.parametrize(
    ("name", "canonical"),
    [
        ("_validate_amount", "_check_"),
        ("_verify_signature", "_check_"),
        ("_ensure_partner", "_check_"),
        ("_fetch_lines", "_get_"),
        ("_retrieve_token", "_get_"),
        ("_assign_owner", "_update_"),
        ("_delete_old_orders", "_remove_"),
        ("_append_tax", "_add_"),
    ],
)
def test_abolished_verbs_are_flagged(name, canonical):
    assert classify(name) is not None
    assert classify(name)[1] == canonical


@pytest.mark.parametrize("verb", sorted(RESERVED))
def test_reserved_verbs_are_never_flagged(verb):
    assert classify(f"_{verb}_table") is None
    assert verb not in ABOLISHED


@pytest.mark.parametrize(
    "name",
    [
        "_prepare_invoice_vals",
        "_get_lines",
        "_check_date",
        "_compute_amount",
        "action_confirm",
        "create",
        "write",
        "__init__",
        "_validate",
    ],
)
def test_compliant_and_framework_names_are_quiet(name):
    assert classify(name) is None


def test_payload_verbs_only_fire_on_payload_shaped_names():
    assert classify("_build_invoice_vals") == ("build", "_prepare_")
    assert classify("_make_line_values") == ("make", "_prepare_")
    assert classify("_build_url") is None
    assert classify("_compose_email") is None


@pytest.mark.parametrize(
    "src",
    [
        "class SaleOrder(models.Model):\n    _name = 'sale.order'",
        "class Wiz(models.TransientModel):\n    _name = 'w'",
        "class Mixin(models.AbstractModel):\n    _name = 'm'",
        "class Extend(SomethingElse):\n    _inherit = 'sale.order'",
    ],
)
def test_model_classes_are_in_scope(src):
    assert is_model_class(_cls(src))


@pytest.mark.parametrize(
    "src",
    [
        "class Cursor:\n    def _drop_table(self): pass",
        "class Session(dict):\n    def delete_old_sessions(self): pass",
        "class Registry(Mapping):\n    def discard_field(self): pass",
    ],
)
def test_framework_classes_are_out_of_scope(src):
    assert not is_model_class(_cls(src))


def test_measure_refuses_an_empty_tree(tmp_path):
    (tmp_path / "styles.scss").write_text("body { color: red; }\n")
    with pytest.raises(RuntimeError, match="refusing to report a count"):
        measure([tmp_path])


def test_measure_finds_a_planted_violation(tmp_path):
    (tmp_path / "sale_order.py").write_text(
        textwrap.dedent("""
            class SaleOrder(models.Model):
                _name = "sale.order"

                def _validate_amount(self):
                    pass

                def _drop_table(self):
                    pass
        """)
    )
    found = measure([tmp_path])
    assert [v.name for v in found] == ["_validate_amount"]
    assert found[0].canonical == "_check_"


def test_measure_does_not_count_an_override(tmp_path):
    """An override does not choose its name -- the base does."""
    (tmp_path / "m.py").write_text(
        textwrap.dedent(
            """
            from odoo import models

            class M(models.Model):
                _inherit = "some.model"

                def _validate_leave_request(self):
                    super()._validate_leave_request()
                    return True
            """
        )
    )
    assert measure([tmp_path]) == []


def test_measure_counts_the_same_name_when_it_is_not_an_override(tmp_path):
    """The exemption is the `super()` call, not the name."""
    (tmp_path / "m.py").write_text(
        textwrap.dedent(
            """
            from odoo import models

            class M(models.Model):
                _name = "some.model"

                def _validate_leave_request(self):
                    return True
            """
        )
    )
    assert [v.name for v in measure([tmp_path])] == ["_validate_leave_request"]


def test_measure_counts_an_override_of_a_DIFFERENT_method(tmp_path):
    """Calling `super().write()` does not licence an abolished verb of its own."""
    (tmp_path / "m.py").write_text(
        textwrap.dedent(
            """
            from odoo import models

            class M(models.Model):
                _inherit = "some.model"

                def _validate_amount(self):
                    return super().write({})
            """
        )
    )
    assert [v.name for v in measure([tmp_path])] == ["_validate_amount"]


def test_measure_skips_test_files(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_sale.py").write_text(
        "class T(models.Model):\n    _name='t'\n    def _validate_x(self): pass\n"
    )
    with pytest.raises(RuntimeError):
        measure([tmp_path])


def test_violation_renders_the_replacement():
    v = Violation(
        path="addons/sale/models/sale_order.py",
        line=12,
        name="_validate_amount",
        verb="validate",
        canonical="_check_",
    )
    assert "_validate_amount" in str(v)
    assert "_check_*" in str(v)


def test_the_real_tree_still_measures():
    found = measure()
    assert found, "the odoo checkout should still have abolished-verb definitions"
    assert all(Path(v.path).suffix == ".py" for v in found)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("_get_model_names_in_tree", "head"),
        ("_get_keys_client_only", "head"),
        ("get_view_types_for_window", "head"),
        ("_get_allowed_models", "tail"),
        ("_get_supported_account_types", "tail"),
        ("_get_company_address_field_names", "tail"),
        ("_get_fields_inheriting_views", None),
        ("_get_fields_readable", None),
        ("_get_partner_ids", None),
        ("_compute_xml_id", None),
        ("_sync_path_reservations", None),
    ],
)
def test_collection_head_order_reads_the_position(name, expected):
    assert collection_head_order(name) is expected


def test_collection_head_census_counts_both_orders():
    from naming_vocabulary import census

    c = census()
    assert c.heads_searched > 0
    assert c.heads_head_first > 0
    assert c.heads_tail_first > 0, (
        "the ordering is settled and unapplied outside the fields family; a zero "
        "here means the search stopped matching, not that the tree was converted"
    )


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        (
            "@api.constrains('order', 'field_id')\ndef _check_order(self): pass",
            ["order", "field_id"],
        ),
        ("@constrains('date')\ndef _check_date(self): pass", ["date"]),
        ("def _check_date(self): pass", []),
        ("@api.model\ndef _check_date(self): pass", []),
        ("@api.constrains(*FIELDS)\ndef _check_date(self): pass", []),
        ("@api.onchange('partner_id')\ndef _onchange_partner_id(self): pass", []),
    ],
)
def test_constrains_fields_reads_the_decorator(src, expected):
    from naming_vocabulary import constrains_fields

    node = next(
        n
        for n in ast.walk(ast.parse(textwrap.dedent(src)))
        if isinstance(n, ast.FunctionDef)
    )
    assert constrains_fields(node) == expected


def test_constrains_census_sizes_the_family_it_exempts():
    from naming_vocabulary import census

    c = census()
    assert c.constrains_hooks > 0
    assert c.constrains_single > 0
    assert 0 < c.constrains_named_for_field < c.constrains_single, (
        "a constraint named for its field is the minority the exemption predicts; "
        "0 or all of them means the decorator is no longer being read"
    )
    assert 0 < c.constrains_unruled < c.constrains_hooks - c.constrains_canonical
