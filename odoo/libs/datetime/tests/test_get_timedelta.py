from datetime import datetime

import pytest
from dateutil.relativedelta import relativedelta

from odoo.libs.datetime.date_utils import get_timedelta

GRANULARITIES = ("hour", "day", "week", "month", "year")


def _switch(qty: int, granularity: str) -> relativedelta:
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
        moment = datetime(2026, 2, 28, 13, 45)
        assert moment + get_timedelta(qty, granularity) == moment + _switch(
            qty, granularity
        )

    def test_builds_exactly_one_relativedelta(self, monkeypatch):
        built = []

        class Counting(relativedelta):
            def __init__(self, *args, **kwargs):
                built.append(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr("odoo.libs.datetime.date_utils.relativedelta", Counting)
        result = get_timedelta(3, "day")
        assert len(built) == 1
        assert result == relativedelta(days=3)

    def test_an_unknown_granularity_raises_a_named_error(self):
        with pytest.raises(ValueError, match="Granularity must be"):
            get_timedelta(1, "fortnight")  # type: ignore[arg-type]
