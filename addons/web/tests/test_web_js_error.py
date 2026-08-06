"""Tests for the JS error beacon: /web/observability/js_error → web.js.error."""

import json
from unittest.mock import patch

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger


@tagged("-at_install", "post_install", "web_http", "web_js_error")
class TestWebJsErrorBeacon(HttpCase):
    """Behaviour of the /web/observability/js_error controller, plus
    ``web.js.error``'s retention sweep, which is exercised through the model.
    """

    def _beacon(self, payload):
        return self.url_open(
            "/web/observability/js_error",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )

    def test_js_error_beacon_is_rate_limited(self):
        from odoo.addons.web.controllers import observability

        observability._rate_state.clear()
        self.addCleanup(observability._rate_state.clear)

        with (
            patch.object(observability, "_RATE_LIMIT_MAX", 3),
            mute_logger("odoo.addons.web.controllers.observability"),
        ):
            statuses = [
                self._beacon({"message": f"boom {i}", "kind": "error"}).status_code
                for i in range(6)
            ]

        self.assertEqual(
            statuses[:3], [204, 204, 204], "beacons within the cap must be accepted"
        )
        self.assertTrue(
            all(s == 429 for s in statuses[3:]),
            f"js_error beacons over the cap must be rejected with 429, got {statuses}",
        )

    def test_js_error_service_start_kind_logged_verbatim(self):
        with self.assertLogs(
            "odoo.addons.web.controllers.observability", level="WARNING"
        ) as capture:
            status = self._beacon(
                {"message": "boot ok", "kind": "service_start"}
            ).status_code

        self.assertEqual(status, 204)
        self.assertTrue(
            any("kind=service_start" in line for line in capture.output),
            "service_start must be logged verbatim, not coerced to error",
        )

    def test_js_error_asset_load_error_kind_logged_verbatim(self):
        with self.assertLogs(
            "odoo.addons.web.controllers.observability", level="WARNING"
        ) as capture:
            status = self._beacon(
                {"message": "bundle gone", "kind": "asset_load_error"}
            ).status_code

        self.assertEqual(status, 204)
        self.assertTrue(
            any("kind=asset_load_error" in line for line in capture.output),
            "the loader has always sent this kind; it must stop being coerced",
        )

    def test_js_error_reloaded_flag_is_logged(self):
        """``reloaded`` separates a page that self-healed from one that stayed
        broken, so both values must reach the log distinctly."""
        for sent, expected in ((True, "reloaded=True"), (False, "reloaded=False")):
            with self.assertLogs(
                "odoo.addons.web.controllers.observability", level="WARNING"
            ) as capture:
                self._beacon(
                    {
                        "message": "bundle gone",
                        "kind": "asset_load_error",
                        "reloaded": sent,
                    }
                )
            self.assertTrue(
                any(expected in line for line in capture.output),
                f"expected {expected} in the log line",
            )

    def test_js_error_absent_reloaded_logs_none(self):
        """Every other kind omits the field; it must not read as False, which
        would claim a reload was suppressed when none was ever attempted."""
        with self.assertLogs(
            "odoo.addons.web.controllers.observability", level="WARNING"
        ) as capture:
            self._beacon({"message": "plain error"})
        self.assertTrue(
            any("reloaded=None" in line for line in capture.output),
            "an absent reloaded must log as None, not False",
        )

    def test_js_error_persists_a_row(self):
        self._beacon(
            {
                "message": "persisted probe",
                "kind": "service_start",
                "phase": "pre_boot",
                "cause": "Caused by: TypeError: boom",
                "stack": "at svc (svc.js:1:1)",
                "url": "http://localhost/web/login",
            }
        )
        row = self.env["web.js.error"].search(
            [("message", "=", "persisted probe")], limit=1
        )
        self.assertTrue(row, "the beacon must land in web.js.error")
        self.assertEqual(row.kind, "service_start")
        self.assertEqual(row.phase, "pre_boot")
        self.assertEqual(row.cause, "Caused by: TypeError: boom")
        self.assertFalse(row.reloaded, "no reloaded was sent, so it stays unset")

    def test_js_error_reloaded_maps_to_selection(self):
        """The wire sends a bool; the model stores a tristate so that 'not
        applicable' stays distinguishable from 'the reload was suppressed'."""
        for sent, expected in ((True, "reloaded"), (False, "suppressed")):
            message = f"reload probe {sent}"
            self._beacon(
                {
                    "message": message,
                    "kind": "asset_load_error",
                    "reloaded": sent,
                }
            )
            row = self.env["web.js.error"].search([("message", "=", message)], limit=1)
            self.assertEqual(row.reloaded, expected)

    def test_js_error_rate_limited_beacon_persists_nothing(self):
        """A 429 must not leave a row behind, or the rate limit would cap the
        log while the table grew unbounded."""
        from odoo.addons.web.controllers import observability

        # _rate_state is process-global: clear it on both sides or this test
        # poisons the budget for whatever runs next in the same worker.
        observability._rate_state.clear()
        self.addCleanup(observability._rate_state.clear)

        Model = self.env["web.js.error"]
        before = Model.search_count([])
        with patch.object(observability, "_RATE_LIMIT_MAX", 2):
            statuses = [
                self._beacon({"message": f"rl probe {i}"}).status_code for i in range(4)
            ]

        self.assertEqual(statuses, [204, 204, 429, 429])
        self.assertEqual(
            Model.search_count([]) - before,
            2,
            "only the accepted beacons may persist",
        )

    def test_js_error_empty_message_persists_nothing(self):
        before = self.env["web.js.error"].search_count([])
        status = self._beacon({"message": ""}).status_code
        self.assertEqual(status, 204)
        self.assertEqual(self.env["web.js.error"].search_count([]), before)

    def test_js_error_gc_respects_retention_days(self):
        Model = self.env["web.js.error"]
        Model._record_beacon({"message": "old row", "kind": "error"})
        self.env.cr.execute(
            "UPDATE web_js_error SET recorded_at = (now() AT TIME ZONE 'UTC')"
            " - interval '90 days' WHERE message = 'old row'"
        )
        param = self.env["ir.config_parameter"].sudo()

        # 0 disables retention entirely — the transit-buffer case.
        param.set_param("web.js_error.retention_days", "0")
        Model._gc_old_errors()
        self.assertTrue(Model.search([("message", "=", "old row")]))

        param.set_param("web.js_error.retention_days", "30")
        Model._gc_old_errors()
        self.assertFalse(Model.search([("message", "=", "old row")]))

    def test_js_error_unknown_kind_falls_back_to_error(self):
        with self.assertLogs(
            "odoo.addons.web.controllers.observability", level="WARNING"
        ) as capture:
            status = self._beacon({"message": "boom", "kind": "nonsense"}).status_code

        self.assertEqual(status, 204)
        self.assertTrue(
            any("kind=error" in line for line in capture.output),
            "an unknown kind must still fall back to error",
        )
        self.assertFalse(
            any("kind=nonsense" in line for line in capture.output),
            "widening the kind tuple must not open it to arbitrary strings",
        )

    def test_js_error_message_truncated_to_4096(self):
        long_message = "x" * 5000
        with self.assertLogs(
            "odoo.addons.web.controllers.observability", level="WARNING"
        ) as capture:
            status = self._beacon(
                {"message": long_message, "kind": "error"}
            ).status_code

        self.assertEqual(status, 204)
        logged = "\n".join(capture.output)
        self.assertNotIn("x" * 5000, logged)
        self.assertIn("x" * 4096, logged)

    def test_js_error_cause_is_clamped_and_logged(self):
        cause = "Caused by: TypeError: boom " * 200  # well over 4096 chars
        with self.assertLogs(
            "odoo.addons.web.controllers.observability", level="WARNING"
        ) as capture:
            status = self._beacon(
                {"message": "top-level failure", "kind": "error", "cause": cause}
            ).status_code

        self.assertEqual(status, 204)
        logged = "\n".join(capture.output)
        self.assertIn("cause=", logged)
        self.assertIn(cause[:4096], logged)
        self.assertNotIn(cause, logged, "the cause must be clamped, not sent in full")

    def test_js_error_non_string_cause_does_not_500(self):
        for bad_cause in (12345, {"nested": {"deeply": {"cause": "boom"}}}):
            status = self._beacon(
                {"message": "boom", "kind": "error", "cause": bad_cause}
            ).status_code
            self.assertIn(
                status,
                (204, 400),
                f"non-string cause {bad_cause!r} must not 500, got {status}",
            )
