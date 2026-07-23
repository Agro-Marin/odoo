"""Micro-guards on the base conversion helpers.

* ``Field.convert_to_column`` (base implementation): the ``str(value)``
  fallback is restricted to scalar-ish values — a dict/list/object used to be
  silently stringified into the column (e.g. ``"{'a': 1}"`` into a varchar).
* ``Id.expression_getter("id.origin")``: an empty recordset returns ``False``
  (upstream contract) instead of IndexError-ing on ``record._ids[0]``.
"""

import pytest

from odoo import fields, models
from odoo.orm.fields.base import Field
from odoo.orm.model_test_env import model_test_env

_MOD = "test_field_convert_guards"


class Thing(models.Model):
    _name = "fcg.thing"
    _module = _MOD
    _description = "thing"
    _log_access = False

    name = fields.Char()


def test_base_convert_to_column_scalarish_only():
    with model_test_env(Thing) as env:
        record = env["fcg.thing"].browse()
        field = record._fields["name"]
        # call the BASE implementation explicitly (Char overrides it)
        convert = Field.convert_to_column
        assert convert(field, None, record) is None
        assert convert(field, False, record) is None
        assert convert(field, "s", record) == "s"
        assert convert(field, b"s", record) == "s"
        assert convert(field, 42, record) == "42"
        assert convert(field, 4.5, record) == "4.5"
        with pytest.raises(TypeError):
            convert(field, {"a": 1}, record)
        with pytest.raises(TypeError):
            convert(field, ["a"], record)


def test_id_origin_getter_handles_empty_and_new():
    with model_test_env(Thing) as env:
        Model = env["fcg.thing"]
        getter = Model._fields["id"].expression_getter("id.origin")
        # empty recordset: False, not IndexError
        assert getter(Model.browse()) is False
        record = Model.create({"name": "x"})
        assert getter(record) == record.id
        new_record = Model.new(origin=record)
        assert getter(new_record) == record.id
