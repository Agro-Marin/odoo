"""Regression: ``filtered("m2o_field")`` must not drop new records.

A many2one caches the comodel id — for an unsaved record that is a ``NewId``,
whose ``__bool__`` is False while the field VALUE is a truthy one-record
recordset.  The raw-truthiness cache scan therefore disagreed with the
callable form ``filtered(lambda r: r.parent_id)``.  Relational fields are now
excluded from the raw scan by the shared eligibility predicate
(``models/mixins/_cache_scan.can_scan_truthy``) and resolve per record via
``__get__``.  Tier-2 suite: real ``import odoo``, no database.
"""

import sys

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_filtered_relational_newid"


class ScanNode(models.Model):
    _name = "scan.node"
    _module = _MOD
    _description = "self-referencing many2one for the filtered() fast path"

    name = fields.Char()
    parent_id = fields.Many2one("scan.node")


def test_filtered_m2o_keeps_new_records():
    with model_test_env(ScanNode) as env:
        model = env["scan.node"]
        parent = model.new({})
        child = model.new({"parent_id": parent})
        orphan = model.new({})
        assert child.parent_id  # the field VALUE is a truthy recordset
        recs = child + orphan
        by_name = recs.filtered("parent_id")
        by_func = recs.filtered(lambda r: r.parent_id)
        assert by_name._ids == by_func._ids == child._ids


def test_filtered_m2o_mixed_real_and_new():
    with model_test_env(ScanNode) as env:
        model = env["scan.node"]
        real_parent = model.create({"name": "p"})
        real_child = model.create({"name": "r", "parent_id": real_parent.id})
        real_orphan = model.create({"name": "o"})
        new_child = model.new({"parent_id": model.new({})})
        recs = real_child + real_orphan + new_child
        by_name = recs.filtered("parent_id")
        by_func = recs.filtered(lambda r: r.parent_id)
        assert by_name._ids == by_func._ids == (real_child.id, new_child.id)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
