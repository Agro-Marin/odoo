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


def test_create_with_recordset_stores_the_reference():
    """``create()`` reaches the column converter, ``write()`` does not.

    ``_build_insert_rows`` hands ``convert_to_column`` the raw *write-format*
    value, so a recordset (``create({'ref': record})``) arrives there intact.
    ``Reference.convert_to_column`` used to delegate straight to the scalar
    ``Field.convert_to_column``, which rejects a non-scalar with
    ``TypeError: Invalid column value`` rather than formatting "model,id".
    """
    with model_test_env(Target, Holder) as env:
        target = env["refw.target"].create({"name": "t"})
        holder = env["refw.holder"].create({"name": "h", "ref": target})
        assert holder.ref == target


def test_create_with_dangling_recordset_is_dropped():
    """Same degradation as the write path: a deleted target stores no value."""
    with model_test_env(Target, Holder) as env:
        holder = env["refw.holder"].create(
            {"name": "h", "ref": env["refw.target"].browse(99999)}
        )
        assert not holder.ref


def test_create_with_string_reference_still_works():
    """The string form is already the column format and must be untouched."""
    with model_test_env(Target, Holder) as env:
        target = env["refw.target"].create({"name": "t"})
        holder = env["refw.holder"].create(
            {"name": "h", "ref": f"refw.target,{target.id}"}
        )
        assert holder.ref == target
