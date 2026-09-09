import ast
import textwrap
from pathlib import Path

import pytest
from naming_vocabulary import (
    ABOLISHED,
    RESERVED,
    ROOT,
    SCAN_ROOTS,
    Violation,
    _python_files,
    classify,
    collection_head_order,
    governed_definitions,
    governs_module_helpers,
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


def test_the_payload_suffix_chooses_an_assemble_verbs_canonical_not_its_reach():
    assert classify("_build_invoice_vals") == ("build", "_prepare_")
    assert classify("_make_line_values") == ("make", "_prepare_")
    assert classify("_build_url") == ("build", "_get_")
    assert classify("_compose_email") == ("compose", "_get_")


def test_a_bare_assemble_verb_stays_out_of_this_gate():
    assert classify("_build") is None
    assert classify("make") is None


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
        "class Session(dict):\n    def remove_old_sessions(self): pass",
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


def test_the_real_tree_is_still_scanned():
    # This asserted the checkout still HAD abolished verbs, which stopped being a
    # statement about the gate the moment the sweep reached zero: a ratchet at 0
    # is the goal, not a broken measurement. What has to stay true is that the
    # scan still reaches files -- an empty walk would report 0 for the same
    # reason a clean tree does. The classification itself is covered against a
    # fixture above, and `measure` refusing an empty scan is covered by
    # test_every_gate_refuses_an_empty_tree.
    scanned = _python_files([ROOT / r for r in SCAN_ROOTS])
    assert len(scanned) > 1000, (
        f"only {len(scanned)} files scanned under {', '.join(SCAN_ROOTS)} — the "
        f"walk is broken, and every count it reports would be 0 by accident"
    )
    assert all(p.suffix == ".py" for p in scanned)
    assert all(Path(v.path).suffix == ".py" for v in measure())


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


# §2.4.13's three populations. Each fixture is a real addon layout rather than a
# bare file, because the scope test is `__manifest__.py` above a models/ wizard/
# wizards/ directory and a fixture that skips either half would pass while
# measuring nothing.
HELPERS = """
    def make_widget_vals(record):
        return {}


    class Helper:
        def _fetch_rows(self):
            return []


    class WidgetLine(models.Model):
        _name = "widget.line"

        def _get_lines(self):
            def _retrieve_bucket(key):
                return key

            return _retrieve_bucket
"""


def _addon(tmp_path, subdir="models", manifest=True):
    module = tmp_path / "widget"
    package = module / subdir
    package.mkdir(parents=True)
    if manifest:
        (module / "__manifest__.py").write_text("{'name': 'widget'}\n")
    (package / "widget_line.py").write_text(textwrap.dedent(HELPERS))
    return module


@pytest.mark.parametrize("subdir", ["models", "wizard", "wizards"])
def test_an_addon_helper_file_is_governed_in_all_three_directories(tmp_path, subdir):
    assert governs_module_helpers(_addon(tmp_path, subdir) / subdir / "widget_line.py")


def test_all_three_uncounted_populations_are_measured(tmp_path):
    found = {v.name for v in measure([_addon(tmp_path)])}
    assert found == {"make_widget_vals", "_fetch_rows", "_retrieve_bucket"}, (
        "§2.4.13 governs a module-level function, a plain-class method and a "
        f"nested def in an addon models/ file; measured {sorted(found)}"
    )


def test_a_definition_is_counted_once_however_deeply_nested(tmp_path):
    module = tmp_path / "widget"
    (module / "models").mkdir(parents=True)
    (module / "__manifest__.py").write_text("{'name': 'widget'}\n")
    (module / "models" / "deep.py").write_text(
        textwrap.dedent("""
            class WidgetLine(models.Model):
                _name = "widget.line"

                def _get_lines(self):
                    def outer():
                        def _retrieve_bucket(key):
                            return key

                        return _retrieve_bucket

                    return outer
        """)
    )
    # `ast.walk` from every function reaches the innermost `def` once per
    # enclosing frame, so this is the assertion that keeps a doubly nested name
    # from being reported twice and inflating the floor.
    assert [v.name for v in measure([module])] == ["_retrieve_bucket"]


def test_a_helper_outside_models_and_wizard_is_not_governed(tmp_path):
    outside = _addon(tmp_path, "controllers")
    assert not governs_module_helpers(outside / "controllers" / "widget_line.py")
    assert measure([outside]) == []


def test_a_models_directory_with_no_manifest_above_it_is_not_an_addon(tmp_path):
    loose = _addon(tmp_path, manifest=False)
    assert not governs_module_helpers(loose / "models" / "widget_line.py")
    assert measure([loose]) == []


def test_the_core_package_keeps_the_narrow_population(tmp_path):
    # `naming_core_vocabulary.py` reads every function under odoo/odoo/ on
    # sharper rules and holds a hard zero with an argued allowlist. Widening
    # this gate over the same tree would ask one question twice and answer it
    # two ways -- `append_paths` being §2.4.13's own example of a name that gate
    # allowlists and this one would report.
    core_file = ROOT / "odoo" / "addons" / "base" / "models" / "ir_asset_paths.py"
    if not core_file.is_file():
        pytest.skip(f"{core_file} has moved; the scope claim needs a new witness")
    assert not governs_module_helpers(core_file)


def test_a_model_method_is_still_counted_without_the_widening(tmp_path):
    # The narrow population is not conditional on the addon test: a model class
    # in a file the widening does not reach is measured exactly as before.
    (tmp_path / "sale_order.py").write_text(
        textwrap.dedent("""
            class SaleOrder(models.Model):
                _name = "sale.order"

                def _validate_amount(self):
                    pass

                def helper():
                    pass
        """)
    )
    assert not governs_module_helpers(tmp_path / "sale_order.py")
    assert [v.name for v in measure([tmp_path])] == ["_validate_amount"]


def test_governed_definitions_reads_a_file_without_measuring_it(tmp_path):
    module = _addon(tmp_path)
    path = module / "models" / "widget_line.py"
    names = [n.name for n in governed_definitions(path, ast.parse(path.read_text()))]
    assert sorted(names) == [
        "_fetch_rows",
        "_get_lines",
        "_retrieve_bucket",
        "make_widget_vals",
    ], (
        "the population is every definition the vocabulary reaches, compliant "
        f"ones included; classify() is what narrows it. Got {sorted(names)}"
    )
