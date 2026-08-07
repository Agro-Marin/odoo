import pytest

from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_domain_granularity_depends"
_MOD_BAD = "test_domain_granularity_depends_bad"


class Partner(models.Model):
    _name = "g.partner"
    _module = _MOD
    _description = "partner"

    name = fields.Char()


class Line(models.Model):
    _name = "g.line"
    _module = _MOD
    _description = "line"
    _log_access = False

    name = fields.Char()
    order_id = fields.Many2one("g.order")
    partner_id = fields.Many2one("g.partner")


class Order(models.Model):
    _name = "g.order"
    _module = _MOD
    _description = "order"
    _log_access = False

    name = fields.Char()
    line_ids = fields.One2many(
        "g.line",
        "order_id",
        domain=[("partner_id", "any", [("create_date.year_number", "=", 2024)])],
    )


class BadOrder(models.Model):
    _name = "g.badorder"
    _module = _MOD_BAD
    _description = "bad order"
    _log_access = False

    name = fields.Char()
    total = fields.Integer(compute="_compute_total")

    @api.depends("name.upper")
    def _compute_total(self):
        for record in self:
            record.total = 0


def test_registry_builds_and_strips_granularity_suffix():
    with model_test_env(Partner, Line, Order) as env:
        registry = env.registry
        field = registry["g.order"]._fields["line_ids"]
        depends = set(registry.field_depends[field])
        assert "line_ids.partner_id" in depends
        assert "line_ids.partner_id.create_date" in depends
        assert not any(path.endswith("year_number") for path in depends)
        registry._ensure_field_triggers()


def test_bad_depends_path_raises_descriptive_error():
    with model_test_env(BadOrder) as env:
        registry = env.registry
        with pytest.raises(ValueError, match=r"'name' is not relational"):
            registry._ensure_field_triggers()
