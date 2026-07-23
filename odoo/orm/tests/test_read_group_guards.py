"""Guards around read_group internals (audit fixes).

- ``_read_group_having`` must reject under-arity polish-notation domains with a
  clear ``ValueError`` instead of leaking a raw ``IndexError`` (the method is
  reachable from RPC via ``formatted_read_group(having=...)``).
- The deprecated ``read_group()`` must not crash when ``groupby=[]`` while the
  context carries a dict ``fill_temporal``, and must ignore unknown
  ``fill_temporal`` keys instead of raising ``TypeError`` on ``**``-unpacking.
- The empty-query shortcut of ``_read_group`` must accept a *virtual* groupby
  spec (one with no backing field, resolved by a ``_read_group_groupby``
  override) the same way the non-empty path does, while still rejecting a
  genuinely unknown spec with ``ValueError``.

Tier-2 suite: real ``import odoo``, no database.
"""

import warnings

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env
from odoo.orm.models.mixins.read_group.sql import _ReadGroupSQLMixin
from odoo.tools import SQL

_MOD = "test_read_group_guards"


class _HavingStub(_ReadGroupSQLMixin):
    """Bare instance: ``__count`` leaves never touch model state."""

    __slots__ = ()


class ReadGroupThing(models.Model):
    _name = "read.group.thing"
    _module = _MOD
    _description = "read_group guard model"

    name = fields.Char()
    adate = fields.Date()

    def _read_group_format_result(self, rows_dict, lazy_groupby):
        # The real formatter resolves the user locale via res.lang, which the
        # DB-free tier does not provide; the tests here target the fill_temporal
        # handling that runs BEFORE formatting, so only mimic the final
        # __domain normalization.
        for row in rows_dict:
            row["__domain"] = list(row["__domain"])


class ReadGroupVirtual(models.Model):
    _name = "read.group.virtual"
    _module = _MOD
    _description = "read_group virtual groupby model"

    name = fields.Char()

    def _read_group_groupby(self, alias, groupby_spec, query):
        # A virtual groupby with no backing field, resolved entirely here --
        # the pattern account_followup uses for 'followup_overdue'.
        if groupby_spec == "is_named":
            return SQL(
                "%s IS NOT NULL", self._field_to_sql(self._table, "name", query)
            )
        return super()._read_group_groupby(alias, groupby_spec, query)


@pytest.mark.parametrize(
    "having_domain",
    [
        ["|", ("__count", ">", 1)],  # binary operator, one operand
        ["&"],  # binary operator, no operand
        ["!"],  # unary operator, no operand
        ["&", "|", ("__count", ">", 1)],  # nested underflow
    ],
)
def test_read_group_having_underflow_raises_valueerror(having_domain):
    stub = _HavingStub()
    with pytest.raises(ValueError, match="Invalid having clause"):
        stub._read_group_having(having_domain, None)


def test_read_group_having_valid_forms_still_build():
    stub = _HavingStub()
    assert stub._read_group_having([("__count", ">", 1)], None).code == "COUNT(*) > %s"
    # implicit AND between leftover operands (usual domain semantics)
    assert (
        stub._read_group_having([("__count", ">", 1), ("__count", "<", 5)], None).code
        == "(COUNT(*) > %s AND COUNT(*) < %s)"
    )
    assert (
        stub._read_group_having(["|", ("__count", ">", 1), ("__count", "<", 5)], None).code
        == "(COUNT(*) > %s OR COUNT(*) < %s)"
    )


def test_read_group_empty_groupby_with_dict_fill_temporal():
    """groupby=[] + dict fill_temporal: old guard crashed IndexError."""
    with model_test_env(ReadGroupThing) as env:
        model = env["read.group.thing"].with_context(fill_temporal={})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            rows = model.read_group([], ["__count"], [])
        assert len(rows) == 1
        assert rows[0]["__count"] == 0


def test_read_group_fill_temporal_unknown_keys_ignored():
    """Unknown fill_temporal context keys: old code TypeErrored on **kwargs."""
    with model_test_env(ReadGroupThing) as env:
        model = env["read.group.thing"].with_context(
            fill_temporal={"bogus_key": 1, "fill_from": False}
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            # no data: the empty-query shortcut still runs the fill branch
            rows = model.read_group([], ["__count"], ["adate:month"])
        assert rows == []


def test_read_group_empty_path_accepts_virtual_groupby():
    """Empty-query shortcut must accept a virtual groupby resolved by a
    ``_read_group_groupby`` override (regression: was rejected as
    ``Invalid field`` by the parallel spec validator)."""
    with model_test_env(ReadGroupVirtual) as env:
        model = env["read.group.virtual"]
        # ('id', 'in', []) is a contradiction => empty query => shortcut path.
        rows = model._read_group([("id", "in", [])], ["is_named"], ["__count"])
        assert rows == []


def test_read_group_empty_path_rejects_unknown_groupby():
    """The shortcut must still raise for a genuinely unknown spec, so
    invalid-spec detection does not depend on whether data matched."""
    with model_test_env(ReadGroupVirtual) as env:
        model = env["read.group.virtual"]
        with pytest.raises(ValueError, match="Invalid field 'nope'"):
            model._read_group([("id", "in", [])], ["nope"], ["__count"])
