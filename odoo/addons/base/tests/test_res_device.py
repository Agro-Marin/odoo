import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import odoo.http
from odoo.exceptions import AccessError, UserError
from odoo.libs._vendor.useragents import UserAgentParser
from odoo.tests import TransactionCase, new_test_user

from odoo.addons.base.models import res_device
from odoo.addons.base.models.ir_autovacuum import is_autovacuum

KEY = "k" * 43


class _Session(dict):
    def __init__(self, uid, sid):
        super().__init__()
        self.uid = uid
        self.sid = sid
        self.trace = None

    def update_trace(self, request):
        return self.trace


class _Response:
    def __init__(self):
        self.cookies = {}

    def set_cookie(self, key, value, **options):
        self.cookies[key] = value


class DeviceCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["res.device"].with_context(active_test=False).search([]).unlink()

    def _seen(
        self,
        when,
        *,
        sid="sid_rdev_" + "a" * 60,
        key=KEY,
        ip="10.0.0.1",
        platform="linux",
        browser="firefox",
        issue=False,
        uid=None,
        at_login=None,
    ):
        session = _Session(uid or self.env.uid, sid)
        stamp = datetime.fromisoformat(when).replace(tzinfo=UTC).timestamp()
        session.trace = {
            "platform": platform,
            "browser": browser,
            "ip_address": ip,
            "first_activity": stamp,
            "last_activity": stamp,
        }
        response = _Response() if issue else None
        request = SimpleNamespace(
            session=session,
            app=odoo.http.root,
            httprequest=SimpleNamespace(
                cookies={res_device.DEVICE_KEY_COOKIE: key} if key else {}
            ),
            future_response=response,
        )
        self.env["res.device"]._update_device(
            request, at_login=issue if at_login is None else at_login
        )
        self.env.invalidate_all()
        return response

    def _devices(self):
        return self.env["res.device"].with_context(active_test=False).search([])

    def _device(self, sessions=("sid_rdev_manual",), active=True, **vals):
        device = self.env["res.device"].create(
            {
                "user_id": self.env.uid,
                "key_hash": f"hash_{vals.get('name', '')}_{sessions[0]}",
                "last_activity": "2020-01-01 00:00:00",
                "active": active,
                **vals,
            }
        )
        for identifier in sessions:
            self.env["res.device.session"].create(
                {
                    "device_id": device.id,
                    "session_identifier": identifier,
                    "last_activity": vals.get("last_activity", "2020-01-01"),
                    "active": active,
                }
            )
        return device


class TestDeviceUpsert(DeviceCase):
    def test_a_browser_is_one_device_across_its_sessions(self):
        self._seen("2026-07-01 08:00:00", sid="sid_rdev_morning" + "a" * 50)
        self._seen(
            "2026-07-02 09:00:00", sid="sid_rdev_next_day" + "a" * 50, ip="10.0.0.2"
        )

        device = self._devices()
        self.assertEqual(len(device), 1)
        self.assertEqual(len(device.session_ids), 2)
        self.assertEqual(device.first_activity, datetime(2026, 7, 1, 8, 0))
        self.assertEqual(device.last_activity, datetime(2026, 7, 2, 9, 0))
        self.assertEqual(device.ip_address, "10.0.0.2")
        self.assertEqual(device.log_ids.mapped("ip_address"), ["10.0.0.2", "10.0.0.1"])

    def test_the_first_visit_issues_the_key_the_next_one_presents(self):
        response = self._seen("2026-07-01 08:00:00", key=None, issue=True)
        issued = response.cookies[res_device.DEVICE_KEY_COOKIE]
        self.assertRegex(issued, r"^[A-Za-z0-9_-]{43}$")
        device = self._devices()
        self.assertEqual(device.key_hash, res_device._sha256(issued))
        self.assertNotIn(issued, device.key_hash)

        again = self._seen(
            "2026-07-03 08:00:00", sid="sid_rdev_later" + "a" * 50, key=issued
        )
        self.assertIsNone(again)
        self.assertEqual(self._devices(), device)
        self.assertEqual(len(device.session_ids), 2)

    def test_a_session_without_a_key_gets_none_until_it_logs_in(self):
        responses = [
            self._seen("2026-07-01 09:00:00", key=None, issue=True, at_login=False)
            for _parallel_request in range(3)
        ]
        self.assertFalse(any(response.cookies for response in responses))
        self.assertEqual(len(self._devices()), 1, "one browser, one device")

    def test_a_malformed_key_is_replaced(self):
        response = self._seen("2026-07-01 08:00:00", key="not-a-key", issue=True)
        self.assertIn(res_device.DEVICE_KEY_COOKIE, response.cookies)

    def test_without_a_key_each_session_is_a_device(self):
        self._seen("2026-07-01 08:00:00", key=None, sid="sid_rdev_one" + "a" * 50)
        self._seen("2026-07-01 09:00:00", key=None, sid="sid_rdev_two" + "a" * 50)
        self.assertEqual(len(self._devices()), 2)

    def test_the_keyless_hash_matches_the_migration(self):
        self.env.cr.execute(
            """
            SELECT encode(sha256(convert_to(concat_ws(
                chr(31), 'session', 'sid_x', coalesce(NULL, ''), 'firefox'
            ), 'UTF8')), 'hex')
            """
        )
        self.assertEqual(
            self.env.cr.fetchone()[0],
            res_device._device_key_hash(None, "sid_x", None, "firefox"),
        )

    def test_two_users_on_one_browser_are_two_devices(self):
        other = new_test_user(self.env, login="rdev_other")
        self._seen("2026-07-01 08:00:00")
        self._seen("2026-07-01 09:00:00", uid=other.id, sid="sid_rdev_o" + "a" * 50)
        self.assertEqual(
            sorted(self._devices().mapped("user_id").ids),
            sorted([self.env.uid, other.id]),
        )

    def test_late_trace_keeps_the_latest_address(self):
        self._seen("2026-07-01 12:00:00", ip="10.0.0.2")
        self._seen("2026-07-01 08:00:00", ip="10.0.0.1")
        device = self._devices()
        self.assertEqual(device.ip_address, "10.0.0.2")
        self.assertEqual(device.first_activity, datetime(2026, 7, 1, 8, 0))

    def test_activity_revives_a_device_and_its_session(self):
        sid = "sid_rdev_" + "a" * 60
        self._seen("2026-07-01 08:00:00", sid=sid)
        self.env["res.device.session"]._mark_revoked([sid[:42]])
        self.assertFalse(self.env["res.device"].search([]))
        self._seen("2026-07-01 09:00:00", sid=sid)
        device = self.env["res.device"].search([])
        self.assertTrue(device.active)
        self.assertTrue(device.session_ids.active)

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

        self.assertEqual(vacuums("res.device"), {"_gc_revoked_devices"})
        self.assertEqual(
            vacuums("res.device.session"), {"_update_revoked", "_gc_ended_sessions"}
        )
        self.assertEqual(vacuums("res.device.log"), {"_gc_stale_addresses"})

    def test_mobile_platforms_are_parser_vocabulary(self):
        emitted = {name for _regex, name in UserAgentParser.platforms}
        self.assertLessEqual(res_device._MOBILE_PLATFORMS, emitted)
        self.assertEqual(res_device._device_type("Android"), "mobile")
        self.assertEqual(res_device._device_type(None), "computer")

    def test_display_names(self):
        cases = {
            ("iphone", "safari", False): "iPhone Safari",
            ("windows phone", "edge", False): "Windows Phone Edge",
            ("macos", "samsung", False): "macOS Samsung Internet",
            (False, False, False): "Unknown Unknown",
            ("linux", "firefox", "Work laptop"): "Work laptop",
        }
        for (platform, browser, name), expected in cases.items():
            device = self._device(
                sessions=(f"sid_rdev_{platform}_{browser}_{name}",),
                platform=platform,
                browser=browser,
                name=name,
            )
            self.assertEqual(device.display_name, expected)

    def test_a_user_renames_their_device_and_nothing_else(self):
        user = new_test_user(self.env, login="rdev_renamer", groups="base.group_user")
        mine = self._device(sessions=("sid_rdev_mine",), user_id=user.id)
        theirs = self._device(sessions=("sid_rdev_theirs",))

        mine.with_user(user).write({"name": "Work laptop"})
        self.assertEqual(mine.display_name, "Work laptop")
        with self.assertRaises(AccessError):
            mine.with_user(user).write({"active": False})
        with self.assertRaises(AccessError):
            theirs.with_user(user).write({"name": "Mine now"})

    def test_rename_opens_the_rename_form(self):
        action = self._device().action_rename()
        self.assertEqual(action["res_model"], "res.device")
        self.assertEqual(action["target"], "new")
        self.assertEqual(
            action["views"], [(self.env.ref("base.res_device_view_rename").id, "form")]
        )

    def test_a_revoked_device_cannot_be_unarchived(self):
        device = self._device(active=False)
        with self.assertRaises(UserError):
            device.action_unarchive()
        self.assertFalse(device.active)

    def test_is_current_without_request(self):
        self.assertFalse(self._device().is_current)

    def test_a_device_stays_while_one_of_its_sessions_lives(self):
        device = self._device(sessions=("sid_rdev_a", "sid_rdev_b"))
        Session = self.env["res.device.session"]
        self.assertEqual(Session._mark_revoked(["sid_rdev_a"]), 1)
        self.assertTrue(device.active)
        self.assertEqual(Session._mark_revoked(["sid_rdev_b"]), 1)
        self.assertFalse(device.active)
        self.assertFalse(self.env.user.device_ids)
        self.assertEqual(Session._mark_revoked(["sid_rdev_b"]), 0)

    def test_revoking_a_device_ends_all_its_sessions(self):
        first, second = "sid_rdev_" + "a" * 33, "sid_rdev_" + "b" * 33
        device = self._device(sessions=(first, second))
        with patch.object(
            type(res_device.root.session_store), "remove_sessions_for_identifiers"
        ) as remove:
            device._revoke()
        self.assertEqual(sorted(remove.call_args.args[0]), [first, second])
        self.assertFalse(device.active)
        self.assertFalse(
            device.with_context(active_test=False).session_ids.filtered("active")
        )


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
            result = self.env["res.device.session"].sudo()._update_revoked()
        self.env.invalidate_all()
        return result

    def test_missing_sessions_are_revoked(self):
        gone = self._device(sessions=("sid_rdev_gone",))
        live = self._device(sessions=("sid_rdev_live",))
        recent = self._device(
            sessions=("sid_rdev_recent",), last_activity=datetime.now()
        )

        self.assertEqual(self._sweep(live={"sid_rdev_live"}), (1, False))

        self.assertFalse(gone.active)
        self.assertTrue(live.active)
        self.assertTrue(recent.active, "a recently active session is not asked about")

    def test_batches_cover_every_candidate(self):
        devices = [self._device(sessions=(f"sid_rdev_{n}",)) for n in range(7)]
        with patch.object(res_device, "_REVOKE_SWEEP_BATCH", 2):
            result = self._sweep(live={"sid_rdev_1", "sid_rdev_4"})
        self.assertEqual(result, (5, False))
        self.assertEqual(
            [device.active for device in devices],
            [False, True, False, False, True, False, False],
        )

    def test_stops_when_the_time_budget_is_spent(self):
        self._device(sessions=("sid_rdev_x",))
        self._device(sessions=("sid_rdev_y",))
        with patch.object(res_device, "_REVOKE_SWEEP_BATCH", 1):
            self.assertEqual(self._sweep(live=(), budget=0), (1, True))


class TestRevokedRetention(DeviceCase):
    def test_revoked_devices_expire_with_their_sessions_and_addresses(self):
        now = datetime.now()
        expired = self._device(
            sessions=("sid_rdev_old",),
            active=False,
            last_activity=now - timedelta(days=91),
        )
        session = expired.with_context(active_test=False).session_ids
        address = self.env["res.device.log"].create(
            {"device_id": expired.id, "ip_address": "10.0.0.1"}
        )
        kept_recent = self._device(
            sessions=("sid_rdev_recent",),
            active=False,
            last_activity=now - timedelta(days=89),
        )
        kept_active = self._device(
            sessions=("sid_rdev_active",), last_activity=now - timedelta(days=400)
        )

        self.assertEqual(self.env["res.device"]._gc_revoked_devices(), (1, False))
        self.env.invalidate_all()

        self.assertFalse(expired.exists() or session.exists() or address.exists())
        self.assertTrue(kept_recent.exists())
        self.assertTrue(kept_active.exists())

    def test_ended_sessions_of_a_live_device_expire(self):
        now = datetime.now()
        device = self._device(sessions=("sid_rdev_live",), last_activity=now)
        Session = self.env["res.device.session"]
        ended = Session.create(
            {
                "device_id": device.id,
                "session_identifier": "sid_rdev_ended",
                "last_activity": now - timedelta(days=91),
                "active": False,
            }
        )
        self.assertEqual(Session._gc_ended_sessions(), (1, False))
        self.env.invalidate_all()
        self.assertFalse(ended.exists())
        self.assertEqual(device.session_ids.session_identifier, "sid_rdev_live")

    def test_retention_is_configurable(self):
        stale = self._device(
            active=False, last_activity=datetime.now() - timedelta(days=10)
        )
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("base.device_retention_days", "0")
        self.assertIsNone(self.env["res.device"]._gc_revoked_devices())
        self.assertIsNone(self.env["res.device.session"]._gc_ended_sessions())
        self.assertIsNone(self.env["res.device.log"]._gc_stale_addresses())
        self.assertTrue(stale.exists())
        icp.set_param("base.device_retention_days", "7")
        self.assertEqual(self.env["res.device"]._gc_revoked_devices(), (1, False))
        self.assertFalse(stale.exists())

    def test_stale_addresses_expire_but_not_the_current_one(self):
        now = datetime.now()
        device = self._device(ip_address="10.0.0.3", last_activity=now)
        Address = self.env["res.device.log"]
        stale, recent, current = (
            Address.create(
                {"device_id": device.id, "ip_address": ip, "last_activity": when}
            )
            for ip, when in (
                ("10.0.0.1", now - timedelta(days=91)),
                ("10.0.0.2", now - timedelta(days=89)),
                ("10.0.0.3", now - timedelta(days=200)),
            )
        )
        self.env.flush_all()

        self.assertEqual(Address._gc_stale_addresses(), (1, False))
        self.env.invalidate_all()

        self.assertFalse(stale.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(current.exists(), "the device's current address stays")

    def test_batches_report_remaining_work(self):
        for n in range(3):
            self._device(sessions=(f"sid_rdev_{n}",), active=False)
        with patch.object(res_device, "_RETENTION_BATCH", 2):
            self.assertEqual(self.env["res.device"]._gc_revoked_devices(), (2, True))
            self.assertEqual(self.env["res.device"]._gc_revoked_devices(), (1, False))


class TestEndOtherSessions(TransactionCase):
    def test_the_epoch_changes_every_session_token(self):
        user = self.env.user
        before = user._get_session_token("a" * 84)
        epoch = user.session_epoch
        user._end_other_sessions()
        self.assertEqual(user.session_epoch, epoch + 1)
        self.assertNotEqual(user._get_session_token("a" * 84), before)
