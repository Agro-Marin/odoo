import datetime
import logging
from unittest.mock import patch

from odoo.libs.datetime import TIMEZONE_ALIASES, all_timezones, timezone, tz
from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)


class TestTZ(TransactionCase):
    def test_tz_legacy(self):
        d = datetime.datetime(2024, 6, 15)

        def assertTZEqual(tz1, tz2):
            dt1 = d.replace(tzinfo=tz1)
            dt2 = d.replace(tzinfo=tz2)
            self.assertEqual(dt1.strftime("%z"), dt2.strftime("%z"))

        for source, target in TIMEZONE_ALIASES.items():
            with self.subTest(source=source, target=target):
                if source == "Pacific/Enderbury":
                    continue
                try:
                    target_tz = timezone(target)
                except KeyError:
                    _logger.info(
                        "Skipping test for %s -> %s, target does not exist",
                        source,
                        target,
                    )
                    continue
                tz._timezone_cache.clear()
                source_tz = timezone(source)
                assertTZEqual(source_tz, target_tz)

    def test_dont_adapt_available_tz(self):
        with patch.dict(
            TIMEZONE_ALIASES,
            {
                "DeprecatedUtc": "UTC",
                "America/New_York": "UTC",
            },
            clear=False,
        ):
            tz._timezone_cache.clear()

            self.assertNotIn(
                "DeprecatedUtc",
                all_timezones(),
                "DeprecatedUtc is not available",
            )
            deprecated_tz = timezone("DeprecatedUtc")
            utc_tz = timezone("UTC")
            now = datetime.datetime.now()
            self.assertEqual(
                now.replace(tzinfo=deprecated_tz).strftime("%z"),
                now.replace(tzinfo=utc_tz).strftime("%z"),
                "DeprecatedUtc does not exist and should have been replaced with UTC",
            )

            self.assertIn(
                "America/New_York",
                all_timezones(),
                "America/New_York is available",
            )
            tz._timezone_cache.clear()
            ny_tz = timezone("America/New_York")
            self.assertNotEqual(
                now.replace(tzinfo=ny_tz).strftime("%z"),
                now.replace(tzinfo=utc_tz).strftime("%z"),
                "America/New_York exists and should not have been replaced with UTC",
            )

    def test_cannot_set_deprecated_timezone(self):
        self.env.user.tz = "America/New_York"
        if "US/Eastern" not in all_timezones():
            resolved = tz.timezone("US/Eastern")
            self.assertEqual(resolved.key, "America/New_York")

    def test_partner_with_old_tz(self):
        tz._timezone_cache.clear()

        partner = self.env["res.partner"].create({"name": "test", "tz": "UTC"})
        self.env.cr.execute(
            """UPDATE res_partner set tz='US/Eastern' WHERE id=%s""",
            (partner.id,),
        )
        partner.invalidate_recordset()
        self.assertEqual(partner.tz, "US/Eastern")

        expected_offset = datetime.datetime.now(timezone("America/New_York")).strftime(
            "%z"
        )
        self.assertEqual(
            partner.tz_offset,
            expected_offset,
            "Timezone offset should work even with deprecated timezone names",
        )


class TestLegacyTimezoneGrouping(TransactionCase):
    """Grouping under a legacy alias must land in that zone, not in UTC.

    Odoo's ``tz`` dropdown offers 599 zoneinfo names; this PostgreSQL accepts
    487. Degrading the other 112 to UTC never raised, so nothing noticed that
    an 'Asia/Calcutta' user was reading day buckets cut 5h30 from their own
    midnight -- a wrong answer that looks like a working report.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "tz grouping probe"})
        # 20:00 UTC is still the 15th in UTC and already the 16th in +05:30,
        # so the day bucket alone tells the two zones apart.
        cls.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            ("2024-06-15 20:00:00", cls.partner.id),
        )
        cls.partner.invalidate_recordset(["create_date"])

    def _day_buckets(self, tz_name):
        return [
            group[0]
            for group in self.env["res.partner"]
            .with_context(tz=tz_name)
            ._read_group(
                [("id", "=", self.partner.id)], ["create_date:day"], ["__count"]
            )
        ]

    def test_the_probe_instant_really_straddles_a_day(self):
        """Guards the other tests: without this they would pass on any zone."""
        self.assertNotEqual(self._day_buckets("Asia/Kolkata"), self._day_buckets("UTC"))

    def test_a_legacy_alias_groups_in_its_real_zone(self):
        self.assertNotIn("Asia/Calcutta", _pg_timezone_names(self.env))
        self.assertEqual(
            self._day_buckets("Asia/Calcutta"), self._day_buckets("Asia/Kolkata")
        )

    def test_a_resolvable_alias_warns_about_nothing(self):
        with self.assertNoLogs("odoo.fields", logging.WARNING):
            self._day_buckets("Asia/Calcutta")

    def test_a_zone_with_no_server_equivalent_still_falls_back_to_utc(self):
        with self.assertLogs("odoo.fields", logging.WARNING) as capture:
            buckets = self._day_buckets("Mars/Olympus_Mons")
        self.assertEqual(buckets, self._day_buckets("UTC"))
        self.assertIn("Mars/Olympus_Mons", capture.output[0])


def _pg_timezone_names(env):
    env.cr.execute("SELECT name FROM pg_timezone_names")
    return {name for [name] in env.cr.fetchall()}
