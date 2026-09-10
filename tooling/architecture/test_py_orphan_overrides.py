from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import py_orphan_overrides as gate

HEAD = "from odoo import models\n\n\n"


def _measure(tmp_path: Path, **sources: str) -> list[gate.OrphanOverride]:
    scope = tmp_path / "odoo"
    scope.mkdir(parents=True, exist_ok=True)
    for name, text in sources.items():
        (scope / f"{name}.py").write_text(HEAD + text, encoding="utf-8")
    return gate.measure(scopes=(scope,))


def _names(found) -> list[str]:
    return sorted(o.name for o in found)


def _model(model: str, body: str, *, key: str = "_name", inherit: str = "") -> str:
    lines = [f"class M(models.Model):\n    {key} = {model!r}\n"]
    if inherit:
        lines.append(f"    _inherit = {inherit}\n")
    lines.append(body)
    return "".join(lines)


OVERRIDE = "\n    def {n}(self):\n        return super().{n}()\n"
IMPLEMENT = "\n    def {n}(self):\n        return 1\n"


def test_an_override_of_a_method_nothing_implements_is_reported(tmp_path):
    found = _measure(tmp_path, a=_model("sale.order", OVERRIDE.format(n="_gone")))
    assert _names(found) == ["_gone"]


def test_an_implementation_in_another_extension_of_the_model_resolves_it(tmp_path):
    found = _measure(
        tmp_path,
        owner=_model("sale.order", IMPLEMENT.format(n="_here")),
        caller=_model("sale.order", OVERRIDE.format(n="_here"), key="_inherit"),
    )
    assert found == []


def test_a_method_on_an_unrelated_model_is_not_a_parent(tmp_path):
    found = _measure(
        tmp_path,
        purchase=_model("purchase.order", IMPLEMENT.format(n="_prepare_invoice")),
        sale=_model(
            "sale.order", OVERRIDE.format(n="_prepare_invoice"), key="_inherit"
        ),
    )
    assert _names(found) == ["_prepare_invoice"], (
        "purchase.order's method is not in sale.order's MRO; resolving the name "
        "anywhere in the tree is what hid ten renamed overrides"
    )


def test_overrides_do_not_vouch_for_each_other(tmp_path):
    found = _measure(
        tmp_path,
        it=_model("sale.order", OVERRIDE.format(n="_prepare_invoice"), key="_inherit"),
        br=_model("sale.order", OVERRIDE.format(n="_prepare_invoice"), key="_inherit"),
    )
    assert _names(found) == ["_prepare_invoice", "_prepare_invoice"]


def test_an_ancestor_reached_through_inherit_resolves_it(tmp_path):
    found = _measure(
        tmp_path,
        mixin=_model("mixin.thing", IMPLEMENT.format(n="_shared"), key="_name"),
        user=_model(
            "sale.order", OVERRIDE.format(n="_shared"), inherit="['mixin.thing']"
        ),
    )
    assert found == []


def test_a_transitive_ancestor_resolves_it(tmp_path):
    found = _measure(
        tmp_path,
        root=_model("mixin.root", IMPLEMENT.format(n="_deep")),
        middle=_model("mixin.middle", "", inherit="['mixin.root']"),
        leaf=_model(
            "sale.order", OVERRIDE.format(n="_deep"), inherit="['mixin.middle']"
        ),
    )
    assert found == []


def test_an_ancestor_that_only_overrides_does_not_ground_it(tmp_path):
    found = _measure(
        tmp_path,
        mixin=_model("mixin.thing", OVERRIDE.format(n="_hollow")),
        user=_model(
            "sale.order", OVERRIDE.format(n="_hollow"), inherit="['mixin.thing']"
        ),
    )
    assert _names(found) == ["_hollow", "_hollow"]


def test_the_orm_base_composition_resolves_it(tmp_path):
    found = _measure(
        tmp_path,
        orm=(
            "class CreateMixin:\n    def create(self, vals):\n        return 1\n\n\n"
            "class BaseModel(CreateMixin):\n    pass\n"
        ),
        user=_model(
            "sale.order",
            "\n    def create(self, vals):\n        return super().create(vals)\n",
        ),
    )
    assert found == []


def test_extensions_of_the_base_model_resolve_for_every_model(tmp_path):
    found = _measure(
        tmp_path,
        everywhere=_model("base", IMPLEMENT.format(n="_grafted"), key="_inherit"),
        user=_model("sale.order", OVERRIDE.format(n="_grafted")),
    )
    assert found == []


def test_an_ancestor_outside_the_scanned_roots_is_not_judged(tmp_path):
    found = _measure(
        tmp_path,
        unrelated=_model("stock.move", IMPLEMENT.format(n="_x")),
        user=_model("sale.order", OVERRIDE.format(n="_x"), inherit="['elsewhere']"),
    )
    assert found == []


def test_a_name_defined_nowhere_else_is_reported_whatever_the_ancestry(tmp_path):
    found = _measure(
        tmp_path,
        user=_model(
            "sale.order", OVERRIDE.format(n="_nowhere"), inherit="['elsewhere']"
        ),
    )
    assert _names(found) == ["_nowhere"], (
        "no MRO this tree can build has a parent for a name no other class "
        "defines; an unknown ancestor cannot excuse it"
    )


def test_an_opaque_sibling_does_not_ground_a_name_the_tree_defines(tmp_path):
    found = _measure(
        tmp_path,
        unrelated=_model("stock.move", IMPLEMENT.format(n="_elsewhere")),
        opaque=("class O(models.Model, LibraryBase):\n    _inherit = 'sale.order'\n"),
        owner=_model("sale.order", ""),
        caller=_model("sale.order", OVERRIDE.format(n="_elsewhere"), key="_inherit"),
    )
    assert _names(found) == ["_elsewhere"]


def test_a_mixin_resolves_through_what_it_is_mixed_into(tmp_path):
    found = _measure(
        tmp_path,
        thread=_model("mail.thread", IMPLEMENT.format(n="message_subscribe")),
        mixin=(
            "class Mixin(models.AbstractModel):\n    _name = 'mixin.approval'\n"
            + OVERRIDE.format(n="message_subscribe")
        ),
        leave=_model("hr.leave", "", inherit="['mail.thread', 'mixin.approval']"),
    )
    assert found == []


def test_an_annotated_name_declares_the_model(tmp_path):
    found = _measure(
        tmp_path,
        owner=(
            "class Owner(models.Model):\n    _name: str = 'purchase.order'\n"
            + IMPLEMENT.format(n="_annotated")
        ),
        caller=_model(
            "purchase.order", OVERRIDE.format(n="_annotated"), key="_inherit"
        ),
    )
    assert found == []


def test_an_unknown_python_base_is_not_judged(tmp_path):
    source = (
        "class M(models.Model, ExternalHelper):\n    _name = 'sale.order'\n"
        + OVERRIDE.format(n="_helper")
    )
    assert _measure(tmp_path, user=source) == []


def test_a_class_that_is_not_a_model_is_not_scanned(tmp_path):
    source = "class Parser(lib.Base):\n" + OVERRIDE.format(n="parse")
    assert _measure(tmp_path, lib=source) == []


def test_a_string_inherit_without_a_name_extends_that_model(tmp_path):
    found = _measure(
        tmp_path,
        owner=_model("sale.order", IMPLEMENT.format(n="_named")),
        caller=_model("sale.order", OVERRIDE.format(n="_named"), key="_inherit"),
    )
    assert found == []


def test_an_empty_scan_refuses_instead_of_reporting_zero(tmp_path):
    with pytest.raises(RuntimeError, match="no Python sources"):
        gate.measure(scopes=(tmp_path / "absent",))


def test_findings_are_sorted_so_a_diff_is_readable(tmp_path):
    found = _measure(
        tmp_path,
        a=_model(
            "sale.order", OVERRIDE.format(n="_zeta") + OVERRIDE.format(n="_alpha")
        ),
    )
    assert [o.name for o in found] == ["_alpha", "_zeta"]


def test_roots_report_only_the_sibling_but_resolve_against_the_framework(tmp_path):
    core = tmp_path / "odoo"
    core.mkdir(parents=True)
    (core / "framework.py").write_text(
        HEAD + _model("sale.order", IMPLEMENT.format(n="_provided")), encoding="utf-8"
    )
    (core / "core_caller.py").write_text(
        HEAD + _model("sale.order", OVERRIDE.format(n="_core_gone"), key="_inherit"),
        encoding="utf-8",
    )
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    (sibling / "addon.py").write_text(
        HEAD
        + _model(
            "sale.order",
            OVERRIDE.format(n="_provided") + OVERRIDE.format(n="_missing"),
            key="_inherit",
        ),
        encoding="utf-8",
    )
    found = gate.measure(scopes=(core, sibling), report_scopes=(sibling,))
    assert _names(found) == ["_missing"]
