import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import odoo.http
from odoo.libs._vendor.useragents import UserAgentParser
from odoo.tests import TransactionCase

from odoo.addons.base.models import res_device
from odoo.addons.base.models.ir_autovacuum import is_autovacuum

SID = "sid_rdev_" + "a" * 60


class _Session(dict):
    def __init__(self, uid, sid=SID):
        super().__init__()
        self.uid = uid
        self.sid = sid
        self.trace = None

    def update_trace(self, request):
        return self.trace


class DeviceCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["res.device"].with_context(active_test=False).search([]).unlink()
        self.session = _Session(self.env.uid)
        self.request = SimpleNamespace(session=self.session, app=odoo.http.root)

    def _seen(self, when, ip="10.0.0.1", platform="linux", browser="firefox"):
        stamp = datetime.fromisoformat(when).replace(tzinfo=UTC).timestamp()
        self.session.trace = {
            "platform": platform,
            "browser": browser,
            "ip_address": ip,
            "first_activity": stamp,
            "last_activity": stamp,
        }
        self.env["res.device"]._update_device(self.request)
        self.env.invalidate_all()

    def _device(self, **vals):
        return self.env["res.device"].create(
            {
                "session_identifier": "sid_rdev_manual",
                "user_id": self.env.uid,
                "last_activity": "2020-01-01 00:00:00",
                **vals,
            }
        )

    def _devices(self):
        return self.env["res.device"].with_context(active_test=False).search([])


class TestDeviceUpsert(DeviceCase):
    def test_one_device_one_row_per_address(self):
        self._seen("2026-07-01 08:00:00", ip="10.0.0.1")
        self._seen("2026-07-01 09:00:00", ip="10.0.0.1")
        self._seen("2026-07-01 12:00:00", ip="10.0.0.2")

        device = self._devices()
        self.assertEqual(len(device), 1)
        self.assertEqual(device.ip_address, "10.0.0.2")
        self.assertEqual(device.first_activity, datetime(2026, 7, 1, 8, 0))
        self.assertEqual(device.last_activity, datetime(2026, 7, 1, 12, 0))
        self.assertEqual(
            [(log.ip_address, log.last_activity) for log in device.log_ids],
            [
                ("10.0.0.2", datetime(2026, 7, 1, 12, 0)),
                ("10.0.0.1", datetime(2026, 7, 1, 9, 0)),
            ],
        )

    def test_device_id_survives_refreshes(self):
        self._seen("2026-07-01 08:00:00")
        shown = self._devices()
        self._seen("2026-07-01 09:00:00")
        self._seen("2026-07-01 10:00:00", ip="10.0.0.9")
        self.assertEqual(self._devices(), shown)
        with patch.object(
            type(res_device.root.session_store), "remove_sessions_for_identifiers"
        ):
            shown._revoke()
        self.assertFalse(shown.active)

    def test_late_trace_keeps_the_latest_address(self):
        self._seen("2026-07-01 12:00:00", ip="10.0.0.2")
        self._seen("2026-07-01 08:00:00", ip="10.0.0.1")
        device = self._devices()
        self.assertEqual(device.ip_address, "10.0.0.2")
        self.assertEqual(device.first_activity, datetime(2026, 7, 1, 8, 0))
        self.assertEqual(device.last_activity, datetime(2026, 7, 1, 12, 0))

    def test_unknown_platform_and_browser_are_one_device(self):
        self._seen("2026-07-01 08:00:00", platform=None, browser=None)
        self._seen("2026-07-01 09:00:00", platform=None, browser=None, ip="10.0.0.2")
        self.assertEqual(len(self._devices()), 1)
        self.assertEqual(len(self._devices().log_ids), 2)

    def test_browsers_are_devices(self):
        self._seen("2026-07-01 08:00:00", browser="firefox")
        self._seen("2026-07-01 08:00:00", browser="chrome")
        self.assertEqual(
            sorted(self._devices().mapped("browser")), ["chrome", "firefox"]
        )

    def test_activity_revives_a_device_revoked_by_mistake(self):
        self._seen("2026-07-01 08:00:00")
        self.env["res.device"]._mark_revoked([SID[:42]])
        self.assertFalse(self.env["res.device"].search([]))
        self._seen("2026-07-01 09:00:00")
        self.assertTrue(self.env["res.device"].search([]).active)

    def test_device_type_follows_the_platform(self):
        self._seen("2026-07-01 08:00:00", platform="android", browser="chrome")
        self.assertEqual(self._devices().device_type, "mobile")


class TestDeviceModel(DeviceCase):
    def test_autovacuums(self):
        def vacuums(model):
            return {
                name
                for name, _func in inspect.getmembers(
                    self.env[model].__class__, is_autovacuum
                )
            }

        self.assertEqual(
            vacuums("res.device"), {"_update_revoked", "_gc_revoked_devices"}
        )
        self.assertEqual(vacuums("res.device.log"), {"_gc_stale_addresses"})

    def test_mobile_platforms_are_parser_vocabulary(self):
        emitted = {name for _regex, name in UserAgentParser.platforms}
        self.assertLessEqual(res_device._MOBILE_PLATFORMS, emitted)
        self.assertEqual(res_device._device_type("Android"), "mobile")
        self.assertEqual(res_device._device_type("linux"), "computer")
        self.assertEqual(res_device._device_type(None), "computer")

    def test_display_names(self):
        cases = {
            ("iphone", "safari"): "iPhone Safari",
            ("windows phone", "edge"): "Windows Phone Edge",
            ("macos", "samsung"): "macOS Samsung Internet",
            ("linux", "firefox"): "Linux Firefox",
            (False, False): "Unknown Unknown",
        }
        for (platform, browser), name in cases.items():
            device = self._device(
                session_identifier=f"sid_rdev_{platform}_{browser}",
                platform=platform,
                browser=browser,
            )
            self.assertEqual(device.display_name, name)

    def test_is_current_without_request(self):
        self.assertFalse(self._device().is_current)

    def test_revoked_devices_are_archived(self):
        device = self._device()
        self.assertEqual(self.env["res.device"].search([]), device)
        self.assertEqual(self.env["res.device"]._mark_revoked(["sid_rdev_manual"]), 1)
        self.assertFalse(device.active)
        self.assertFalse(self.env["res.device"].search([]))
        self.assertFalse(self.env.user.device_ids)
        self.assertEqual(self.env["res.device"]._mark_revoked(["sid_rdev_manual"]), 0)


class TestUpdateRevoked(DeviceCase):
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
            result = self.env["res.device"].sudo()._update_revoked()
        self.env.invalidate_all()
        return result

    def test_missing_sessions_are_revoked(self):
        gone = self._device(session_identifier="sid_rdev_gone")
        gone_firefox = self._device(session_identifier="sid_rdev_gone", browser="ff")
        live = self._device(session_identifier="sid_rdev_live")
        recent = self._device(
            session_identifier="sid_rdev_recent", last_activity=datetime.now()
        )

        self.assertEqual(self._sweep(live={"sid_rdev_live"}), (2, False))

        self.assertFalse(gone.active or gone_firefox.active)
        self.assertTrue(live.active)
        self.assertTrue(recent.active, "a recently active device is not asked about")

    def test_batches_cover_every_candidate(self):
        devices = [self._device(session_identifier=f"sid_rdev_{n}") for n in range(7)]
        with patch.object(res_device, "_REVOKE_SWEEP_BATCH", 2):
            result = self._sweep(live={"sid_rdev_1", "sid_rdev_4"})
        self.assertEqual(result, (5, False))
        self.assertEqual(
            [device.active for device in devices],
            [False, True, False, False, True, False, False],
        )

    def test_stops_when_the_time_budget_is_spent(self):
        self._device(session_identifier="sid_rdev_x")
        self._device(session_identifier="sid_rdev_y")
        with patch.object(res_device, "_REVOKE_SWEEP_BATCH", 1):
            self.assertEqual(self._sweep(live=(), budget=0), (1, True))


class TestRevokedRetention(DeviceCase):
    def _gc(self):
        result = self.env["res.device"]._gc_revoked_devices()
        self.env.invalidate_all()
        return result

    def test_revoked_devices_expire_with_their_addresses(self):
        now = datetime.now()
        expired = self._device(
            session_identifier="sid_rdev_old",
            active=False,
            last_activity=now - timedelta(days=91),
        )
        address = self.env["res.device.log"].create(
            {"device_id": expired.id, "ip_address": "10.0.0.1"}
        )
        kept_recent = self._device(
            session_identifier="sid_rdev_recent",
            active=False,
            last_activity=now - timedelta(days=89),
        )
        kept_active = self._device(
            session_identifier="sid_rdev_active",
            last_activity=now - timedelta(days=400),
        )

        self.assertEqual(self._gc(), (1, False))

        self.assertFalse(expired.exists())
        self.assertFalse(address.exists())
        self.assertTrue(kept_recent.exists())
        self.assertTrue(kept_active.exists())

    def test_retention_is_configurable(self):
        stale = self._device(
            active=False, last_activity=datetime.now() - timedelta(days=10)
        )
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("base.device_retention_days", "0")
        self.assertIsNone(self._gc())
        self.assertTrue(stale.exists())
        icp.set_param("base.device_retention_days", "7")
        self.assertEqual(self._gc(), (1, False))
        self.assertFalse(stale.exists())

    def test_stale_addresses_expire_but_not_the_current_one(self):
        now = datetime.now()
        device = self._device(ip_address="10.0.0.3", last_activity=now)
        Address = self.env["res.device.log"]
        stale = Address.create(
            {
                "device_id": device.id,
                "ip_address": "10.0.0.1",
                "last_activity": now - timedelta(days=91),
            }
        )
        recent = Address.create(
            {
                "device_id": device.id,
                "ip_address": "10.0.0.2",
                "last_activity": now - timedelta(days=89),
            }
        )
        current = Address.create(
            {
                "device_id": device.id,
                "ip_address": "10.0.0.3",
                "last_activity": now - timedelta(days=200),
            }
        )
        self.env.flush_all()

        self.assertEqual(Address._gc_stale_addresses(), (1, False))
        self.env.invalidate_all()

        self.assertFalse(stale.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(current.exists(), "the device's current address stays")
        self.env["ir.config_parameter"].sudo().set_param(
            "base.device_retention_days", "0"
        )
        self.assertIsNone(Address._gc_stale_addresses())

    def test_batches_report_remaining_work(self):
        for n in range(3):
            self._device(session_identifier=f"sid_rdev_{n}", active=False)
        with patch.object(res_device, "_RETENTION_BATCH", 2):
            self.assertEqual(self._gc(), (2, True))
            self.assertEqual(self._gc(), (1, False))


class TestEndOtherSessions(TransactionCase):
    def test_the_epoch_changes_every_session_token(self):
        user = self.env.user
        before = user._get_session_token("a" * 84)
        epoch = user.session_epoch
        user._end_other_sessions()
        self.assertEqual(user.session_epoch, epoch + 1)
        self.assertNotEqual(user._get_session_token("a" * 84), before)
