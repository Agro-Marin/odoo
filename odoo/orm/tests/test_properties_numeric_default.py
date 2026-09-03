import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_properties_numeric_default"


class PropParent(models.Model):
    _name = "prop.parent.numdef"
    _module = _MOD
    _description = "Prop Parent"

    name = fields.Char()
    child_properties = fields.PropertiesDefinition()


class PropChild(models.Model):
    _name = "prop.child.numdef"
    _module = _MOD
    _description = "Prop Child"

    parent_id = fields.Many2one("prop.parent.numdef")
    props = fields.Properties(
        definition="parent_id.child_properties", definition_record="parent_id"
    )


@pytest.fixture
def env():
    gen = model_test_env(PropParent, PropChild)
    yield gen.__enter__()
    gen.__exit__(None, None, None)


def test_add_default_values_keeps_a_configured_zero_default(env):
    parent = env["prop.parent.numdef"].create(
        {
            "name": "Parent",
            "child_properties": [
                {"name": "count", "type": "integer", "default": 0},
            ],
        }
    )
    field = env["prop.child.numdef"]._fields["props"]

    result = field._add_default_values(env, {"props": {}, "parent_id": parent})

    assert result[0]["value"] == 0


def test_add_default_values_keeps_a_nonzero_default(env):
    parent = env["prop.parent.numdef"].create(
        {
            "name": "Parent",
            "child_properties": [
                {"name": "count", "type": "integer", "default": 5},
            ],
        }
    )
    field = env["prop.child.numdef"]._fields["props"]

    result = field._add_default_values(env, {"props": {}, "parent_id": parent})

    assert result[0]["value"] == 5


def test_add_default_values_leaves_value_unset_without_a_default(env):
    parent = env["prop.parent.numdef"].create(
        {
            "name": "Parent",
            "child_properties": [
                {"name": "count", "type": "integer"},
            ],
        }
    )
    field = env["prop.child.numdef"]._fields["props"]

    result = field._add_default_values(env, {"props": {}, "parent_id": parent})

    assert result[0].get("value") is None
