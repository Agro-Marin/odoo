import pytest

from odoo import fields, models
from odoo.orm.model_test_env import ModelRegistry, model_test_env

_MOD = "test_count_field_setup"


class Line(models.Model):
    _name = "c.line"
    _module = _MOD
    _description = "line"
    _log_access = False

    name = fields.Char()
    node_id = fields.Many2one("c.node")


class Node(models.Model):
    _name = "c.node"
    _module = _MOD
    _description = "node"
    _log_access = False

    name = fields.Char()
    line_ids = fields.One2many("c.line", "node_id")
    line_count = fields.Count("line_ids")


def _registry(*model_classes):
    return ModelRegistry(model_classes, db_name=":memory:")


def test_count_infers_the_attributes_of_a_computed_field():
    with model_test_env(Line, Node) as env:
        field = env["c.node"]._fields["line_count"]
        assert field.type == "integer"
        assert field.compute
        assert field.readonly
        assert not field.store
        assert not field.copy
        assert env.registry.field_depends[field] == ("line_ids",)


def test_count_resolves_the_field_it_counts():
    with model_test_env(Line, Node) as env:
        field = env["c.node"]._fields["line_count"]
        assert field.count_of == "line_ids"
        assert field.counts_in_database


def test_count_without_count_of_is_refused():
    with pytest.raises(TypeError, match="requires count_of"):

        class NoTarget(models.Model):
            _name = "c.no.target"
            _module = _MOD + "_no_target"
            _description = "no target"

            line_count = fields.Count()

        _registry(NoTarget)


def test_count_of_an_unknown_field_is_refused():
    class Unknown(models.Model):
        _name = "c.unknown"
        _module = _MOD + "_unknown"
        _description = "unknown"
        _log_access = False

        line_count = fields.Count("nope_ids")

    with pytest.raises(ValueError, match="does not exist"):
        _registry(Unknown)


def test_count_of_a_scalar_is_refused():
    class Scalar(models.Model):
        _name = "c.scalar"
        _module = _MOD + "_scalar"
        _description = "scalar"
        _log_access = False

        name = fields.Char()
        name_count = fields.Count("name")

    with pytest.raises(TypeError, match="counts a one2many or a many2many"):
        _registry(Scalar)


def test_a_related_count_is_refused():
    with pytest.raises(TypeError, match="cannot be related"):

        class Related(models.Model):
            _name = "c.related"
            _module = _MOD + "_related"
            _description = "related"
            _log_access = False

            node_id = fields.Many2one("c.node")
            line_count = fields.Count("line_ids", related="node_id.line_count")

        _registry(Line, Node, Related)
