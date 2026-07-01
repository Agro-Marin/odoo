"""Regression: ``union`` / ``|`` must dedup regardless of which operand is empty.

Recordset ids may legally contain duplicates (from ``concat`` / ``+``). ``union``
documents first-occurrence-order set semantics, and the general path dedups via
``OrderedSet``. The single-empty-operand fast paths used to return their operand
raw, so ``(rec + rec) | empty`` kept the duplicate while ``(rec + rec) | other``
did not. Tier-2 suite: real ``import odoo``, no database.
"""

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
        # every empty-operand form must dedup like the general path
        assert (dup | empty)._ids == (1,)
        assert (empty | dup)._ids == (1,)
        assert dup.union()._ids == (1,)
        assert dup.union(empty, empty)._ids == (1,)


def test_union_keeps_identity_for_unique_self_with_empty_arg():
    with model_test_env(UnionThing) as env:
        model = env["union.thing"]
        rec = model.browse((1, 2))
        empty = model.browse()
        # unique self | empty: fast path preserves object identity (no alloc)
        assert (rec | empty) is rec


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
