import json
import time
from datetime import datetime
from unittest.mock import patch

from freezegun import freeze_time

import odoo
from odoo import Command
from odoo.exceptions import AccessError
from odoo.http import STORED_SESSION_BYTES
from odoo.service import security
from odoo.tests.utils import HOST, get_db_name

from .test_common import TestHttpBase
from odoo.addons.base.models.res_device import DEVICE_KEY_COOKIE
from odoo.addons.test_http.utils import (
    TEST_IP,
    USER_AGENT_android_chrome,
    USER_AGENT_linux_chrome,
    USER_AGENT_linux_firefox,
)


class TestDevice(TestHttpBase):
    def setUp(self):
        super().setUp()

        self.Device = self.env["res.device"]
        self.DeviceLog = self.env["res.device.log"]
        self.Device.with_context(active_test=False).search([]).unlink()
        self.browser_keys = {}

        self.user_admin = self.env.ref("base.user_admin")
        self.user_internal = self.env["res.users"].create(
            {
                "login": "internal",
                "password": "internal",
                "name": "Internal",
                "email": "internal@example.com",
                "group_ids": [Command.set([self.env.ref("base.group_user").id])],
            }
        )

    def authenticate(self, login, password):
        return super().authenticate(
            login, password, session_extra={"_trace_disable": False}
        )

    def hit(self, time, endpoint, headers=None, ip=None):
        if ip:
            headers = headers or {}
            headers = {
                **headers,
                "Host": "",
                "X-Forwarded-For": ip,
                "X-Forwarded-Host": "odoo.com",
                "X-Forwarded-Proto": "http",
            }
        # one cookie jar plays every browser: each user agent keeps its own
        # browser key, as separate browsers would
        agent = (headers or {}).get("User-Agent", "")
        jar = self.opener.cookies
        jar.set(DEVICE_KEY_COOKIE, None)
        if agent in self.browser_keys:
            jar.set(DEVICE_KEY_COOKIE, self.browser_keys[agent], domain=HOST)
        with (
            freeze_time(time),
            odoo.tools.config.patch(proxy_mode=bool(ip)),
        ):
            response = self.url_open(url=endpoint, headers=headers)
        if issued := jar.get(DEVICE_KEY_COOKIE):
            self.browser_keys[agent] = issued
        return response

    def info_trace(self, trace):
        return {
            "elapsed_time": trace["last_activity"] - trace["first_activity"],
            "platform": trace["platform"],
            "browser": trace["browser"],
            "ip_address": trace["ip_address"],
        }

    def get_devices_logs(self, user=None):
        self.env.invalidate_all()
        domain = [("user_id", "=", user.id)] if user else []
        devices = self.Device.search(domain)
        return devices, devices.log_ids

    def test_detection_device_readonly(self):
        session = self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-public")

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(logs), 1)
        session = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(len(session["_trace"]), 1)

    def test_detection_device_no_readonly(self):
        session = self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-public?readonly=0")

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(logs), 1)
        session = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(len(session["_trace"]), 1)

    def test_detection_user_public(self):
        self.authenticate(None, None)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-public?readonly=0")

        devices, logs = self.get_devices_logs()
        self.assertEqual(len(devices), 0)
        self.assertEqual(len(logs), 0)

    def test_detection_device_readonly_then_no_readonly(self):
        session = self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-public")

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(logs), 1)
        session = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(len(session["_trace"]), 1)

        self.hit("2024-01-01 08:00:00", "/test_http/greeting-public?readonly=0")

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(logs), 1)
        session = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(len(session["_trace"]), 1)

    def test_detection_device_according_to_time(self):
        session = self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-public?readonly=0")

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(logs), 1)
        session = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(len(session["_trace"]), 1)
        self.assertEqual(self.info_trace(session["_trace"][0])["elapsed_time"], 0)

        self.hit("2024-01-01 08:30:00", "/test_http/greeting-public?readonly=0")

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(logs), 1)
        session = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(len(session["_trace"]), 1)
        self.assertEqual(self.info_trace(session["_trace"][0])["elapsed_time"], 0)

        self.hit("2024-01-01 09:00:00", "/test_http/greeting-public?readonly=0")

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs.last_activity, datetime(2024, 1, 1, 9, 0))
        session = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(len(session["_trace"]), 1)
        self.assertEqual(self.info_trace(session["_trace"][0])["elapsed_time"], 3600)

        self.hit("2024-01-01 10:00:00", "/test_http/greeting-public?readonly=0")

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs.first_activity, datetime(2024, 1, 1, 8, 0))
        self.assertEqual(logs.last_activity, datetime(2024, 1, 1, 10, 0))
        self.assertEqual(devices.last_activity, datetime(2024, 1, 1, 10, 0))
        session = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(len(session["_trace"]), 1)
        self.assertEqual(self.info_trace(session["_trace"][0])["elapsed_time"], 7200)

    def test_detection_device_according_to_useragent(self):
        session = self.authenticate(self.user_admin.login, self.user_admin.login)

        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_chrome},
        )

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(logs), 1)
        session = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(len(session["_trace"]), 1)
        self.assertEqual(self.info_trace(session["_trace"][0])["platform"], "linux")
        self.assertEqual(self.info_trace(session["_trace"][0])["browser"], "chrome")

        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_firefox},
        )

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 2)
        self.assertEqual(len(logs), 2)
        session = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(len(session["_trace"]), 2)
        self.assertEqual(self.info_trace(session["_trace"][1])["platform"], "linux")
        self.assertEqual(self.info_trace(session["_trace"][1])["browser"], "firefox")

    def test_detection_device_according_to_ipaddress(self):
        session = self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-public?readonly=0")

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(logs), 1)
        session = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(len(session["_trace"]), 1)

        self.hit(
            "2024-01-01 08:00:01",
            "/test_http/greeting-public?readonly=0",
            ip=TEST_IP,
        )

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(logs), 2)
        session = odoo.http.root.session_store.get(session.sid)
        self.assertEqual(len(session["_trace"]), 2)
        self.assertNotEqual(
            self.info_trace(session["_trace"][0])["ip_address"], TEST_IP
        )
        self.assertEqual(self.info_trace(session["_trace"][1])["ip_address"], TEST_IP)

        localized_device = devices.filtered(lambda device: device.ip_address == TEST_IP)
        self.assertEqual(localized_device.country, "France")

    def test_detection_usurpation_sid(self):
        session = self.authenticate(self.user_internal.login, self.user_internal.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-user?readonly=0")

        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-user?readonly=0",
            headers={"session_id": session.sid},
            ip=TEST_IP,
        )
        devices, logs = self.get_devices_logs(self.user_internal)
        self.assertEqual(len(devices), 1)
        self.assertEqual(len(logs), 2)
        self.assertEqual(len(self.user_internal.device_ids), 1)

    def test_detection_devices_according_to_time_useragent(self):
        self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_chrome},
        )
        self.assertEqual(len(self.user_admin.device_ids), 1)

        self.hit(
            "2024-01-01 09:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_chrome},
        )
        self.assertEqual(len(self.user_admin.device_ids), 1)

        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_firefox},
        )
        self.assertEqual(len(self.user_admin.device_ids), 2)

        self.hit(
            "2024-01-01 09:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_firefox},
        )
        self.assertEqual(len(self.user_admin.device_ids), 2)

    def test_detection_devices_according_to_user_or_admin(self):
        self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-public?readonly=0")
        self.hit("2024-01-01 09:00:00", "/test_http/greeting-public?readonly=0")
        self.authenticate(self.user_internal.login, self.user_internal.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-public?readonly=0")
        self.hit("2024-01-01 09:00:00", "/test_http/greeting-public?readonly=0")

        devices, logs = self.get_devices_logs()
        self.assertEqual(len(devices), 2)
        self.assertEqual(len(logs), 2)
        self.assertEqual(len(self.user_admin.device_ids), 1)
        self.assertEqual(len(self.user_internal.device_ids), 1)

        devices_from_admin = self.Device.with_user(self.user_admin).search([])
        devices_from_internal = self.Device.with_user(self.user_internal).search([])
        self.assertEqual(len(devices_from_admin), 2)
        self.assertEqual(len(devices_from_internal), 1)

    def test_differentiate_computer_and_mobile(self):
        self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_chrome},
        )
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_android_chrome},
        )

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 2)
        self.assertEqual(len(logs), 2)

        laptop_device = devices.filtered(
            lambda device: device.device_type == "computer"
        )
        mobile_device = devices.filtered(lambda device: device.device_type == "mobile")
        self.assertEqual(len(laptop_device), 1)
        self.assertEqual(len(mobile_device), 1)

    def test_retrieve_linked_ip_addresses(self):
        self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            ip="193.0.3.43",
        )
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            ip="192.0.2.42",
        )
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            ip="191.0.1.41",
        )

        devices, _ = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertEqual(
            sorted(devices.log_ids.mapped("ip_address")),
            ["191.0.1.41", "192.0.2.42", "193.0.3.43"],
        )

    def test_retrieve_linked_ip_addresses_according_to_devices(self):
        self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_chrome},
            ip="193.0.3.43",
        )
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_chrome},
            ip="192.0.2.42",
        )
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_firefox},
            ip="191.0.1.41",
        )

        devices, _ = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 2)
        device_chrome = devices.filtered(lambda device: device.browser == "chrome")
        device_firefox = devices.filtered(lambda device: device.browser == "firefox")
        self.assertEqual(
            sorted(device_chrome.log_ids.mapped("ip_address")),
            ["192.0.2.42", "193.0.3.43"],
        )
        self.assertEqual(device_firefox.log_ids.mapped("ip_address"), ["191.0.1.41"])

    def test_detection_no_trace_mechanism(self):
        session = self.authenticate(self.user_admin.login, self.user_admin.login)
        session["_trace_disable"] = True
        odoo.http.root.session_store.save(session)
        res = self.hit("2024-01-01 08:00:00", "/test_http/greeting-public?readonly=0")
        self.assertEqual(res.status_code, 200)
        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 0)
        self.assertEqual(len(logs), 0)

    def test_detection_device_default_order(self):
        self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_chrome},
        )
        self.hit(
            "2024-01-01 10:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_firefox},
        )
        self.hit(
            "2024-01-01 09:00:00",
            "/test_http/greeting-public?readonly=0",
            headers={"User-Agent": USER_AGENT_android_chrome},
        )
        devices, _ = self.get_devices_logs(self.user_admin)
        self.assertEqual(
            list(
                zip(devices.mapped("platform"), devices.mapped("browser"), strict=False)
            ),
            [("linux", "firefox"), ("android", "chrome"), ("linux", "chrome")],
            "By default, devices should be found from the most recent to the least recent (according to their last activity).",
        )

    def test_deletion_device(self):
        self.authenticate(self.user_internal.login, self.user_internal.login)
        res = self.hit("2024-01-01 08:00:00", "/test_http/greeting-user?readonly=0")
        self.assertNotIn("/web/login", res.url)

        user_internal_device = self.user_internal.device_ids
        self.assertEqual(len(user_internal_device), 1)
        self.assertTrue(user_internal_device.active)

        user_internal_device._revoke()

        res = self.hit("2024-01-01 08:00:01", "/test_http/greeting-user?readonly=0")
        self.assertIn("/web/login", res.url)

    def test_deletion_invalidate_sid(self):
        session = self.authenticate(self.user_internal.login, self.user_internal.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-user?readonly=0")

        self.user_internal.device_ids._revoke()

        res = self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-user?readonly=0",
            headers={"session_id": session.sid},
        )
        self.assertIn("/web/login", res.url)

    def test_deletion_specific_device(self):
        self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-user?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_chrome},
        )
        self.hit(
            "2024-01-01 09:00:00",
            "/test_http/greeting-user?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_chrome},
        )
        self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-user?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_chrome},
        )
        self.hit(
            "2024-01-01 09:00:00",
            "/test_http/greeting-user?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_chrome},
        )
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-user?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_firefox},
        )

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 2, "one Chrome across two logins, one Firefox")
        self.assertEqual(len(logs), 2)
        chrome = devices.filtered(lambda device: device.browser == "chrome")
        self.assertEqual(len(chrome.session_ids), 2)

        self.user_admin.device_ids.filtered(
            lambda device: "firefox" in device.browser
        )._revoke()

        res = self.hit(
            "2024-01-01 08:00:30",
            "/test_http/greeting-user?readonly=0",
            headers={"User-Agent": USER_AGENT_linux_firefox},
        )
        self.assertIn("/web/login", res.url)

    def test_revoke_foreign_device_denied_for_non_system(self):
        self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-user?readonly=0")
        admin_device = self.user_admin.device_ids
        self.assertEqual(len(admin_device), 1)

        foreign_device = admin_device.sudo().with_user(self.user_internal)
        with self.assertRaises(AccessError):
            foreign_device._revoke()
        self.assertTrue(admin_device.active)

    def test_revoke_foreign_device_allowed_for_system(self):
        self.authenticate(self.user_internal.login, self.user_internal.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-user?readonly=0")
        internal_device = self.user_internal.device_ids
        self.assertEqual(len(internal_device), 1)
        self.assertTrue(internal_device.active)

        internal_device.with_user(self.user_admin)._revoke()
        self.assertFalse(internal_device.active)

    def _create_device_log_for_user(self, session, count):
        for _ in range(count):
            identifier = odoo.http.root.session_store.generate_key()[
                :STORED_SESSION_BYTES
            ]
            device = self.Device.create(
                {
                    "key_hash": f"key_{identifier}",
                    "user_id": session.uid,
                    "first_activity": datetime.now(),
                    "last_activity": datetime.now(),
                    "session_ids": [
                        Command.create(
                            {
                                "session_identifier": identifier,
                                "first_activity": datetime.now(),
                                "last_activity": datetime.now(),
                            }
                        )
                    ],
                }
            )
            self.DeviceLog.create(
                {
                    "device_id": device.id,
                    "first_activity": datetime.now(),
                    "last_activity": datetime.now(),
                }
            )

    def test_filesystem_reflexion(self):
        session = self.authenticate(self.user_admin.login, self.user_admin.login)
        with freeze_time("2025-01-01 08:00:00"):
            self._create_device_log_for_user(session, 10)

        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 10)
        self.assertEqual(len(logs), 10)
        self.assertEqual(len(self.user_admin.device_ids), 10)

        session = self.authenticate(self.user_internal.login, self.user_internal.login)
        with freeze_time("2025-01-01 08:00:00"):
            self._create_device_log_for_user(session, 10)

        devices, logs = self.get_devices_logs(self.user_internal)
        self.assertEqual(len(devices), 10)
        self.assertEqual(len(logs), 10)
        self.assertEqual(len(self.user_internal.device_ids), 10)

        with (
            freeze_time("2025-02-01 08:00:00"),
            patch.object(self.cr, "commit", lambda: ...),
        ):
            self.env["res.device.session"].sudo()._update_revoked()
        self.env.invalidate_all()

        devices, _ = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 0)
        self.assertEqual(len(self.user_admin.device_ids), 0)

        devices, _ = self.get_devices_logs(self.user_internal)
        self.assertEqual(len(devices), 0)
        self.assertEqual(len(self.user_internal.device_ids), 0)

    def test_specific_public_user_write(self):
        session = self.authenticate(None, None)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-public?readonly=0")

        self.assertFalse(session["_trace"])

    def test_first_activity_survives_an_ip_change(self):
        self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit(
            "2024-01-01 08:00:00",
            "/test_http/greeting-public?readonly=0",
            ip="193.0.3.43",
        )
        self.hit(
            "2024-01-01 12:00:00",
            "/test_http/greeting-public?readonly=0",
            ip="192.0.2.42",
        )
        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(logs), 2)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices.ip_address, "192.0.2.42")
        self.assertEqual(devices.first_activity, datetime(2024, 1, 1, 8, 0))
        self.assertEqual(devices.last_activity, datetime(2024, 1, 1, 12, 0))

    def _sweep_real_store(self):
        with patch.object(
            type(self.env["ir.cron"]), "_commit_progress", lambda *a, **k: float("inf")
        ):
            self.env["res.device.session"].sudo()._update_revoked()
        self.env.invalidate_all()

    def test_sweep_keeps_a_live_session(self):
        session = self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-public?readonly=0")
        self._sweep_real_store()
        devices, _logs = self.get_devices_logs(self.user_admin)
        self.assertEqual(len(devices), 1)
        self.assertTrue(devices.active)
        self.assertTrue(odoo.http.root.session_store.get(session.sid).uid)

    def test_sweep_archives_a_dead_session(self):
        session = self.authenticate(self.user_admin.login, self.user_admin.login)
        self.hit("2024-01-01 08:00:00", "/test_http/greeting-public?readonly=0")
        self.hit(
            "2024-01-01 08:00:01", "/test_http/greeting-public?readonly=0", ip=TEST_IP
        )
        devices, logs = self.get_devices_logs(self.user_admin)
        self.assertEqual((len(devices), len(logs)), (1, 2))
        odoo.http.root.session_store.delete(session)
        self._sweep_real_store()
        self.assertFalse(devices.active)
        self.assertEqual(len(devices.log_ids), 2, "the history outlives the session")
        self.assertFalse(self.user_admin.device_ids)

    def _call_kw(self, model, method, ids):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"model": model, "method": method, "args": [ids], "kwargs": {}},
        }
        return self.url_open(
            f"/web/dataset/call_kw/{model}/{method}",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        ).json()

    def test_revoking_the_current_device_reloads(self):
        session = self.authenticate(self.user_admin.login, self.user_admin.login)
        session["identity-check-last"] = time.time()
        odoo.http.root.session_store.save(session)
        self.url_open("/test_http/greeting-user?readonly=0")
        device = self.user_admin.device_ids
        self.assertEqual(len(device), 1)

        response = self._call_kw("res.device", "revoke", device.ids)

        self.assertEqual(
            response.get("result"), {"type": "ir.actions.client", "tag": "reload"}
        )
        self.assertIn("/web/login", self.url_open("/test_http/greeting-user").url)

    def test_device_log_lines_carry_no_session_identifier(self):
        session = self.authenticate(self.user_admin.login, self.user_admin.login)
        with self.assertLogs("odoo.addons.base.models.res_device", "INFO") as logs:
            self.hit("2024-01-01 08:00:00", "/test_http/greeting-user?readonly=0")
            self.user_admin.device_ids._revoke()
        self.assertEqual(len(logs.output), 2)
        identifier = session.sid[:STORED_SESSION_BYTES]
        self.assertFalse([line for line in logs.output if identifier in line])

    def test_logout_archives_the_device_at_once(self):
        self.authenticate(self.user_internal.login, self.user_internal.login)
        self.url_open("/test_http/greeting-user?readonly=0")
        device = self.user_internal.device_ids
        self.assertEqual(len(device), 1)

        self.url_open("/web/session/logout")

        self.env.invalidate_all()
        self.assertFalse(device.active)
        self.assertFalse(self.user_internal.device_ids)
        self.assertEqual(len(device.log_ids), 1, "the history outlives the session")

    def test_logout_leaves_the_other_sessions_devices(self):
        other = self.authenticate(self.user_internal.login, self.user_internal.login)
        self.url_open("/test_http/greeting-user?readonly=0")
        self.authenticate(self.user_internal.login, self.user_internal.login)
        self.url_open("/test_http/greeting-user?readonly=0")
        self.assertEqual(len(self.user_internal.device_ids), 2)

        self.url_open("/web/session/logout")

        self.env.invalidate_all()
        self.assertEqual(
            self.user_internal.device_ids.session_ids.session_identifier,
            other.sid[:STORED_SESSION_BYTES],
        )

    def _session_without_device(self, user):
        session = odoo.http.root.session_store.new()
        session.update(
            odoo.http.prepare_default_session(), db=get_db_name(), _trace_disable=True
        )
        session.uid = user.id
        session.login = user.login
        session.session_token = security.get_session_token(session, self.env)
        odoo.http.root.session_store.save(session)
        return session

    def _open_with(self, session, url):
        self.opener.cookies.set("session_id", session.sid, domain=HOST)
        return self.url_open(url)

    def test_revoke_all_ends_a_session_that_has_no_device(self):
        victim = self.authenticate(self.user_internal.login, self.user_internal.login)
        victim["identity-check-last"] = time.time()
        odoo.http.root.session_store.save(victim)
        self.url_open("/test_http/greeting-user?readonly=0")
        unlisted = self._session_without_device(self.user_internal)
        self.assertNotIn(
            "/web/login", self._open_with(unlisted, "/test_http/greeting-user").url
        )
        self.env.invalidate_all()
        self.assertEqual(len(self.user_internal.device_ids), 1, "only the victim's")

        self._open_with(victim, "/odoo")
        response = self._call_kw(
            "res.users", "action_revoke_all_devices", self.user_internal.ids
        )

        self.assertEqual(
            response.get("result"), {"type": "ir.actions.client", "tag": "reload"}
        )
        self.assertIn(
            "/web/login", self._open_with(unlisted, "/test_http/greeting-user").url
        )
        self.assertNotIn(
            "/web/login", self._open_with(victim, "/test_http/greeting-user").url
        )

    def test_login_records_the_device_of_the_session_it_keeps(self):
        self.authenticate(None, None)
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "db": get_db_name(),
                "login": self.user_internal.login,
                "password": self.user_internal.login,
            },
        }
        response = self.url_open(
            "/web/session/authenticate",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        self.assertNotIn("error", response.json())
        sid = self.opener.cookies["session_id"]

        self.env.invalidate_all()
        device = self.user_internal.device_ids
        self.assertEqual(len(device), 1)
        self.assertEqual(
            device.session_ids.session_identifier, sid[:STORED_SESSION_BYTES]
        )
        self.assertNotIn("/web/login", self.url_open("/test_http/greeting-user").url)
