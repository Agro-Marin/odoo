from datetime import UTC, date, datetime, timedelta
from datetime import timezone as fixed_offset
from zoneinfo import ZoneInfo

from addons.mail.tools.activity_calendar import (
    ANCHOR_MINUTES,
    days_by_timezone,
    days_elsewhere,
    state_for,
    today_by_tz,
    today_in_tz,
    tz_anchor,
)
from odoo.libs.datetime import all_timezones


class TestStateFor:
    def test_the_three_states(self):
        today = date(2026, 8, 19)
        assert state_for(today, today) == "today"
        assert state_for(today - timedelta(days=1), today) == "overdue"
        assert state_for(today + timedelta(days=1), today) == "planned"

    def test_a_year_either_side_stays_on_the_right_side(self):
        today = date(2026, 8, 19)
        for offset in (1, 2, 30, 365, 4000):
            assert state_for(today - timedelta(days=offset), today) == "overdue"
            assert state_for(today + timedelta(days=offset), today) == "planned"


class TestTodayInTz:
    def test_unknown_and_unset_zones_fall_back_to_utc(self):
        moment = datetime(2026, 8, 19, 23, 30, tzinfo=UTC)
        assert today_in_tz(False, moment) == date(2026, 8, 19)
        assert today_in_tz("Not/AZone", moment) == date(2026, 8, 19)
        assert today_in_tz("", moment) == date(2026, 8, 19)

    def test_two_zones_can_disagree_about_the_date(self):
        moment = datetime(2026, 8, 19, 23, 30, tzinfo=UTC)
        assert today_in_tz("Pacific/Auckland", moment) == date(2026, 8, 20)
        assert today_in_tz("Pacific/Honolulu", moment) == date(2026, 8, 19)


class TestTodayByTz:
    def test_it_agrees_with_today_in_tz_zone_by_zone(self):
        moment = datetime(2026, 8, 19, 23, 30, tzinfo=UTC)
        zones = ["Pacific/Auckland", "Pacific/Honolulu", "Europe/Madrid", False]
        by_tz = today_by_tz(zones, moment)
        assert by_tz == {tz: today_in_tz(tz, moment) for tz in zones}

    def test_one_instant_serves_every_zone(self):
        moment = datetime(2026, 8, 19, 23, 59, 59, tzinfo=UTC)
        first = today_by_tz(all_timezones(), moment)
        second = today_by_tz(all_timezones(), moment)
        assert first == second
        assert len(set(first.values())) <= 3


class TestDaysElsewhere:
    def test_the_fallback_day_is_excluded(self):
        moment = datetime(2026, 8, 19, 23, 30, tzinfo=UTC)
        fallback = today_in_tz(False, moment)
        assert all(day != fallback for day, _names in days_elsewhere(moment))

    def test_every_zone_is_named_exactly_once_or_falls_back(self):
        moment = datetime(2026, 8, 19, 23, 30, tzinfo=UTC)
        named = [name for _day, names in days_elsewhere(moment) for name in names]
        assert len(named) == len(set(named)), "a zone appears in two day groups"
        by_tz = today_by_tz(all_timezones(), moment)
        fallback = today_in_tz(False, moment)
        for day, names in days_elsewhere(moment):
            for name in names:
                assert by_tz[name] == day
        for name in set(all_timezones()) - set(named):
            assert by_tz[name] == fallback


class TestAnchorInvariant:
    def _disagreements(self, moment):
        groups = days_by_timezone(tz_anchor(moment))
        day_of = {name: day for day, names in groups for name in names}
        exact = today_by_tz(all_timezones(), moment)
        return [name for name, day in day_of.items() if day != exact[name]]

    _WITHIN_WINDOW = (0, 1, ANCHOR_MINUTES * 30, ANCHOR_MINUTES * 60 - 1)

    def _windows(self, start, days):
        for quarter in range(days * 24 * 60 // ANCHOR_MINUTES):
            boundary = start + timedelta(minutes=quarter * ANCHOR_MINUTES)
            for seconds in self._WITHIN_WINDOW:
                yield boundary + timedelta(seconds=seconds)

    def test_every_offset_is_a_whole_multiple_of_the_quantum(self):
        moment = datetime(2026, 8, 19, tzinfo=UTC)
        offsets = set()
        for tz_name in all_timezones():
            zone = ZoneInfo(tz_name)
            for hours in range(0, 366 * 24, 12):
                local = (moment + timedelta(hours=hours)).astimezone(zone)
                offsets.add(int(local.utcoffset().total_seconds()) // 60)
        assert offsets, "no offsets sampled"
        assert not [o for o in offsets if o % ANCHOR_MINUTES]

    def test_the_anchor_never_straddles_a_local_midnight(self):
        for moment in self._windows(datetime(2026, 8, 19, tzinfo=UTC), days=1):
            assert not self._disagreements(moment), moment.isoformat()

    def test_it_holds_across_dst_transitions_and_new_year(self):
        windows = [
            datetime(2026, 3, 7, tzinfo=UTC),
            datetime(2026, 3, 28, tzinfo=UTC),
            datetime(2026, 10, 24, tzinfo=UTC),
            datetime(2026, 11, 1, tzinfo=UTC),
            datetime(2025, 12, 31, tzinfo=UTC),
        ]
        for window in windows:
            for moment in self._windows(window, days=3):
                assert not self._disagreements(moment), moment.isoformat()

    def test_the_quantum_is_what_makes_it_hold(self):
        rogue = fixed_offset(timedelta(minutes=ANCHOR_MINUTES - 5))
        base = datetime(2026, 8, 19, tzinfo=UTC)
        broken = [
            moment
            for minutes in range(24 * 60)
            if (moment := base + timedelta(minutes=minutes))
            and tz_anchor(moment).astimezone(rogue).date()
            != moment.astimezone(rogue).date()
        ]
        assert broken, "a non-multiple offset must be able to straddle the anchor"


class TestDaysByTimezone:
    def test_at_most_three_days_exist_at_once(self):
        base = datetime(2026, 8, 19, tzinfo=UTC)
        for minutes in range(0, 24 * 60, 15):
            groups = days_by_timezone(tz_anchor(base + timedelta(minutes=minutes)))
            assert 1 <= len(groups) <= 3

    def test_it_partitions_every_known_zone(self):
        groups = days_by_timezone(tz_anchor(datetime(2026, 8, 19, 12, tzinfo=UTC)))
        named = [name for _day, names in groups for name in names]
        assert sorted(named) == sorted(all_timezones())
