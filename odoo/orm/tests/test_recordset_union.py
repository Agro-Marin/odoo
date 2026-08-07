import sys

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_recordset_union"


class UnionThing(models.Model):
    _name = "union.thing"
    _module = _MOD
    _description = "union dedup model"

    name = fields.Char()


def test_union_dedups_with_either_operand_empty():
    with model_test_env(UnionThing) as env:
        model = env["union.thing"]
        rec = model.browse(1)
        empty = model.browse()
        dup = rec + rec
        assert dup._ids == (1, 1)
        assert (dup | empty)._ids == (1,)
        assert (empty | dup)._ids == (1,)
        assert dup.union()._ids == (1,)
        assert dup.union(empty, empty)._ids == (1,)


def test_union_keeps_identity_for_unique_self_with_empty_arg():
    with model_test_env(UnionThing) as env:
        model = env["union.thing"]
        rec = model.browse((1, 2))
        empty = model.browse()
        assert (rec | empty) is rec


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
