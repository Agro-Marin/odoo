import inspect
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from odoo.libs._vendor.useragents import UserAgentParser
from odoo.tests import TransactionCase, tagged

from odoo.addons.base.models import res_device
from odoo.addons.base.models.ir_autovacuum import is_autovacuum


class DeviceLogCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["res.device.log"].search([]).unlink()

    def _log(self, **vals):
        base = {
            "session_identifier": "sid_rdev_a",
            "platform": "linux",
            "browser": "firefox",
            "ip_address": "10.0.0.1",
            "user_id": self.env.uid,
            "first_activity": "2026-07-01 10:00:00",
            "last_activity": "2026-07-01 10:00:00",
        }
        base.update(vals)
        return self.env["res.device.log"].create(base)

    def _devices(self, session_identifier="sid_rdev_a"):
        self.env.flush_all()
        self.env.invalidate_all()
        return (
            self.env["res.device"]
            .sudo()
            .search([("session_identifier", "=", session_identifier)])
        )


@tagged("post_install", "-at_install")
class TestDeviceLogGC(DeviceLogCase):
    def test_gc_keeps_latest_log_per_device(self):
        DeviceLog = self.env["res.device.log"]

        self._log(last_activity="2026-07-01 10:00:00")
        self._log(last_activity="2026-07-01 11:00:00")
        keep_a = self._log(last_activity="2026-07-01 12:00:00")

        self._log(platform=False, browser=False, last_activity="2026-07-01 10:00:00")
        keep_b = self._log(
            platform=False, browser=False, last_activity="2026-07-01 11:00:00"
        )

        self._log(session_identifier="sid_rdev_c", last_activity="2026-07-01 09:00:00")
        keep_c = self._log(
            session_identifier="sid_rdev_c", last_activity="2026-07-01 09:00:00"
        )

        keep_d = self._log(
            session_identifier="sid_rdev_d",
            ip_address="10.0.0.8",
            last_activity="2020-01-01 00:00:00",
        )

        self.env.flush_all()
        self.assertEqual(DeviceLog._gc_device_log(), (4, False))
        self.env.invalidate_all()

        survivors = DeviceLog.search(
            [("session_identifier", "in", ["sid_rdev_a", "sid_rdev_c", "sid_rdev_d"])],
            order="id",
        )
        self.assertEqual(survivors, keep_a | keep_b | keep_c | keep_d)

    def test_gc_keeps_ip_history_view_shows_latest(self):
        old_ip = self._log(last_activity="2026-07-01 10:00:00")
        new_ip = self._log(ip_address="10.0.0.2", last_activity="2026-07-01 11:00:00")
        self.assertEqual(self._devices().ids, [new_ip.id])
        self.env["res.device.log"]._gc_device_log()
        self.assertEqual(
            self.env["res.device.log"].search(
                [("session_identifier", "=", "sid_rdev_a")]
            ),
            old_ip | new_ip,
            "GC keeps one row per IP for linked_ip_addresses history",
        )

    def test_null_user_rows_dedup_consistently(self):
        old = self._log(user_id=False, last_activity="2026-07-01 10:00:00")
        newest = self._log(user_id=False, last_activity="2026-07-01 11:00:00")
        self.assertEqual(self._devices().ids, [newest.id])
        self.env["res.device.log"]._gc_device_log()
        self.assertEqual(
            self.env["res.device.log"].search(
                [("session_identifier", "=", "sid_rdev_a")]
            ),
            newest,
            f"GC must delete hidden row {old.id}",
        )


class TestDeviceModel(DeviceLogCase):
    def test_autovacuum_belongs_to_the_log_alone(self):
        def vacuums(model):
            return {
                name
                for name, _func in inspect.getmembers(
                    self.env[model].__class__, is_autovacuum
                )
            }

        self.assertEqual(
            vacuums("res.device.log"), {"_gc_device_log", "_update_revoked"}
        )
        self.assertFalse(vacuums("res.device"), "the view would vacuum the log twice")

    def test_mobile_platforms_are_parser_vocabulary(self):
        emitted = {name for _regex, name in UserAgentParser.platforms}
        self.assertLessEqual(res_device._MOBILE_PLATFORMS, emitted)
        self.assertEqual(res_device._device_type("Android"), "mobile")
        self.assertEqual(res_device._device_type("linux"), "computer")
        self.assertEqual(res_device._device_type(None), "computer")

    def test_first_activity_is_the_device_earliest(self):
        self._log(
            first_activity="2026-07-01 08:00:00", last_activity="2026-07-01 09:00:00"
        )
        latest = self._log(
            ip_address="10.0.0.2",
            first_activity="2026-07-01 12:00:00",
            last_activity="2026-07-01 12:00:00",
        )
        device = self._devices()
        self.assertEqual(device.id, latest.id)
        self.assertEqual(device.ip_address, "10.0.0.2")
        self.assertEqual(device.first_activity, datetime(2026, 7, 1, 8, 0))
        self.assertEqual(device.last_activity, datetime(2026, 7, 1, 12, 0))

    def test_linked_ip_addresses_newest_first_and_per_device(self):
        self._log(ip_address="10.0.0.1", last_activity="2026-07-01 10:00:00")
        self._log(ip_address="10.0.0.3", last_activity="2026-07-01 12:00:00")
        self._log(ip_address="10.0.0.2", last_activity="2026-07-01 11:00:00")
        self._log(ip_address="10.0.0.1", last_activity="2026-07-01 09:00:00")
        self._log(browser="chrome", ip_address="10.9.9.9")
        devices = self._devices()
        firefox = devices.filtered(lambda d: d.browser == "firefox")
        chrome = devices.filtered(lambda d: d.browser == "chrome")
        self.assertEqual(firefox.linked_ip_addresses, "10.0.0.3\n10.0.0.2\n10.0.0.1")
        self.assertEqual(chrome.linked_ip_addresses, "10.9.9.9")

    def test_is_current_without_request(self):
        self._log()
        self.assertFalse(self._devices().is_current)


class TestUpdateRevoked(DeviceLogCase):
    def _sweep(self, live, budget=float("inf")):
        store = SimpleNamespace(
            get_missing_session_identifiers=lambda identifiers: (
                set(identifiers) - set(live)
            )
        )
        with (
            patch.object(res_device, "root", SimpleNamespace(session_store=store)),
            patch.object(
                type(self.env["ir.cron"]), "_commit_progress", lambda *a, **k: budget
            ),
        ):
            result = self.env["res.device.log"].sudo()._update_revoked()
        self.env.invalidate_all()
        return result

    def _revoked(self, session_identifier):
        return set(
            self.env["res.device.log"]
            .search([("session_identifier", "=", session_identifier)])
            .mapped("revoked")
        )

    def test_missing_family_is_revoked_whole(self):
        self._log(session_identifier="sid_rdev_gone", last_activity="2020-01-01")
        self._log(
            session_identifier="sid_rdev_gone",
            ip_address="10.0.0.2",
            last_activity=datetime.now(),
        )
        self._log(session_identifier="sid_rdev_live", last_activity="2020-01-01")
        self._log(session_identifier="sid_rdev_recent", last_activity=datetime.now())
        self.env.flush_all()

        revoked, remaining = self._sweep(live={"sid_rdev_live"})

        self.assertEqual((revoked, remaining), (2, False))
        self.assertEqual(self._revoked("sid_rdev_gone"), {True})
        self.assertEqual(self._revoked("sid_rdev_live"), {False})
        self.assertEqual(
            self._revoked("sid_rdev_recent"),
            {False},
            "a family with no inactive row is not asked about",
        )
        self.assertFalse(self._devices("sid_rdev_gone"))

    def test_batches_cover_every_candidate(self):
        families = [f"sid_rdev_{n}" for n in range(7)]
        for family in families:
            self._log(session_identifier=family, last_activity="2020-01-01")
        self.env.flush_all()

        with patch.object(res_device, "_REVOKE_SWEEP_BATCH", 2):
            revoked, remaining = self._sweep(live={"sid_rdev_1", "sid_rdev_4"})

        self.assertEqual((revoked, remaining), (5, False))
        for family in families:
            self.assertEqual(
                self._revoked(family), {family not in {"sid_rdev_1", "sid_rdev_4"}}
            )

    def test_stops_when_the_time_budget_is_spent(self):
        for family in ("sid_rdev_x", "sid_rdev_y"):
            self._log(session_identifier=family, last_activity="2020-01-01")
        self.env.flush_all()

        with patch.object(res_device, "_REVOKE_SWEEP_BATCH", 1):
            self.assertEqual(self._sweep(live=(), budget=0), (1, True))
