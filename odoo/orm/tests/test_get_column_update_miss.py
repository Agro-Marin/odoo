"""``get_column_update`` must raise ``KeyError`` on a total cache miss in ALL
branches.

The flush loop (``models/mixins/recompute.py``) wraps a ``KeyError`` into a
diagnostic RuntimeError naming record and context.  The context-dependent
branch used to raise ``AssertionError`` (bypassing that handler entirely) and
the ``translate=True`` branch silently returned ``None`` — flushing SQL NULL
over the real value.
"""

import pytest

from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_get_column_update_miss"


class Thing(models.Model):
    _name = "gcu.thing"
    _module = _MOD
    _description = "thing"
    _log_access = False

    name = fields.Char()
    name_tr = fields.Char(translate=True)
    per_uid = fields.Char(compute="_compute_per_uid", store=True)

    @api.depends("name")
    @api.depends_context("uid")
    def _compute_per_uid(self):
        for record in self:
            record.per_uid = (record.name or "") + "!"


def test_fast_path_total_miss_raises_keyerror():
    with model_test_env(Thing) as env:
        record = env["gcu.thing"].create({"name": "a"})
        field = record._fields["name"]
        env.invalidate_all()
        with pytest.raises(KeyError):
            field.get_column_update(record)


def test_context_dependent_total_miss_raises_keyerror():
    with model_test_env(Thing) as env:
        record = env["gcu.thing"].create({"name": "a"})
        field = record._fields["per_uid"]
        assert field._is_context_dependent(env), "test premise"
        env.invalidate_all()
        # used to raise AssertionError, which _flush does not wrap
        with pytest.raises(KeyError):
            field.get_column_update(record)


def test_translate_total_miss_raises_keyerror():
    with model_test_env(Thing) as env:
        record = env["gcu.thing"].create({"name": "a", "name_tr": "hello"})
        field = record._fields["name_tr"]
        env.invalidate_all()
        # used to silently return None (flushing SQL NULL)
        with pytest.raises(KeyError):
            field.get_column_update(record)


def test_translate_none_value_still_flushes_null():
    # A record PRESENT in cache with value None is not a miss: it must keep
    # returning None (SQL NULL), not raise.
    with model_test_env(Thing) as env:
        record = env["gcu.thing"].create({"name": "a", "name_tr": "hello"})
        record.name_tr = False
        field = record._fields["name_tr"]
        assert field.get_column_update(record) is None
