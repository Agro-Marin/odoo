import functools

import pytest

from odoo import api, fields, models
from odoo.orm.fields.base import determine
from odoo.orm.model_test_env import model_test_env

_MOD = "test_determine_dispatch"


def _inverse_generic(self, offset):
    for record in self:
        record.qty = len(record.label or "") + offset


class DetermineWidget(models.Model):
    _name = "determine.widget"
    _module = _MOD
    _description = "Determine Widget"

    qty = fields.Integer()
    label = fields.Char(compute="_compute_label", inverse="_inverse_label", store=True)

    @api.depends("qty")
    def _compute_label(self):
        for record in self:
            record.label = "x" * record.qty

    _inverse_label = functools.partialmethod(_inverse_generic, offset=1)


def test_a_partialmethod_is_a_usable_inverse():
    with model_test_env(DetermineWidget) as env:
        record = env["determine.widget"].create([{"qty": 2}])
        record.write({"label": "abcd"})
        assert record.qty == 5


def test_both_needle_shapes_reject_a_dunder_the_same_way():
    with model_test_env(DetermineWidget) as env:
        model = env["determine.widget"]
        with pytest.raises(TypeError, match="dunder"):
            determine("__len__", model)
        with pytest.raises(TypeError, match="dunder"):
            determine(type(model).__len__, model)


def test_a_needle_that_is_neither_says_so():
    with model_test_env(DetermineWidget) as env:
        with pytest.raises(TypeError, match="callable or method name"):
            determine(None, env["determine.widget"])


def test_a_non_recordset_subject_says_so():
    with pytest.raises(TypeError, match="subject recordset"):
        determine("anything", object())  # type: ignore[arg-type]
