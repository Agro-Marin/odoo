import logging

import pytest

from odoo import fields, models
from odoo.orm import registration
from odoo.orm.model_test_env import ModelRegistry


class CycA(models.Model):
    _name = "regcyc.a"
    _module = "test_reg_cycle"
    _description = "Cycle A"


class CycB(models.Model):
    _name = "regcyc.b"
    _module = "test_reg_cycle"
    _description = "Cycle B"
    _inherits = {"regcyc.a": "a_id"}

    a_id = fields.Many2one("regcyc.a", required=True, ondelete="cascade")


class CycAExt(models.Model):
    _inherit = "regcyc.a"
    _module = "test_reg_cycle"
    _inherits = {"regcyc.b": "b_id"}

    b_id = fields.Many2one("regcyc.b", required=True, ondelete="cascade")


def test_circular_inherits_raises_type_error():
    with pytest.raises(TypeError, match="Circular _inherits chain involving model"):
        ModelRegistry([CycA, CycB, CycAExt])


class InhCycA(models.Model):
    _name = "reginh.a"
    _module = "test_reg_inherit_cycle"
    _description = "Inherit cycle A"


class InhCycB(models.Model):
    _name = "reginh.b"
    _inherit = "reginh.a"
    _module = "test_reg_inherit_cycle"
    _description = "Inherit cycle B"


class InhCycAExt(models.Model):
    # extends reginh.a while also parenting reginh.b, which already extends
    # reginh.a -- closing a cycle in `_inherit_children`
    _name = "reginh.a"
    _inherit = ["reginh.a", "reginh.b"]
    _module = "test_reg_inherit_cycle"
    _description = "Inherit cycle A ext"


def test_circular_inherit_raises_type_error():
    with pytest.raises(TypeError, match="Circular _inherit chain involving model"):
        ModelRegistry([InhCycA, InhCycB, InhCycAExt])


class DiamondBase(models.Model):
    _name = "regdia.base"
    _module = "test_reg_diamond"
    _description = "Diamond base"


class DiamondLeft(models.Model):
    _name = "regdia.left"
    _inherit = "regdia.base"
    _module = "test_reg_diamond"
    _description = "Diamond left"


class DiamondRight(models.Model):
    _name = "regdia.right"
    _inherit = "regdia.base"
    _module = "test_reg_diamond"
    _description = "Diamond right"


class DiamondBaseExtLeft(models.Model):
    _name = "regdia.base"
    _inherit = "regdia.base"
    _module = "test_reg_diamond"


class DiamondBaseExtRight(models.Model):
    _name = "regdia.base"
    _inherit = "regdia.base"
    _module = "test_reg_diamond"


def test_diamond_inherit_children_are_not_mistaken_for_a_cycle():
    registry = ModelRegistry(
        [
            DiamondBase,
            DiamondLeft,
            DiamondRight,
            DiamondBaseExtLeft,
            DiamondBaseExtRight,
        ]
    )
    assert set(registry["regdia.base"]._inherit_children) == {
        "regdia.left",
        "regdia.right",
    }


class AbsThing(models.AbstractModel):
    _name = "regabs.thing"
    _module = "test_reg_abstract"
    _description = "Abstract Thing"


class AbsThingConcreteExt(models.Model):
    _inherit = "regabs.thing"
    _module = "test_reg_abstract"


def test_extension_cannot_make_abstract_model_concrete():
    with pytest.raises(
        TypeError, match=r"transforms the abstract model 'regabs\.thing'"
    ):
        ModelRegistry([AbsThing, AbsThingConcreteExt])


class TransThing(models.TransientModel):
    _name = "regtrans.thing"
    _module = "test_reg_transient"
    _description = "Transient Thing"


class TransThingModelExt(models.Model):
    _inherit = "regtrans.thing"
    _module = "test_reg_transient"


def test_extension_cannot_make_transient_model_persistent():
    with pytest.raises(
        TypeError,
        match=r"transforms the transient model 'regtrans\.thing' into a "
        r"non-transient model",
    ):
        ModelRegistry([TransThing, TransThingModelExt])


class PlainThing(models.Model):
    _name = "regplain.thing"
    _module = "test_reg_plain"
    _description = "Plain Thing"


class PlainThingTransientExt(models.TransientModel):
    _inherit = "regplain.thing"
    _module = "test_reg_plain"


def test_extension_cannot_make_model_transient():
    with pytest.raises(
        TypeError,
        match=r"transforms the model 'regplain\.thing' into a transient model",
    ):
        ModelRegistry([PlainThing, PlainThingTransientExt])


class ConcreteParent(models.Model):
    _name = "regpar.parent"
    _module = "test_reg_parent_ext"
    _description = "Concrete Parent"


class AbstractChild(models.AbstractModel):
    _name = "regpar.child"
    _inherit = "regpar.parent"
    _module = "test_reg_parent_ext"
    _description = "Abstract Child"


def test_abstract_model_cannot_inherit_concrete_model():
    with pytest.raises(
        TypeError,
        match=r"abstract model 'regpar\.child' cannot inherit from "
        r"non-abstract model 'regpar\.parent'",
    ):
        ModelRegistry([ConcreteParent, AbstractChild])


class MissParent(models.Model):
    _name = "regmiss.parent"
    _module = "test_reg_inherits_missing"
    _description = "Miss Parent"


class MissChild(models.Model):
    _name = "regmiss.child"
    _module = "test_reg_inherits_missing"
    _description = "Miss Child"
    _inherits = {"regmiss.parent": "parent_id"}


def test_inherits_without_field_raises_type_error():
    with pytest.raises(
        TypeError,
        match=r"Missing many2one field definition for _inherits reference "
        r"'parent_id' in model 'regmiss\.child'",
    ):
        ModelRegistry([MissParent, MissChild])


class BadFlagsParent(models.Model):
    _name = "regbad.parent"
    _module = "test_reg_inherits_flags"
    _description = "Bad Flags Parent"


class BadFlagsChild(models.Model):
    _name = "regbad.child"
    _module = "test_reg_inherits_flags"
    _description = "Bad Flags Child"
    _inherits = {"regbad.parent": "parent_id"}

    parent_id = fields.Many2one("regbad.parent", ondelete="cascade")


def test_inherits_field_must_be_required_with_cascade_or_restrict():
    with pytest.raises(
        TypeError,
        match=r"must be marked as 'delegate', 'required' with "
        r"ondelete='cascade' or 'restrict'",
    ):
        ModelRegistry([BadFlagsParent, BadFlagsChild])


class BadRecName(models.Model):
    _name = "regrec.bad"
    _module = "test_reg_rec_name"
    _description = "Bad Rec Name"
    _rec_name = "missing_field"


def test_rec_name_must_be_a_field():
    with pytest.raises(
        TypeError, match=r"Invalid _rec_name='missing_field' for model 'regrec\.bad'"
    ):
        ModelRegistry([BadRecName])


class BadActiveName(models.Model):
    _name = "regact.bad"
    _module = "test_reg_active_name"
    _description = "Bad Active Name"
    _active_name = "name"

    name = fields.Char()


def test_active_name_only_supports_active_and_x_active():
    with pytest.raises(
        TypeError,
        match=r"Invalid _active_name='name' for model 'regact\.bad'; only "
        r"'active' and 'x_active' are supported",
    ):
        ModelRegistry([BadActiveName])


class MissingActiveName(models.Model):
    _name = "regact.missing"
    _module = "test_reg_active_missing"
    _description = "Missing Active Field"
    _active_name = "active"


def test_active_name_field_must_exist():
    with pytest.raises(TypeError, match=r"Invalid _active_name='active'"):
        ModelRegistry([MissingActiveName])


class AutoNames(models.Model):
    _name = "regauto.thing"
    _module = "test_reg_auto_names"
    _description = "Auto Names"

    name = fields.Char()
    active = fields.Boolean(default=True)


class NoNames(models.Model):
    _name = "regauto.bare"
    _module = "test_reg_auto_names"
    _description = "No Names"

    label = fields.Char()


def test_rec_name_and_active_name_auto_detection():
    registry = ModelRegistry([AutoNames, NoNames])
    assert registry["regauto.thing"]._rec_name == "name"
    assert registry["regauto.thing"]._active_name == "active"
    assert registry["regauto.bare"]._rec_name is None
    assert registry["regauto.bare"]._active_name is None


class DupFirst(models.Model):
    _name = "regdup.thing"
    _module = "test_reg_duplicate"
    _description = "Dup First"

    a = fields.Char()


class DupSecond(models.Model):
    _name = "regdup.thing"
    _module = "test_reg_duplicate"
    _description = "Dup Second"

    b = fields.Char()


def test_same_name_without_inherit_warns_and_replaces(caplog):
    with caplog.at_level(logging.WARNING, logger="odoo.registry"):
        registry = ModelRegistry([DupFirst, DupSecond])

    messages = [
        record.getMessage()
        for record in caplog.records
        if "replaces the existing definition" in record.getMessage()
    ]
    assert len(messages) == 1, caplog.records
    assert "'regdup.thing'" in messages[0]
    assert "'test_reg_duplicate'" in messages[0]
    assert "Did you mean to inherit it?" in messages[0]

    model_fields = registry["regdup.thing"]._fields
    assert "b" in model_fields
    assert "a" not in model_fields


class PopThing(models.Model):
    _name = "regpop.thing"
    _module = "test_reg_pop_field"
    _description = "Pop Thing"

    name = fields.Char()
    other = fields.Char()


def test_pop_field_fixes_rec_name_and_display_name_depends():
    registry = ModelRegistry([PopThing])
    model_cls = registry["regpop.thing"]
    display_name = model_cls._fields["display_name"]

    assert model_cls._rec_name == "name"
    assert registry.field_depends[display_name] == ("name",)

    popped = registration.pop_field(model_cls, "name")

    assert popped is not None
    assert popped.name == "name"
    assert "name" not in model_cls._fields
    assert model_cls._rec_name is None
    assert registry.field_depends[display_name] == ()
    assert display_name not in registry.field_depends


def test_pop_field_of_non_rec_name_field_leaves_rec_name_alone():
    registry = ModelRegistry([PopThing])
    model_cls = registry["regpop.thing"]
    display_name = model_cls._fields["display_name"]

    popped = registration.pop_field(model_cls, "other")

    assert popped is not None
    assert popped.name == "other"
    assert "other" not in model_cls._fields
    assert model_cls._rec_name == "name"
    assert registry.field_depends[display_name] == ("name",)


def test_pop_field_of_unknown_name_returns_none():
    registry = ModelRegistry([PopThing])
    model_cls = registry["regpop.thing"]
    assert registration.pop_field(model_cls, "does_not_exist") is None
