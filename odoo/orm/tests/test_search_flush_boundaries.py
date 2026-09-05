import pytest

from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env
from odoo.tools import SQL

_MOD = "test_search_flush_boundaries"


class BoundaryGroup(models.Model):
    _name = "flush.boundary.group"
    _module = _MOD
    _description = "Flush Boundary Group"
    _log_access = False

    value = fields.Integer()
    rank = fields.Integer(compute="_compute_rank", store=True)
    item_ids = fields.One2many("flush.boundary.item", "group_id")

    @api.depends("value")
    def _compute_rank(self):
        for record in self:
            record.rank = record.value * 2


class BoundaryItem(models.Model):
    _name = "flush.boundary.item"
    _module = _MOD
    _description = "Flush Boundary Item"
    _log_access = False

    name = fields.Char()
    happened = fields.Datetime()
    group_id = fields.Many2one("flush.boundary.group")
    group_rank = fields.Integer(related="group_id.rank")


@pytest.fixture
def env():
    with model_test_env(BoundaryGroup, BoundaryItem) as env:
        yield env


def test_timezone_search_does_not_require_a_postgres_catalog(env):
    Item = env["flush.boundary.item"].with_context(tz="America/Mexico_City")
    record = Item.create({"happened": "2026-03-01 02:00:00"})

    assert Item.search([("happened.month_number", "=", 2)]) == record


def test_custom_python_predicate_does_not_compile_sql(env):
    Item = env["flush.boundary.item"]
    records = Item.create([{"name": "keep"}, {"name": "skip"}])

    def sql_only(model, alias, query):
        raise AssertionError("the Python adapter must not compile custom SQL")

    domain = fields.Domain.custom(
        to_sql=sql_only, predicate=lambda record: record["name"] == "keep"
    ) & fields.Domain("id", "in", records.ids)

    assert Item.search(domain) == records[0]


def test_sql_only_custom_domain_fails_without_recursive_search(env):
    Item = env["flush.boundary.item"]
    Item.create({"name": "existing"})
    domain = fields.Domain.custom(to_sql=lambda *args: SQL("TRUE"))

    with pytest.raises(NotImplementedError, match="require a Python predicate"):
        Item.search(domain)


def test_related_order_flushes_the_stored_target(env):
    groups = env["flush.boundary.group"].create([{"value": 1}, {"value": 2}])
    items = env["flush.boundary.item"].create(
        [{"group_id": groups[0].id}, {"group_id": groups[1].id}]
    )
    env.flush_all()
    groups[0].value = 3

    assert items.search([], order="group_rank") == items[1] + items[0]
    assert env.cr.storage.get_row(groups._table, groups[0].id)["rank"] == 6


def test_one2many_domain_observes_a_dirty_inverse(env):
    groups = env["flush.boundary.group"].create([{}, {}])
    item = env["flush.boundary.item"].create({"name": "kept", "group_id": groups[0].id})
    env.flush_all()
    item.group_id = groups[1]

    assert groups.search([("item_ids", "any", [("name", "=", "kept")])]) == groups[1]
    assert env.cr.storage.get_row(item._table, item.id)["group_id"] == groups[1].id
