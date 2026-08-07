import warnings

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env
from odoo.orm.models.mixins.read_group.sql import _ReadGroupSQLMixin
from odoo.tools import SQL

_MOD = "test_read_group_guards"


class _HavingStub(_ReadGroupSQLMixin):
    __slots__ = ()


class ReadGroupThing(models.Model):
    _name = "read.group.thing"
    _module = _MOD
    _description = "read_group guard model"

    name = fields.Char()
    adate = fields.Date()

    def _read_group_format_result(self, rows_dict, lazy_groupby):
        for row in rows_dict:
            row["__domain"] = list(row["__domain"])


class ReadGroupVirtual(models.Model):
    _name = "read.group.virtual"
    _module = _MOD
    _description = "read_group virtual groupby model"

    name = fields.Char()

    def _read_group_groupby(self, alias, groupby_spec, query):
        if groupby_spec == "is_named":
            return SQL("%s IS NOT NULL", self._field_to_sql(self._table, "name", query))
        return super()._read_group_groupby(alias, groupby_spec, query)


@pytest.mark.parametrize(
    "having_domain",
    [
        ["|", ("__count", ">", 1)],
        ["&"],
        ["!"],
        ["&", "|", ("__count", ">", 1)],
    ],
)
def test_read_group_having_underflow_raises_valueerror(having_domain):
    stub = _HavingStub()
    with pytest.raises(ValueError, match="Invalid having clause"):
        stub._read_group_having(having_domain, None)


def test_read_group_having_valid_forms_still_build():
    stub = _HavingStub()
    assert stub._read_group_having([("__count", ">", 1)], None).code == "COUNT(*) > %s"
    assert (
        stub._read_group_having([("__count", ">", 1), ("__count", "<", 5)], None).code
        == "(COUNT(*) > %s AND COUNT(*) < %s)"
    )
    assert (
        stub._read_group_having(
            ["|", ("__count", ">", 1), ("__count", "<", 5)], None
        ).code
        == "(COUNT(*) > %s OR COUNT(*) < %s)"
    )


def test_read_group_empty_groupby_with_dict_fill_temporal():
    with model_test_env(ReadGroupThing) as env:
        model = env["read.group.thing"].with_context(fill_temporal={})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            rows = model.read_group([], ["__count"], [])
        assert len(rows) == 1
        assert rows[0]["__count"] == 0


def test_read_group_fill_temporal_unknown_keys_ignored():
    with model_test_env(ReadGroupThing) as env:
        model = env["read.group.thing"].with_context(
            fill_temporal={"bogus_key": 1, "fill_from": False}
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            rows = model.read_group([], ["__count"], ["adate:month"])
        assert rows == []


def test_read_group_empty_path_accepts_virtual_groupby():
    with model_test_env(ReadGroupVirtual) as env:
        model = env["read.group.virtual"]
        rows = model._read_group([("id", "in", [])], ["is_named"], ["__count"])
        assert rows == []


def test_read_group_empty_path_rejects_unknown_groupby():
    with model_test_env(ReadGroupVirtual) as env:
        model = env["read.group.virtual"]
        with pytest.raises(ValueError, match="Invalid field 'nope'"):
            model._read_group([("id", "in", [])], ["nope"], ["__count"])
