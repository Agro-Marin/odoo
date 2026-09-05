import pytest

from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_search_flush"


class FlushGroup(models.Model):
    _name = "flush.group"
    _module = _MOD
    _description = "Search Flush Group"
    _order = "rank"
    _log_access = False

    value = fields.Integer()
    rank = fields.Integer(compute="_compute_rank", store=True)
    untouched = fields.Integer(compute="_compute_untouched", store=True)

    @api.depends("value")
    def _compute_rank(self):
        for record in self:
            record.rank = record.value * 2

    @api.depends("value")
    def _compute_untouched(self):
        for record in self:
            record.untouched = record.value + 100


class FlushItem(models.Model):
    _name = "flush.item"
    _module = _MOD
    _description = "Search Flush Item"
    _log_access = False

    name = fields.Char()
    group_id = fields.Many2one("flush.group")


@pytest.fixture
def env():
    with model_test_env(FlushGroup, FlushItem) as env:
        yield env


def _pending(record, name):
    return record.env.is_to_compute(record._fields[name], record)


def test_id_search_keeps_unrelated_compute_pending(env):
    group = env["flush.group"].create({"value": 1})
    env.flush_all()
    group.value = 3

    assert _pending(group, "rank")
    assert group.search([("id", "=", group.id)], order="id") == group

    assert _pending(group, "rank")
    assert _pending(group, "untouched")
    assert group.value == 3
    assert env.cr.storage.get_row(group._table, group.id)["rank"] == 2


@pytest.mark.parametrize("selector", ["domain", "order"])
def test_search_flushes_only_the_required_computed_field(env, selector):
    groups = env["flush.group"].create([{"value": 1}, {"value": 2}])
    env.flush_all()
    groups[0].value = 3

    if selector == "domain":
        result = groups.search([("rank", ">", 4)], order="id")
        assert result == groups[0]
    else:
        result = groups.search([], order="rank desc")
        assert result == groups

    assert not _pending(groups[0], "rank")
    assert _pending(groups[0], "untouched")
    assert env.cr.storage.get_row(groups._table, groups[0].id)["rank"] == 6


@pytest.mark.parametrize("selector", ["domain", "order"])
def test_related_query_flushes_comodel_dependencies(env, selector):
    groups = env["flush.group"].create([{"value": 1}, {"value": 2}])
    items = env["flush.item"].create(
        [
            {"name": "a", "group_id": groups[0].id},
            {"name": "b", "group_id": groups[1].id},
        ]
    )
    env.flush_all()
    groups[0].value = 3

    if selector == "domain":
        assert items.search([("group_id.rank", ">", 4)], order="id") == items[0]
    else:
        assert items.search([], order="group_id") == items[1] + items[0]

    assert not _pending(groups[0], "rank")
    assert _pending(groups[0], "untouched")
    assert env.cr.storage.get_row(groups._table, groups[0].id)["rank"] == 6


def test_search_does_not_overwrite_dirty_cache_with_stored_values(env):
    item = env["flush.item"].create({"name": "old"})
    env.flush_all()
    item.name = "new"

    assert item.search([("id", "=", item.id)]) == item

    assert item.name == "new"
    assert env.cr.storage.get_row(item._table, item.id)["name"] == "old"


def test_search_does_not_populate_unread_columns(env):
    item = env["flush.item"].create({"name": "stored"})
    env.flush_all()
    env.invalidate_all(flush=False)

    assert item.search([("id", "=", item.id)]) == item

    assert list(item._fields["name"]._cache_missing_ids(item)) == item.ids
    assert item.name == "stored"
