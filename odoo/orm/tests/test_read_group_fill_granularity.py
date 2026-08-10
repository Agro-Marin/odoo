import datetime

import pytest

from odoo import fields, models
from odoo.orm.constants import (
    READ_GROUP_ALL_TIME_GRANULARITY,
    READ_GROUP_NUMBER_GRANULARITY,
    READ_GROUP_TIME_GRANULARITY,
)
from odoo.orm.model_test_env import model_test_env

_MOD = "test_read_group_fill_granularity"


class FillGranularityThing(models.Model):
    _name = "fill.granularity.thing"
    _module = _MOD
    _description = "read_group fill_temporal granularity model"

    name = fields.Char()
    adate = fields.Date()


def test_number_granularities_are_accepted_but_not_fillable():
    not_fillable = set(READ_GROUP_ALL_TIME_GRANULARITY) - set(
        READ_GROUP_TIME_GRANULARITY
    )
    assert not_fillable == set(READ_GROUP_NUMBER_GRANULARITY)
    assert "day_of_week" in not_fillable


# `week` and `hour` reach env["res.lang"] (week_start / locale formatting), which
# the DB-free model_test_env does not register. That locale dependency is a
# separate, known Layer-1/2 coupling; it is not what this regression pins.
_LOCALE_DEPENDENT = frozenset({"week", "hour"})


@pytest.mark.parametrize(
    "granularity", sorted(set(READ_GROUP_ALL_TIME_GRANULARITY) - _LOCALE_DEPENDENT)
)
def test_fill_temporal_never_raises_on_an_accepted_granularity(granularity):
    with model_test_env(FillGranularityThing) as env:
        model = env["fill.granularity.thing"].with_context(fill_temporal=True)
        group = f"adate:{granularity}"
        rows = [{group: datetime.date(2026, 8, 7), "__count": 1}]
        result = model._read_group_fill_temporal(rows, [group], {})
        assert isinstance(result, list)


def test_non_fillable_granularity_passes_rows_through_unchanged():
    with model_test_env(FillGranularityThing) as env:
        model = env["fill.granularity.thing"].with_context(fill_temporal=True)
        group = "adate:day_of_week"
        rows = [{group: 5.0, "__count": 2}]
        assert model._read_group_fill_temporal(rows, [group], {}) == rows
