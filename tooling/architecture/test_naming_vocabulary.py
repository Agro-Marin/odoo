"""Tests for the §2.4 method-naming vocabulary gate.

Stdlib + pytest only, like every other gate test here — no Odoo import, no
database. Run with::

    pytest tooling/architecture/test_naming_vocabulary.py

The cases that matter are the *negative* ones. A verb gate is only useful if it
stays quiet on the code it must not touch, and the first run of this gate proved
that is the hard part: it flagged ``_drop_table`` (SQL DDL), ``_insert_cache``
(SQL DML), ``push_protection`` (a stack) and ``discard_field`` (``set.discard``)
before ``RESERVED`` and the model-class scope existed.
"""

import ast
import textwrap
from pathlib import Path

import pytest
from naming_vocabulary import (
    ABOLISHED,
    RESERVED,
    Violation,
    classify,
    is_model_class,
    measure,
)


def _cls(src: str) -> ast.ClassDef:
    return next(
        n
        for n in ast.walk(ast.parse(textwrap.dedent(src)))
        if isinstance(n, ast.ClassDef)
    )


# --- classify --------------------------------------------------------------


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
    """`_drop_table` is DDL, not a sloppy `_remove_`. See RESERVED."""
    assert classify(f"_{verb}_table") is None
    assert verb not in ABOLISHED


@pytest.mark.parametrize(
    "name",
    [
        "_prepare_invoice_vals",  # already canonical
        "_get_lines",
        "_check_date",
        "_compute_amount",
        "action_confirm",
        "create",
        "write",
        "__init__",
        "_validate",  # bare verb, no stem — an ORM hook, not ours to rename
    ],
)
def test_compliant_and_framework_names_are_quiet(name):
    assert classify(name) is None


def test_payload_verbs_only_fire_on_payload_shaped_names():
    """§2.4's Payload row decides `_build_invoice_vals`; it does not reach `_build_url`."""
    assert classify("_build_invoice_vals") == ("build", "_prepare_")
    assert classify("_make_line_values") == ("make", "_prepare_")
    assert classify("_build_url") is None
    assert classify("_compose_email") is None


# --- model-class scope -----------------------------------------------------


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
    """odoo/db, odoo/http and the ORM internals speak SQL and set/stack verbs."""
    assert not is_model_class(_cls(src))


# --- measure ---------------------------------------------------------------


def test_measure_refuses_an_empty_tree(tmp_path):
    """A count of 0 from an empty scan is indistinguishable from a clean tree."""
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
    """Guards against a scope change that silently empties the scan."""
    found = measure()
    assert found, "the odoo checkout should still have abolished-verb definitions"
    assert all(Path(v.path).suffix == ".py" for v in found)
