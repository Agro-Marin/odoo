"""DB-level integrity guards on the Core Web Vitals metric model.

``web.cwv.metric`` is anonymous-writable (the observability controller writes
beacons via ``sudo()``) and high-volume, so it must not rely on the controller
alone to clamp values: the model carries CHECK constraints and column-size caps
that hold regardless of the write path.
"""

from psycopg.errors import CheckViolation

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("web_unit", "web_cwv")
class TestWebCwvMetric(TransactionCase):
    """Constraints on ``web.cwv.metric`` (latency ranges, NaN/Infinity, sizes)."""

    def _create(self, vals):
        rec = self.env["web.cwv.metric"].sudo().create(vals)
        self.env.flush_all()  # force the INSERT so CHECK constraints fire here
        return rec

    def _assert_rejected(self, vals):
        with self.assertRaises(CheckViolation), mute_logger("odoo.sql_db", "odoo.db"), self.cr.savepoint():
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
            self.assertIsNone(_clamp_latency(bad), f"_clamp_latency({bad!r}) must be None")
            self.assertIsNone(_clamp_cls(bad), f"_clamp_cls({bad!r}) must be None")
        self.assertEqual(_clamp_latency(1200), 1200.0)
        self.assertEqual(_clamp_cls(0.05), 0.05)
