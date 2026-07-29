"""DB-level integrity guards on the Core Web Vitals metric model.

``web.cwv.metric`` is anonymous-writable (the observability controller writes
beacons via ``sudo()``) and high-volume, so it must not rely on the controller
alone to clamp values: the model carries CHECK constraints and column-size caps
that hold regardless of the write path.
"""

import json
from unittest.mock import patch

from psycopg.errors import CheckViolation

from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("web_unit", "web_cwv")
class TestWebCwvMetric(TransactionCase):
    """Constraints on ``web.cwv.metric`` (latency ranges, NaN/Infinity, sizes)."""

    def _create(self, vals):
        rec = self.env["web.cwv.metric"].sudo().create(vals)
        self.env.flush_all()
        return rec

    def _assert_rejected(self, vals):
        with (
            self.assertRaises(CheckViolation),
            mute_logger("odoo.db"),
            self.cr.savepoint(),
        ):
            self._create(vals)

    def test_valid_metric_is_accepted(self):
        rec = self._create({"url": "/odoo", "lcp": 1200.0, "fcp": 900.0, "cls": 0.05})
        self.assertTrue(rec.id)

    def test_null_metrics_allowed(self):
        rec = self._create({"url": "/odoo"})
        self.assertTrue(rec.id)

    def test_negative_latency_rejected(self):
        self._assert_rejected({"url": "/odoo", "lcp": -1.0})

    def test_infinity_rejected(self):
        self._assert_rejected({"url": "/odoo", "lcp": float("inf")})

    def test_nan_rejected(self):
        self._assert_rejected({"url": "/odoo", "cls": float("nan")})

    def test_latency_over_cap_rejected(self):
        self._assert_rejected({"url": "/odoo", "ttfb": 36_000_000.0})

    def test_cls_over_cap_rejected(self):
        self._assert_rejected({"url": "/odoo", "cls": 99_999.0})

    def test_url_capped_at_db_level(self):
        rec = self._create({"url": "/" + "x" * 5000})
        self.assertLessEqual(len(rec.url), 2048)

    def test_controller_clamps_reject_non_finite(self):
        """The observability controller must never forward NaN/Infinity to the
        model (NaN slips past a naive range check, then trips the DB CHECK and
        500s the beacon endpoint). The clamps reject non-finite/bool values so
        the controller path stays constraint-safe.
        """
        from odoo.addons.web.controllers.observability import _clamp_cls, _clamp_latency

        for bad in (float("nan"), float("inf"), float("-inf"), -1.0, True):
            self.assertIsNone(
                _clamp_latency(bad), f"_clamp_latency({bad!r}) must be None"
            )
            self.assertIsNone(_clamp_cls(bad), f"_clamp_cls({bad!r}) must be None")
        self.assertEqual(_clamp_latency(1200), 1200.0)
        self.assertEqual(_clamp_cls(0.05), 0.05)

    def test_rate_limiter_key_map_stays_bounded(self):
        """A flood of distinct client keys must not grow ``_rate_state`` without
        bound. Pruning stale windows can't help when every key is fresh (spoofed
        X-Forwarded-For), so eviction hard-caps the map. The batch drops it to a
        low-water mark via ``heapq`` (O(n)) rather than re-sorting the whole map
        (O(n log n)) on every over-cap call.
        """
        from odoo.addons.web.controllers import observability as obs

        obs._rate_state.clear()
        self.addCleanup(obs._rate_state.clear)
        for i in range(obs._RATE_LIMIT_MAX_KEYS + 500):
            obs._rate_limited(f"flood:{i}")
        self.assertLessEqual(
            len(obs._rate_state),
            obs._RATE_LIMIT_MAX_KEYS,
            "the key map must stay bounded under a distinct-key flood",
        )


@tagged("-at_install", "post_install", "web_http", "web_cwv")
class TestWebCwvBeacon(HttpCase):
    """End-to-end behaviour of the /web/observability/cwv beacon controller."""

    def _beacon(self, payload):
        return self.url_open(
            "/web/observability/cwv",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )

    def test_pageview_upsert(self):
        Metric = self.env["web.cwv.metric"].sudo()
        before = Metric.search_count([])

        pid = "pageview-upsert-test"
        r1 = self._beacon({"url": "/odoo", "pageview_id": pid, "lcp": 1000.0})
        self.assertEqual(r1.status_code, 204)
        r2 = self._beacon(
            {"url": "/odoo", "pageview_id": pid, "lcp": 1000.0, "inp": 250.0}
        )
        self.assertEqual(r2.status_code, 204)

        rows = Metric.search([("pageview_id", "=", pid)])
        self.assertEqual(len(rows), 1, "one row per pageview_id")
        self.assertEqual(rows.inp, 250.0, "row updated to the latest values")
        self.assertEqual(Metric.search_count([]) - before, 1)

    def test_missing_pageview_id_always_creates(self):
        Metric = self.env["web.cwv.metric"].sudo()
        before = Metric.search_count([])
        self._beacon({"url": "/odoo", "lcp": 1100.0})
        self._beacon({"url": "/odoo", "lcp": 1200.0})
        self.assertEqual(Metric.search_count([]) - before, 2)

    def test_rate_limited_beacons_are_capped(self):
        from odoo.addons.web.controllers import observability

        Metric = self.env["web.cwv.metric"].sudo()
        observability._rate_state.clear()
        self.addCleanup(observability._rate_state.clear)
        before = Metric.search_count([])

        with patch.object(observability, "_RATE_LIMIT_MAX", 3):
            statuses = [
                self._beacon(
                    {"url": "/odoo", "pageview_id": f"rate-{i}", "lcp": 1000.0}
                ).status_code
                for i in range(6)
            ]

        self.assertEqual(
            statuses[:3], [204, 204, 204], "beacons within the cap must be accepted"
        )
        self.assertTrue(
            all(s == 429 for s in statuses[3:]),
            f"beacons over the cap must be rejected with 429, got {statuses}",
        )
        self.assertEqual(Metric.search_count([]) - before, 3)

    def test_js_error_beacon_is_rate_limited(self):
        from odoo.addons.web.controllers import observability

        observability._rate_state.clear()
        self.addCleanup(observability._rate_state.clear)

        with (
            patch.object(observability, "_RATE_LIMIT_MAX", 3),
            mute_logger("odoo.addons.web.controllers.observability"),
        ):
            statuses = [
                self.url_open(
                    "/web/observability/js_error",
                    data=json.dumps({"message": f"boom {i}", "kind": "error"}),
                    headers={"Content-Type": "application/json"},
                ).status_code
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
            status = self.url_open(
                "/web/observability/js_error",
                data=json.dumps({"message": "boot ok", "kind": "service_start"}),
                headers={"Content-Type": "application/json"},
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
            status = self.url_open(
                "/web/observability/js_error",
                data=json.dumps(
                    {"message": "bundle gone", "kind": "asset_load_error"}
                ),
                headers={"Content-Type": "application/json"},
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
                self.url_open(
                    "/web/observability/js_error",
                    data=json.dumps(
                        {
                            "message": "bundle gone",
                            "kind": "asset_load_error",
                            "reloaded": sent,
                        }
                    ),
                    headers={"Content-Type": "application/json"},
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
            self.url_open(
                "/web/observability/js_error",
                data=json.dumps({"message": "plain error"}),
                headers={"Content-Type": "application/json"},
            )
        self.assertTrue(
            any("reloaded=None" in line for line in capture.output),
            "an absent reloaded must log as None, not False",
        )

    def test_js_error_unknown_kind_falls_back_to_error(self):
        with self.assertLogs(
            "odoo.addons.web.controllers.observability", level="WARNING"
        ) as capture:
            status = self.url_open(
                "/web/observability/js_error",
                data=json.dumps({"message": "boom", "kind": "nonsense"}),
                headers={"Content-Type": "application/json"},
            ).status_code

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
            status = self.url_open(
                "/web/observability/js_error",
                data=json.dumps({"message": long_message, "kind": "error"}),
                headers={"Content-Type": "application/json"},
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
            status = self.url_open(
                "/web/observability/js_error",
                data=json.dumps(
                    {"message": "top-level failure", "kind": "error", "cause": cause}
                ),
                headers={"Content-Type": "application/json"},
            ).status_code

        self.assertEqual(status, 204)
        logged = "\n".join(capture.output)
        self.assertIn("cause=", logged)
        self.assertIn(cause[:4096], logged)
        self.assertNotIn(cause, logged, "the cause must be clamped, not sent in full")

    def test_js_error_non_string_cause_does_not_500(self):
        for bad_cause in (12345, {"nested": {"deeply": {"cause": "boom"}}}):
            status = self.url_open(
                "/web/observability/js_error",
                data=json.dumps(
                    {"message": "boom", "kind": "error", "cause": bad_cause}
                ),
                headers={"Content-Type": "application/json"},
            ).status_code
            self.assertIn(
                status,
                (204, 400),
                f"non-string cause {bad_cause!r} must not 500, got {status}",
            )

    def test_cwv_and_js_error_have_separate_budgets(self):
        from odoo.addons.web.controllers import observability as obs

        obs._rate_state.clear()
        self.addCleanup(obs._rate_state.clear)

        with (
            patch.object(obs, "_RATE_LIMIT_MAX", 2),
            mute_logger("odoo.addons.web.controllers.observability"),
        ):
            cwv = [
                self._beacon(
                    {"url": "/odoo", "pageview_id": f"sep-{i}", "lcp": 1000.0}
                ).status_code
                for i in range(3)
            ]
            err = self.url_open(
                "/web/observability/js_error",
                data=json.dumps({"message": "boom", "kind": "error"}),
                headers={"Content-Type": "application/json"},
            ).status_code

        self.assertEqual(cwv, [204, 204, 429], "CWV budget must be exhausted")
        self.assertEqual(
            err, 204, "js_error has its own budget, not starved by CWV volume"
        )
