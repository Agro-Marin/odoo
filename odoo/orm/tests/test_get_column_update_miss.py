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
    memo = fields.Char(company_dependent=True)
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
        with pytest.raises(KeyError):
            field.get_column_update(record)


def test_translate_total_miss_raises_keyerror():
    with model_test_env(Thing) as env:
        record = env["gcu.thing"].create({"name": "a", "name_tr": "hello"})
        field = record._fields["name_tr"]
        env.invalidate_all()
        with pytest.raises(KeyError):
            field.get_column_update(record)


def test_translate_none_value_still_flushes_null():
    with model_test_env(Thing) as env:
        record = env["gcu.thing"].create({"name": "a", "name_tr": "hello"})
        record.name_tr = False
        field = record._fields["name_tr"]
        assert field.get_column_update(record) is None


def test_company_dependent_total_miss_raises_keyerror():
    with model_test_env(Thing) as env:
        record = env["gcu.thing"].create({"name": "a", "memo": "hello"})
        field = record._fields["memo"]
        assert field.company_dependent, "test premise"
        env.invalidate_all()
        with pytest.raises(KeyError):
            field.get_column_update(record)


def test_company_dependent_present_falsy_value_is_not_a_miss():
    with model_test_env(Thing) as env:
        record = env["gcu.thing"].create({"name": "a", "memo": "hello"})
        record.memo = False
        field = record._fields["memo"]
        result = field.get_column_update(record)
        assert result.obj == {env.company.id: None}
