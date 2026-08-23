from datetime import datetime

import pytest
from dateutil.relativedelta import relativedelta

from odoo.libs.datetime.date_utils import get_timedelta

GRANULARITIES = ("hour", "day", "week", "month", "year")


def _switch(qty: int, granularity: str) -> relativedelta:
    """The mapping this function used to spell as a dict of built objects.

    Written out here rather than derived from the new code, so the equivalence
    is checked against the shape that was replaced.
    """
    return {
        "hour": relativedelta(hours=qty),
        "day": relativedelta(days=qty),
        "week": relativedelta(weeks=qty),
        "month": relativedelta(months=qty),
        "year": relativedelta(years=qty),
    }[granularity]


class TestGetTimedelta:
    @pytest.mark.parametrize("granularity", GRANULARITIES)
    @pytest.mark.parametrize("qty", [-50, -1, 0, 1, 7, 400])
    def test_matches_the_mapping_it_replaced(self, qty, granularity):
        assert get_timedelta(qty, granularity) == _switch(qty, granularity)

    @pytest.mark.parametrize("granularity", GRANULARITIES)
    @pytest.mark.parametrize("qty", [-13, 0, 1, 7, 400])
    def test_matches_when_applied_to_a_datetime(self, qty, granularity):
        # relativedelta equality is not the same question as "shifts a date the
        # same way": month and year arithmetic clamps.  Check both.
        moment = datetime(2026, 2, 28, 13, 45)
        assert moment + get_timedelta(qty, granularity) == moment + _switch(
            qty, granularity
        )

    def test_builds_exactly_one_relativedelta(self, monkeypatch):
        # The dict of built values constructed all five per call and returned
        # one; that is the whole reason this function was rewritten.
        #
        # Patched by dotted string rather than by importing the leaf module:
        # `from odoo.libs.datetime import date_utils` adds an entry to the
        # accidental submodule surface that
        # `test_leaf_imports_through_accidental_surface_are_pinned` counts.
        built = []

        class Counting(relativedelta):
            def __init__(self, *args, **kwargs):
                built.append(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr("odoo.libs.datetime.date_utils.relativedelta", Counting)
        get_timedelta(3, "day")
        assert built == [{"days": 3}]

    def test_an_unknown_granularity_raises_a_named_error(self):
        # A bare KeyError('fortnight') names neither the argument nor the
        # allowed set; start_of and end_of raise ValueError for the same slip.
        with pytest.raises(ValueError, match="Granularity must be"):
            get_timedelta(1, "fortnight")
