"""Assigning an empty value to an x2many must still seed the cache on new
records.

Regression: write_batch dropped empty command lists as "guaranteed no-ops";
true for real records (the DB is the source of truth) but not for NewIds,
whose cache IS the value — a compute assigning ``[]`` on a new record (e.g.
res.groups.all_implied_by_ids, whose compute assigns ``g.ids + ...`` where
``.ids`` is empty for a NewId) then died with "Compute method failed to
assign" in every onchange.
"""

from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_x2many_empty_assign"


class Tag(models.Model):
    _name = "e.tag"
    _module = _MOD
    _description = "tag"

    name = fields.Char()


class Line(models.Model):
    _name = "e.line"
    _module = _MOD
    _description = "line"
    _log_access = False

    name = fields.Char()
    node_id = fields.Many2one("e.node")


class Node(models.Model):
    _name = "e.node"
    _module = _MOD
    _description = "node"
    _log_access = False

    name = fields.Char()
    tag_ids = fields.Many2many("e.tag")
    line_ids = fields.One2many("e.line", "node_id")
    computed_tag_ids = fields.Many2many(
        "e.tag", "e_node_computed_tag_rel", compute="_compute_tags"
    )

    @api.depends("name")
    def _compute_tags(self):
        for record in self:
            # mirrors res.groups._compute_all_implied_by_ids: .ids is empty
            # for a NewId, so this assigns [] on new records
            record.computed_tag_ids = record.ids


def test_computed_m2m_assigning_empty_on_new_record():
    with model_test_env(Tag, Line, Node) as env:
        node = env["e.node"].new({"name": "n"})
        # must not raise "Compute method failed to assign"
        assert node.computed_tag_ids._ids == ()


def test_explicit_empty_assign_on_new_record_seeds_cache():
    with model_test_env(Tag, Line, Node) as env:
        node = env["e.node"].new({"name": "n"})
        node.tag_ids = []
        assert node.tag_ids._ids == ()
        node.line_ids = []
        assert node.line_ids._ids == ()


def test_empty_write_on_real_record_is_noop():
    with model_test_env(Tag, Line, Node) as env:
        tag = env["e.tag"].create({"name": "t"})
        node = env["e.node"].create({"name": "n", "tag_ids": [(6, 0, tag.ids)]})
        node.write({"tag_ids": []})
        assert node.tag_ids == tag, "empty command list must not clear the m2m"
