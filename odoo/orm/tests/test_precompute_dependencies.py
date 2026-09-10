import pytest

from odoo import api, fields, models
from odoo.orm.model_test_env import ModelRegistry, model_test_env

_MOD = "test_precompute_dependencies"


def _registry(*model_classes):
    return ModelRegistry(model_classes, db_name=":memory:")


def test_a_precompute_over_a_stored_compute_that_does_not_precompute_is_refused():
    class Late(models.Model):
        _name = "p.late"
        _module = _MOD + "_late"
        _description = "late"
        _log_access = False

        base = fields.Integer()
        doubled = fields.Integer(compute="_compute_doubled", store=True)
        tripled = fields.Integer(
            compute="_compute_tripled", store=True, precompute=True
        )

        @api.depends("base")
        def _compute_doubled(self):
            for record in self:
                record.doubled = record.base * 2

        @api.depends("doubled")
        def _compute_tripled(self):
            for record in self:
                record.tripled = record.doubled * 3

    registry = _registry(Late)
    with pytest.raises(ValueError, match="cannot be precomputed"):
        registry._get_field_triggers()


class Parent(models.Model):
    _name = "p.parent"
    _module = _MOD
    _description = "parent"
    _log_access = False

    base = fields.Integer()
    doubled = fields.Integer(compute="_compute_doubled", store=True)

    @api.depends("base")
    def _compute_doubled(self):
        for record in self:
            record.doubled = record.base * 2


class Child(models.Model):
    _name = "p.child"
    _module = _MOD
    _description = "child"
    _log_access = False

    base = fields.Integer()
    parent_id = fields.Many2one("p.parent")
    doubled = fields.Integer(compute="_compute_doubled", store=True, precompute=True)
    tripled = fields.Integer(compute="_compute_tripled", store=True, precompute=True)
    inherited = fields.Integer(
        compute="_compute_inherited", store=True, precompute=True
    )

    @api.depends("base")
    def _compute_doubled(self):
        for record in self:
            record.doubled = record.base * 2

    @api.depends("doubled")
    def _compute_tripled(self):
        for record in self:
            record.tripled = record.doubled * 3

    @api.depends("parent_id.doubled")
    def _compute_inherited(self):
        for record in self:
            record.inherited = record.parent_id.doubled


def test_a_precompute_over_a_precomputed_dependency_holds():
    with model_test_env(Parent, Child) as env:
        env.registry._get_field_triggers()
        assert env["p.child"]._fields["tripled"].precompute


def test_a_many2one_hop_ends_the_precompute_chain():
    with model_test_env(Parent, Child) as env:
        env.registry._get_field_triggers()
        assert env["p.child"]._fields["inherited"].precompute
