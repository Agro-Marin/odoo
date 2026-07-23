"""An x2many field domain filtering on a date-part granularity must not crash
the registry build.

Regression: ``_domain_depend_paths`` yielded trigger paths like
``partner_id.create_date.year_number``; ``Field.resolve_depends`` then walked
the granularity suffix as if it were a field of some comodel, making the next
``model_name`` ``None`` and killing the whole registry build with a bare
``KeyError: None`` naming no culprit.  Two layers fix this:

* the granularity suffix is stripped from the trigger path (it is a projection
  of the date field and can never be a trigger) — the domain itself keeps its
  granularity condition;
* a dependency path that walks past a non-relational field now fails loud with
  a descriptive error naming the field and path.
"""

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
    # nested-any domain whose leaf condition filters on a date-part
    # granularity of the partner's create_date
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

    # genuinely-bad path: 'name' is not relational, the path cannot continue
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
        # the trigger stops at the date field, without the granularity suffix
        assert "line_ids.partner_id.create_date" in depends
        assert not any(path.endswith("year_number") for path in depends)
        # force full dependency resolution (used to die with KeyError: None)
        registry._field_triggers  # noqa: B018


def test_bad_depends_path_raises_descriptive_error():
    with model_test_env(BadOrder) as env:
        registry = env.registry
        with pytest.raises(ValueError, match=r"'name' is not relational"):
            registry._field_triggers  # noqa: B018
