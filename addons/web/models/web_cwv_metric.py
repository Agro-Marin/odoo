"""Core Web Vitals metric records — Recommendation #9 (Phases 2-3).

Each row is a single beacon emitted by ``services/web_vitals/web_vitals_service.js``
and persisted via ``controllers/observability.py``.  Data is high-volume,
write-only-from-controller, and read-only-from-UI; the controller writes via
``sudo()`` because beacons can arrive from anonymous frontend visitors.

Phase 3 added a daily retention cron (``_gc_old_metrics``) driven by the
``web.cwv.retention_days`` config parameter (default 30).  Pre-aggregation
into a daily summary model is a separate phase — wait until volume warrants
the indirection.
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class WebCwvMetric(models.Model):
    _name = "web.cwv.metric"
    _description = "Core Web Vitals Metric"
    _order = "recorded_at desc"
    # _log_access = False: skip create_uid/create_date/write_uid/write_date — RUM
    # is append-only and high-volume; the four bookkeeping columns add ~32 bytes
    # per row and one index for nothing useful.  We capture the moment the
    # beacon was received via the explicit ``recorded_at`` field below.
    _log_access = False

    recorded_at = fields.Datetime(
        string="Recorded At",
        required=True,
        default=fields.Datetime.now,
        index=True,
        readonly=True,
    )
    url = fields.Char(
        string="URL",
        required=True,
        size=2048,
        index="btree",
        readonly=True,
        help="Browser path at the time the beacon fired (the query string is "
        "stripped before persisting).  May be the same path for many records.  "
        "Capped at 2048 chars at the DB level so a rogue writer cannot bloat "
        "the row.",
    )
    user_id = fields.Many2one(
        "res.users",
        string="User",
        index="btree_not_null",
        ondelete="set null",
        readonly=True,
        help="User logged in when the beacon fired; null for anonymous "
        "frontend traffic.",
    )
    # Latency metrics, all in milliseconds.  Float not Integer because the
    # browser's PerformanceObserver reports sub-millisecond values.
    lcp = fields.Float(
        string="LCP (ms)",
        readonly=True,
        help="Largest Contentful Paint — time from navigation start to the "
        "render of the largest visible element.  Lighthouse 'good' is < 2500.",
    )
    fcp = fields.Float(
        string="FCP (ms)",
        readonly=True,
        help="First Contentful Paint — time from navigation start to first "
        "text/image paint.  Lighthouse 'good' is < 1800.",
    )
    ttfb = fields.Float(
        string="TTFB (ms)",
        readonly=True,
        help="Time To First Byte — time from request start to the first "
        "byte of the response.  Lighthouse 'good' is < 800.",
    )
    inp = fields.Float(
        string="INP (ms)",
        readonly=True,
        help="Interaction to Next Paint — reported as the worst-observed "
        "interaction duration over the page lifetime (P100), a strict upper "
        "bound on the canonical P98 metric.  Vendoring the web-vitals library "
        "for a true P98 is a future improvement; the wire format won't change.",
    )
    cls = fields.Float(
        string="CLS",
        readonly=True,
        help="Cumulative Layout Shift — unitless score (0 is best).  "
        "Lighthouse 'good' is < 0.1.",
    )
    user_agent = fields.Char(
        string="User Agent",
        size=512,
        readonly=True,
        help="Truncated to 500 chars at the controller; the 512-char DB cap is "
        "a backstop for any other write path.",
    )
    pageview_id = fields.Char(
        string="Pageview ID",
        size=64,
        readonly=True,
        index=True,
        help="Client-generated id, stable for one page load. Metrics arrive "
        "across several beacons as INP/CLS keep growing after the first "
        "tab-switch; the controller upserts on this key so a pageview "
        "contributes one row (updated to the latest values) instead of "
        "accumulating duplicates.",
    )

    # ------------------------------------------------------------------ #
    # Integrity                                                          #
    # ------------------------------------------------------------------ #
    # DB-level guards so the table stays sane regardless of the write path.
    # The controller is the only writer today and clamps values, but a single
    # point of validation is fragile for an anonymous-writable, high-volume
    # table.  The upper bounds also reject NaN/Infinity that a ``double
    # precision`` column would otherwise accept: in PostgreSQL ``NaN`` and
    # ``Infinity`` are greater than every finite number, so ``x <= cap`` is
    # FALSE for them and the CHECK fails.  NULLs are allowed (e.g. ``inp`` is
    # not captured yet), since a NULL comparison is never FALSE.
    _check_latency_range = models.Constraint(
        "CHECK("
        " (lcp  IS NULL OR (lcp  >= 0 AND lcp  <= 3600000))"
        " AND (fcp  IS NULL OR (fcp  >= 0 AND fcp  <= 3600000))"
        " AND (ttfb IS NULL OR (ttfb >= 0 AND ttfb <= 3600000))"
        " AND (inp  IS NULL OR (inp  >= 0 AND inp  <= 3600000))"
        ")",
        "Core Web Vitals latencies must be between 0 and 3600000 ms.",
    )
    _check_cls_range = models.Constraint(
        "CHECK(cls IS NULL OR (cls >= 0 AND cls <= 1000))",
        "Cumulative Layout Shift must be between 0 and 1000.",
    )

    # ------------------------------------------------------------------ #
    # Retention                                                          #
    # ------------------------------------------------------------------ #

    @api.model
    def _gc_old_metrics(self):
        """Daily cron — delete CWV records older than the retention window.

        Reads the ``web.cwv.retention_days`` ``ir.config_parameter`` (default
        ``30``).  A value of ``0`` disables retention (the cron becomes a
        no-op) — useful for environments that pipe beacons to an external
        TSDB and only need the model as a transit buffer.

        Deletion is unbounded (one DELETE statement); on a 30-day window of
        sampled data this is well under a million rows even on busy sites
        and finishes in seconds.  If volume ever requires bounded batching,
        switch to ``self.with_context(active_test=False).search([...]).unlink()``
        with a ``LIMIT`` and a follow-up cron retry.
        """
        days_str = self.env["ir.config_parameter"].sudo().get_param(
            "web.cwv.retention_days", "30",
        )
        try:
            days = int(days_str)
        except (TypeError, ValueError):
            _logger.warning(
                "web.cwv.retention_days=%r is not an integer; skipping GC",
                days_str,
            )
            return
        if days <= 0:
            return
        # Use raw SQL: model has no audit columns and no automatic write/unlink
        # hooks worth invoking; the table is append-only by design.  Avoids the
        # ORM cost of materialising and unlinking potentially-large recordsets.
        # ``recorded_at`` is a stored Odoo Datetime: naive ``timestamp`` in UTC.
        # ``now()`` is ``timestamptz``; comparing the two coerces ``recorded_at``
        # via the *session* TimeZone (which Odoo never sets to UTC), shifting the
        # cutoff by the server's UTC offset. Anchor the cutoff in UTC — matching
        # ``cr.now()`` (``now() AT TIME ZONE 'UTC'``) — so the retention window is
        # exact regardless of the cluster timezone.
        self.env.cr.execute(
            "DELETE FROM web_cwv_metric"
            " WHERE recorded_at < (now() AT TIME ZONE 'UTC') - (%s * interval '1 day')",
            (days,),
        )
        deleted = self.env.cr.rowcount
        if deleted:
            _logger.info(
                "[cwv-gc] deleted %d rows older than %d day(s)",
                deleted,
                days,
            )
