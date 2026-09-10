from datetime import datetime

import pytest
from dateutil.relativedelta import relativedelta

from odoo.libs.datetime.date_utils import (
    TIME_UNIT_SELECTION,
    get_timedelta,
    time_unit_selection,
)

GRANULARITIES = ("minute", "hour", "day", "week", "month", "year")


def _switch(qty: int, granularity: str) -> relativedelta:
    return {
        "minute": relativedelta(minutes=qty),
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


class TestTimeUnitSelection:
    def test_every_offered_value_is_one_get_timedelta_accepts(self):
        """The invariant the selection exists for.

        A field offering a value ``get_timedelta`` rejects stores a latent
        ValueError rather than a wrong answer, and that is precisely how the
        eight hand-written spellings this replaced went wrong.
        """
        for value, _label in TIME_UNIT_SELECTION:
            assert get_timedelta(1, value) is not None

    def test_it_is_ordered_shortest_to_longest(self):
        assert [value for value, _ in TIME_UNIT_SELECTION] == [
            "minute",
            "hour",
            "day",
            "week",
            "month",
            "year",
        ]

    def test_a_subset_keeps_the_canonical_order(self):
        assert time_unit_selection("year", "day", "month") == [
            ("day", "Days"),
            ("month", "Months"),
            ("year", "Years"),
        ]

    def test_the_empty_subset_is_empty(self):
        assert time_unit_selection() == []

    @pytest.mark.parametrize("spelling", ["days", "weeks", "monthly", "quarter", ""])
    def test_a_non_unit_is_refused_at_definition_time(self, spelling):
        """Refused where the field is declared, not where a value is stored."""
        with pytest.raises(ValueError, match="Not time units"):
            time_unit_selection(spelling)
