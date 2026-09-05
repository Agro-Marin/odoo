import sys

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_x2many_prefetch_survives_invalidation"


class PrefetchParent(models.Model):
    _name = "prefetch.parent"
    _module = _MOD
    _description = "one2many owner"

    name = fields.Char()
    child_ids = fields.One2many("prefetch.child", "parent_id")


class PrefetchChild(models.Model):
    _name = "prefetch.child"
    _module = _MOD
    _description = "one2many line"

    name = fields.Char()
    parent_id = fields.Many2one("prefetch.parent")


def _setup(env):
    parent = env["prefetch.parent"].create({"name": "p"})
    children = env["prefetch.child"].create(
        [{"name": str(i), "parent_id": parent.id} for i in range(5)]
    )
    env.flush_all()
    return parent, children


def test_lines_prefetch_each_other_after_invalidate_all():
    with model_test_env(PrefetchParent, PrefetchChild) as env:
        parent, children = _setup(env)
        lines = parent.child_ids
        env.invalidate_all()
        assert set(lines._prefetch_ids) >= set(children.ids)
        first = next(iter(lines))
        assert set(first._prefetch_ids) >= set(children.ids)


def test_lines_reached_through_an_emptied_parent_prefetch_keep_their_siblings():
    with model_test_env(PrefetchParent, PrefetchChild) as env:
        parent, children = _setup(env)
        env.invalidate_all()
        via_parent = env["prefetch.parent"].browse(parent.id).with_prefetch(())
        lines = via_parent.child_ids
        env.invalidate_all()
        assert set(lines._prefetch_ids) >= set(children.ids)
        backwards = list(reversed(lines._prefetch_ids))
        assert set(backwards) >= set(children.ids)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
