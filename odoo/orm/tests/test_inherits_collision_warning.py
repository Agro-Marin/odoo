"""``_add_inherited_fields`` collision warnings must skip non-inherited names.

Tier-2 suite (real ``import odoo``, no database — run as ``pytest
odoo/orm/tests``).  Regression guard: the both-parents collision warning in
:func:`odoo.orm.registration._add_inherited_fields` used to fire *before*
filtering out names already present in ``model_cls._fields``, so every model
with two (or more) ``_inherits`` parents logged exactly six spurious warnings
for the magic fields (id, display_name, create_uid/date, write_uid/date) that
every parent carries.  Only names that are actually inherited may collide;
genuine collisions must still warn.
"""

import logging

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_inherits_collision"

MAGIC_FIELDS = (
    "id",
    "display_name",
    "create_uid",
    "create_date",
    "write_uid",
    "write_date",
)


class CollParentA(models.Model):
    _name = "hcoll.parent_a"
    _module = _MOD
    _description = "Collision Parent A"

    shared = fields.Char()
    power = fields.Integer()


class CollParentB(models.Model):
    _name = "hcoll.parent_b"
    _module = _MOD
    _description = "Collision Parent B"

    shared = fields.Char()
    wings = fields.Integer()


class CollChild(models.Model):
    _name = "hcoll.child"
    _module = _MOD
    _description = "Collision Child"
    _inherits = {
        "hcoll.parent_a": "parent_a_id",
        "hcoll.parent_b": "parent_b_id",
    }

    parent_a_id = fields.Many2one(
        "hcoll.parent_a", required=True, ondelete="cascade"
    )
    parent_b_id = fields.Many2one(
        "hcoll.parent_b", required=True, ondelete="cascade"
    )


def test_two_inherits_parents_warn_only_on_genuine_collision(caplog):
    with caplog.at_level(logging.WARNING, logger="odoo.registry"):
        with model_test_env(CollParentA, CollParentB, CollChild) as env:
            child = env["hcoll.child"]
            parent_a = env["hcoll.parent_a"]
            parent_b = env["hcoll.parent_b"]

            # Precondition making the "no magic warnings" assertion meaningful:
            # the magic fields exist on both parents AND on the child itself,
            # which is exactly the shape that used to produce 6 spurious
            # warnings per model with 2+ _inherits parents.
            for name in MAGIC_FIELDS:
                assert name in parent_a._fields
                assert name in parent_b._fields
                assert name in child._fields

            # The genuine collision is still inherited (last parent wins).
            assert child._fields["shared"].related == "parent_b_id.shared"
            # Non-colliding parent fields are inherited as usual.
            assert child._fields["power"].related == "parent_a_id.power"
            assert child._fields["wings"].related == "parent_b_id.wings"

    collision_msgs = [
        record.getMessage()
        for record in caplog.records
        if "inherits field" in record.getMessage()
    ]

    # zero warnings for the magic fields...
    for name in MAGIC_FIELDS:
        offenders = [msg for msg in collision_msgs if f"{name!r}" in msg]
        assert not offenders, f"spurious magic-field warning(s): {offenders}"

    # ...but exactly one for the genuine duplicated parent field
    shared_msgs = [msg for msg in collision_msgs if "'shared'" in msg]
    assert len(shared_msgs) == 1, collision_msgs
    assert "'hcoll.parent_a'" in shared_msgs[0]
    assert "'hcoll.parent_b'" in shared_msgs[0]
    assert collision_msgs == shared_msgs, collision_msgs
