"""Regression test for ``registration._add_manual_models``'s registry cleanup.

Tier-2 suite (real ``import odoo``, no database — run as ``pytest
odoo/orm/tests``).  ``_add_manual_models`` first *removes* every custom model
from the registry so the fresh definitions from ``ir_model`` re-register from
scratch.  The cleanup discarded the removed model's name from its parents'
``_inherit_children`` but never from ``_inherits_children`` (populated by
``_init_model_class_attributes`` for delegation parents), so a delegating
custom model left its stale name behind across successive registry setups —
e.g. ``Registry.descendants(..., "_inherits")`` kept reporting a model that no
longer exists.

Exercised through the DB-free harness: the ``ir_model`` scan is fixture-backed
(no manual rows), leaving only the cleanup half of the function to observe.
"""

from odoo import fields, models
from odoo.orm import registration
from odoo.orm.model_test_env import model_test_env

_MOD = "test_manual_model_cleanup"

# the raw SQL _add_manual_models runs to find manual models; fixture-backed
_IR_MODEL_QUERY = (
    "SELECT *, name->>'en_US' AS name FROM ir_model WHERE state = 'manual'"
)


class CParent(models.Model):
    _name = "c.parent"
    _module = _MOD
    _description = "Cleanup Parent"

    name = fields.Char()


class CChild(models.Model):
    # delegating ("_inherits") AND custom: the shape whose cleanup was broken
    _name = "c.child"
    _module = _MOD
    _description = "Cleanup Child (custom, delegating)"
    _custom = True
    _inherits = {"c.parent": "parent_id"}

    parent_id = fields.Many2one(
        "c.parent", required=True, ondelete="cascade", delegate=True
    )
    note = fields.Char()


def test_cleanup_discards_from_inherits_children():
    with model_test_env(CParent, CChild, fixtures={_IR_MODEL_QUERY: []}) as env:
        parent_cls = env.registry["c.parent"]
        # registration populated the delegation link
        assert "c.child" in parent_cls._inherits_children

        registration._add_manual_models(env)

        # the custom model is gone from the registry...
        assert "c.child" not in env.registry
        # ...and from BOTH parent link sets — _inherits_children was the leak
        assert "c.child" not in parent_cls._inherit_children
        assert "c.child" not in parent_cls._inherits_children
