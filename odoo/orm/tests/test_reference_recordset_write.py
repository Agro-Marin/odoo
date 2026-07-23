"""Recordset writes to a Reference field get the same existence check and
transaction memo as string writes.

Regression: the recordset branch of ``Reference.convert_to_cache`` skipped
both, so writing a recordset pointing at a deleted id cached a dangling
reference that string writes would have dropped.
"""

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_reference_recordset_write"


class Target(models.Model):
    _name = "refw.target"
    _module = _MOD
    _description = "target"
    _log_access = False

    name = fields.Char()


class Holder(models.Model):
    _name = "refw.holder"
    _module = _MOD
    _description = "holder"
    _log_access = False

    name = fields.Char()
    ref = fields.Reference([("refw.target", "Target")])


def test_dangling_recordset_write_is_dropped():
    with model_test_env(Target, Holder) as env:
        holder = env["refw.holder"].create({"name": "h"})
        # write() passes the raw recordset to convert_to_cache(validate=True)
        holder.write({"ref": env["refw.target"].browse(99999)})
        # same degradation as the string branch: dangling target -> no value
        assert not holder.ref


def test_existing_recordset_write_verifies_and_memoizes():
    with model_test_env(Target, Holder) as env:
        target = env["refw.target"].create({"name": "t"})
        holder = env["refw.holder"].create({"name": "h"})
        holder.write({"ref": target})
        assert holder.ref == target
        field = holder._fields["ref"]
        assert ("refw.target", target.id) in field._verified_pairs(env)
