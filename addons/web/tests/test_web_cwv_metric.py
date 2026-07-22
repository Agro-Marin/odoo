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
        self.env.flush_all()  # force the INSERT so CHECK constraints fire here
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
        # Every vital may be null (e.g. ``inp`` is not captured yet).
        rec = self._create({"url": "/odoo"})
        self.assertTrue(rec.id)

    def test_negative_latency_rejected(self):
        self._assert_rejected({"url": "/odoo", "lcp": -1.0})

    def test_infinity_rejected(self):
        # A ``double precision`` column accepts Infinity; the upper-bound CHECK
        # rejects it (``Infinity <= cap`` is FALSE in PostgreSQL).
        self._assert_rejected({"url": "/odoo", "lcp": float("inf")})

    def test_nan_rejected(self):
        self._assert_rejected({"url": "/odoo", "cls": float("nan")})

    def test_latency_over_cap_rejected(self):
        self._assert_rejected({"url": "/odoo", "ttfb": 36_000_000.0})

    def test_cls_over_cap_rejected(self):
        self._assert_rejected({"url": "/odoo", "cls": 99_999.0})

    def test_url_capped_at_db_level(self):
        # Oversized URLs are bounded (truncated to the column size), never stored
        # unbounded — defends the table against bloat from a rogue writer.
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
        # Several beacons for one pageview (INP/CLS grow after the first
        # tab-switch) must collapse to ONE row, updated to the latest values,
        # not accumulate duplicates.
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
        # Old clients send no pageview_id: each beacon still creates a row
        # (previous behaviour preserved).
        Metric = self.env["web.cwv.metric"].sudo()
        before = Metric.search_count([])
        self._beacon({"url": "/odoo", "lcp": 1100.0})
        self._beacon({"url": "/odoo", "lcp": 1200.0})
        self.assertEqual(Metric.search_count([]) - before, 2)

    def test_rate_limited_beacons_are_capped(self):
        # An anonymous caller must not amplify DB inserts without bound: once a
        # client exceeds its per-window budget, further beacons are rejected
        # (429) before touching the DB. The legit beacon (a small burst per
        # pageview) stays well under the cap and is unaffected.
        from odoo.addons.web.controllers import observability

        Metric = self.env["web.cwv.metric"].sudo()
        # Isolate this test from any accumulated per-IP count, and leave a clean
        # slate for the sibling beacon tests.
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
        # Only the accepted beacons produced rows; the rejected ones never hit
        # the DB.
        self.assertEqual(Metric.search_count([]) - before, 3)

    def test_js_error_beacon_is_rate_limited(self):
        # The js_error beacon logs a WARNING per request and is public +
        # csrf-exempt, so it must be server-side rate-limited just like cwv —
        # otherwise an anonymous caller can flood the log pipeline without
        # bound. (Its own docstring previously claimed only client-side dedup.)
        from odoo.addons.web.controllers import observability

        observability._rate_state.clear()
        self.addCleanup(observability._rate_state.clear)

        with patch.object(observability, "_RATE_LIMIT_MAX", 3):
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

    def test_cwv_and_js_error_have_separate_budgets(self):
        # The two public beacon endpoints are namespaced per route, so a client
        # that exhausts its CWV budget can still send JS-error beacons (and vice
        # versa) — one endpoint's volume must not starve the other's bucket.
        from odoo.addons.web.controllers import observability as obs

        obs._rate_state.clear()
        self.addCleanup(obs._rate_state.clear)

        with patch.object(obs, "_RATE_LIMIT_MAX", 2):
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
