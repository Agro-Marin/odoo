"""Observability endpoints — Real User Monitoring (RUM) beacons.

Receives Core Web Vitals beacons from ``services/web_vitals/web_vitals_service.js``
and persists them to ``web.cwv.metric`` for dashboards (list/pivot/graph views
under Settings → Technical → Performance → Core Web Vitals).  A short ``[cwv]``
INFO log line is also emitted per beacon as an ops-debug signal that does not
require a DB query to inspect.

Recommendation #9 in
``knowledge/research/2026-04-28-web-module-js-architecture-assessment.md`` —
Phase 1 (this controller) + Phase 2 (queryable model + dashboard).
"""

import logging
import math
import threading
import time

from odoo import modules
from odoo.http import Controller, Response, request, route
from odoo.libs.json import loads as json_loads
from odoo.tools import config

_logger = logging.getLogger(__name__)

# Per-client rate limit for the public CWV beacon.  The endpoint is
# ``auth="public"`` + ``csrf=False`` and persists a row per (novel)
# ``pageview_id``, so an anonymous caller forging fresh ids could amplify
# ``INSERT``s without bound.  A cheap in-process fixed-window counter caps how
# many beacons one client (keyed by remote address) may turn into DB writes per
# window.  The window is generous relative to real traffic — ``web_vitals``
# sends only a small burst per pageview via ``navigator.sendBeacon`` on
# ``pagehide`` — so legitimate beacons are never dropped; only abusive volume is.
# The state is per worker process (best-effort DoS mitigation, not a hard global
# quota) and self-prunes to stay bounded.
_RATE_LIMIT_WINDOW_S = 60
_RATE_LIMIT_MAX = 120
_RATE_LIMIT_MAX_KEYS = 10_000
_rate_lock = threading.Lock()
# key -> [window_start_monotonic, count_in_window]
_rate_state: dict[str, list[float]] = {}


def _rate_limited(key: str) -> bool:
    """Return ``True`` when *key* has exceeded its beacon budget this window."""
    now = time.monotonic()
    with _rate_lock:
        # Opportunistic prune so a churn of distinct client keys (e.g. spoofed
        # sources) can't grow the map without bound.
        if len(_rate_state) > _RATE_LIMIT_MAX_KEYS:
            cutoff = now - _RATE_LIMIT_WINDOW_S
            for stale in [k for k, v in _rate_state.items() if v[0] < cutoff]:
                del _rate_state[stale]
            # Pruning stale entries is not enough on its own: a flood of
            # distinct *fresh* keys (e.g. spoofed X-Forwarded-For, all within
            # the window) leaves nothing stale to evict. Hard-cap by dropping
            # the oldest windows so the map size is bounded unconditionally.
            # Evicting a live key merely resets that client's counter — an
            # acceptable trade for a best-effort limiter that must stay bounded.
            if len(_rate_state) > _RATE_LIMIT_MAX_KEYS:
                overflow = len(_rate_state) - _RATE_LIMIT_MAX_KEYS
                for k in sorted(_rate_state, key=lambda k: _rate_state[k][0])[
                    :overflow
                ]:
                    del _rate_state[k]
        state = _rate_state.get(key)
        if state is None or now - state[0] >= _RATE_LIMIT_WINDOW_S:
            _rate_state[key] = [now, 1]
            return False
        if state[1] >= _RATE_LIMIT_MAX:
            return True
        state[1] += 1
        return False


# Sanity bounds — values outside these are dropped as garbage (typically from
# bots, devtools-paused tabs, or buggy browsers).  The thresholds are well
# above any reasonable real-user metric.
_MAX_LATENCY_MS = 60_000  # 60 s — anything longer is a stuck page or bot
_MAX_CLS = 5.0  # Lighthouse "poor" is 0.25; > 5 is wildly broken
_MAX_URL_LEN = 500
_MAX_UA_LEN = 500
_MAX_ERROR_MSG_LEN = 1_000
_MAX_ERROR_STACK_LEN = 4_096
_MAX_ERROR_FILENAME_LEN = 500


def _clamp_latency(value):
    """Return ``value`` if it looks like a valid latency in ms, else ``None``."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not math.isfinite(value):
        # NaN slips past the range check below (every comparison with NaN is
        # False), and the model now rejects non-finite values at the DB level —
        # drop them here so a bogus beacon is silently ignored, not a 500.
        return None
    if value < 0 or value > _MAX_LATENCY_MS:
        return None
    return float(value)


def _clamp_cls(value):
    """Return ``value`` if it looks like a valid CLS score, else ``None``."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not math.isfinite(value):
        return None
    if value < 0 or value > _MAX_CLS:
        return None
    return float(value)


class Observability(Controller):
    """Web client observability endpoints."""

    @route(
        "/web/observability/cwv",
        type="http",
        auth="public",
        sitemap=False,
        methods=["POST"],
        csrf=False,
    )
    def cwv(self) -> Response:
        """Receive a Core Web Vitals beacon and persist it.

        Body is a JSON object with optional fields ``lcp``, ``fcp``, ``cls``,
        ``ttfb``, ``inp`` (numbers in ms or unitless for CLS), plus ``url``
        and ``user_agent`` strings for context.  The endpoint validates
        ranges, drops garbage, emits a ``[cwv]``-tagged INFO log line per
        beacon, and creates a row in ``web.cwv.metric``.

        ``csrf=False`` because ``navigator.sendBeacon`` cannot carry a CSRF
        token (no header control on the Blob path).  The endpoint is purely
        write-only and the validation drops malformed input, so the lack of
        CSRF here does not expand the attack surface meaningfully.

        Beacons are rate-limited per client so an anonymous caller cannot
        amplify DB inserts; ``navigator.sendBeacon`` ignores the response, so a
        429 is invisible to legitimate senders. The key prefers the
        authenticated ``session.uid`` (the CWV population is the backend
        webclient, where every user is logged in) so that many users behind one
        shared egress IP — corporate NAT, or a reverse proxy without
        ``proxy_mode`` collapsing ``remote_addr`` to the proxy — each get their
        own budget instead of starving a single shared bucket. Genuinely
        anonymous callers fall back to ``remote_addr``.
        """
        uid = request.session.uid
        client_key = (
            f"uid:{uid}" if uid else f"ip:{request.httprequest.remote_addr or 'anon'}"
        )
        if _rate_limited(client_key):
            return Response("", status=429, mimetype="text/plain")

        try:
            payload = json_loads(request.httprequest.data or b"{}")
        except ValueError, TypeError:
            return Response("invalid json", status=400, mimetype="text/plain")

        if not isinstance(payload, dict):
            return Response("invalid payload", status=400, mimetype="text/plain")

        lcp = _clamp_latency(payload.get("lcp"))
        fcp = _clamp_latency(payload.get("fcp"))
        ttfb = _clamp_latency(payload.get("ttfb"))
        inp = _clamp_latency(payload.get("inp"))
        cls = _clamp_cls(payload.get("cls"))
        # Strip the query string before logging/persisting: ``location.search``
        # can carry record ids and other PII that RUM does not need — only the
        # route/path is useful for Web-Vitals aggregation. The first-party
        # client (web_vitals_service) already sends ``location.pathname`` only;
        # this strip is defense-in-depth for stale cached clients and
        # hand-crafted beacons (the endpoint is CSRF-exempt and public).
        raw_url = payload.get("url")
        if isinstance(raw_url, str):
            url = raw_url.split("?", 1)[0][:_MAX_URL_LEN]
        else:
            url = ""
        user_agent = (
            (payload.get("user_agent") or "")[:_MAX_UA_LEN]
            if isinstance(payload.get("user_agent"), str)
            else ""
        )
        raw_pageview = payload.get("pageview_id")
        pageview_id = raw_pageview[:64] if isinstance(raw_pageview, str) else ""

        # Drop completely empty beacons (no metric survived validation).
        if lcp is None and fcp is None and ttfb is None and cls is None and inp is None:
            return Response("", status=204)

        # ``url`` is required by the model.  Drop a beacon without one — should
        # never happen from our own service but cheap to guard against.
        if not url:
            return Response("", status=204)

        uid = request.session.uid or False
        _logger.info(
            "[cwv] uid=%s url=%r lcp=%s fcp=%s cls=%s ttfb=%s inp=%s ua=%r",
            uid or "anon",
            url,
            lcp,
            fcp,
            cls,
            ttfb,
            inp,
            user_agent,
        )
        # sudo() — anonymous frontend traffic has no write access on
        # web.cwv.metric.  RUM beacons should not be lost based on caller ACL.
        Metric = request.env["web.cwv.metric"].sudo()
        values = {
            "url": url,
            "user_id": uid,
            "lcp": lcp,
            "fcp": fcp,
            "cls": cls,
            "ttfb": ttfb,
            "inp": inp,
            "user_agent": user_agent or False,
            "pageview_id": pageview_id or False,
        }
        # Upsert on pageview_id: a single pageview beacons several times as
        # INP/CLS keep growing (web_vitals_service), so the latest values
        # replace the existing row instead of accumulating one row per beacon.
        # ``_record_beacon`` does this atomically (INSERT ... ON CONFLICT on the
        # partial unique index), so two workers beaconing the same pageview
        # cannot race into duplicate rows. Empty pageview_id (old clients)
        # stores NULL and never conflicts, so it always inserts as before.
        Metric._record_beacon(values)
        return Response("", status=204)

    @route(
        "/web/observability/js_error",
        type="http",
        auth="public",
        sitemap=False,
        methods=["POST"],
        csrf=False,
    )
    def js_error(self) -> Response:
        """Receive a JS error beacon from ``module_loader.js``.

        Payload fields (all optional, all clamped to per-field length caps):
        ``phase`` (``"pre_boot"`` | ``"post_boot"``), ``kind`` (``"error"`` |
        ``"unhandledrejection"`` | ``"module_rebind"``), ``message``, ``filename``,
        ``line``,
        ``col``, ``stack``, ``url``, ``user_agent``.

        Logs each beacon as ``[js_error]`` at WARNING.  Persistence
        (``web.js.error`` model + queryable dashboard) is intentionally
        deferred to a follow-up phase; the log is enough for operators to
        spot post-deploy regressions via the existing log pipeline.

        ``csrf=False`` because ``navigator.sendBeacon`` cannot carry a CSRF
        token; the endpoint is purely write-only. The first-party client
        rate-limits itself (one beacon per ``(message,line,col)`` per page
        lifetime), but a hostile caller ignores that, so the server also
        applies the same per-client fixed-window cap as ``cwv`` — each beacon
        emits a WARNING log line and must not be amplifiable without bound.
        The client key prefers ``session.uid`` (see ``cwv``) so users sharing an
        egress IP don't collapse into one bucket; anonymous callers fall back to
        ``remote_addr``.
        """
        uid = request.session.uid
        client_key = (
            f"uid:{uid}" if uid else f"ip:{request.httprequest.remote_addr or 'anon'}"
        )
        if _rate_limited(client_key):
            return Response("", status=429, mimetype="text/plain")

        try:
            payload = json_loads(request.httprequest.data or b"{}")
        except ValueError, TypeError:
            return Response("invalid json", status=400, mimetype="text/plain")

        if not isinstance(payload, dict):
            return Response("invalid payload", status=400, mimetype="text/plain")

        def _str_field(raw, cap):
            return (str(raw)[:cap]) if isinstance(raw, str) else ""

        def _int_field(raw):
            return int(raw) if isinstance(raw, (int, float)) and raw >= 0 else 0

        message = _str_field(payload.get("message"), _MAX_ERROR_MSG_LEN)
        if not message:
            # Empty-message beacons carry no signal; drop silently.
            return Response("", status=204)

        kind = (
            payload.get("kind")
            if payload.get("kind") in ("error", "unhandledrejection", "module_rebind")
            else "error"
        )
        phase = (
            payload.get("phase")
            if payload.get("phase") in ("pre_boot", "post_boot")
            else "unknown"
        )
        filename = _str_field(payload.get("filename"), _MAX_ERROR_FILENAME_LEN)
        url = _str_field(payload.get("url"), _MAX_URL_LEN)
        user_agent = _str_field(payload.get("user_agent"), _MAX_UA_LEN)
        stack = _str_field(payload.get("stack"), _MAX_ERROR_STACK_LEN)
        line = _int_field(payload.get("line"))
        col = _int_field(payload.get("col"))

        uid = request.session.uid or False
        # A module-rebind beacon is production telemetry for accidental bundle
        # duplication (a real signal → WARNING). Under tests the test-asset
        # overlay legitimately rebinds prod modules onto the same names, so those
        # beacons are expected noise (DEBUG) — while genuine JS errors stay loud
        # even in tests.
        in_test = bool(modules.module.current_test) or config["test_enable"]
        level = (
            logging.DEBUG if kind == "module_rebind" and in_test else logging.WARNING
        )
        _logger.log(
            level,
            "[js_error] uid=%s phase=%s kind=%s msg=%r at %s:%d:%d url=%r ua=%r stack=%r",
            uid or "anon",
            phase,
            kind,
            message,
            filename,
            line,
            col,
            url,
            user_agent,
            stack,
        )
        return Response("", status=204)
