"""Observability endpoints — Real User Monitoring (RUM) beacons.

Receives Core Web Vitals beacons from ``services/web_vitals/web_vitals_service.js``
and persists them to ``web.cwv.metric`` for dashboards (list/pivot/graph views
under Settings → Technical → Observability → Core Web Vitals).  A short ``[cwv]``
INFO log line is also emitted per beacon as an ops-debug signal that does not
require a DB query to inspect.

Recommendation #9 in
``knowledge/research/2026-04-28-web-module-js-architecture-assessment.md`` —
Phase 1 (this controller) + Phase 2 (queryable model + dashboard).
"""

import heapq
import logging
import math
import threading
import time

from odoo import modules
from odoo.http import Controller, Response, request, route
from odoo.libs.json import loads as json_loads
from odoo.tools import config

_logger = logging.getLogger(__name__)

_RATE_LIMIT_WINDOW_S = 60
_RATE_LIMIT_MAX = 120
_RATE_LIMIT_MAX_KEYS = 10_000
_rate_lock = threading.Lock()
_rate_state: dict[str, list[float]] = {}


def _rate_limited(key: str) -> bool:
    """Return ``True`` when *key* has exceeded its beacon budget this window."""
    now = time.monotonic()
    with _rate_lock:
        if len(_rate_state) > _RATE_LIMIT_MAX_KEYS:
            cutoff = now - _RATE_LIMIT_WINDOW_S
            for stale in [k for k, v in _rate_state.items() if v[0] < cutoff]:
                del _rate_state[stale]
            if len(_rate_state) > _RATE_LIMIT_MAX_KEYS:
                low_water = _RATE_LIMIT_MAX_KEYS * 9 // 10
                evict_n = len(_rate_state) - low_water
                for k in heapq.nsmallest(
                    evict_n, _rate_state, key=lambda k: _rate_state[k][0]
                ):
                    del _rate_state[k]
        state = _rate_state.get(key)
        if state is None or now - state[0] >= _RATE_LIMIT_WINDOW_S:
            _rate_state[key] = [now, 1]
            return False
        if state[1] >= _RATE_LIMIT_MAX:
            return True
        state[1] += 1
        return False


def _client_rate_key(prefix: str) -> str:
    """Per-route rate-limit key: prefer the authenticated uid, else remote addr.

    ``prefix`` namespaces the two beacon endpoints so a page emitting both CWV
    and JS-error beacons doesn't draw them from a single shared budget — one
    endpoint's volume must not starve the other. The uid preference keeps many
    users behind one shared egress IP (corporate NAT, proxy without
    ``proxy_mode``) from collapsing into a single bucket; anonymous callers fall
    back to ``remote_addr``.
    """
    uid = request.session.uid
    ident = f"uid:{uid}" if uid else f"ip:{request.httprequest.remote_addr or 'anon'}"
    return f"{prefix}:{ident}"


_MAX_LATENCY_MS = 60_000
_MAX_CLS = 5.0
_MAX_URL_LEN = 500
_MAX_UA_LEN = 500
# Matches _MAX_ERROR_STACK_LEN. 1000 truncated real client messages: an
# aggregate assertion dump or a stringified payload runs long, and the tail is
# where the specifics are. The `cause` chain has its own cap below.
_MAX_ERROR_MSG_LEN = 4_096
_MAX_ERROR_STACK_LEN = 4_096
_MAX_ERROR_CAUSE_LEN = 4_096
_MAX_ERROR_FILENAME_LEN = 500

# The js_error taxonomy the client is allowed to send, kept in step with the
# beacon emitters under web/static/src (error_beacon.js, module_loader.js,
# boot_failure_overlay.js). ``TestJsErrorTaxonomy`` asserts every emitted
# kind/phase appears here, so a newly-emitted one cannot silently degrade to
# ``"error"`` / ``"unknown"`` -- which is what hid asset-load failures and
# boot-mount failures, the two most operationally interesting of them.
_JS_ERROR_KINDS = frozenset(
    {
        "error",
        "unhandledrejection",
        "module_rebind",
        "service_start",
        "asset_load_error",
    }
)
_JS_ERROR_PHASES = frozenset({"pre_boot", "post_boot", "boot_mount_failed"})


def _clamp_latency(value):
    """Return ``value`` if it looks like a valid latency in ms, else ``None``."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not math.isfinite(value):
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
        client_key = _client_rate_key("cwv")
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

        if lcp is None and fcp is None and ttfb is None and cls is None and inp is None:
            return Response("", status=204)

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
        """Receive a JS error beacon from ``module_loader.js``, ``error_beacon.js``
        or ``boot_failure_overlay.js``.

        Payload fields (all optional, all clamped to per-field length caps):
        ``phase`` (``_JS_ERROR_PHASES``: ``pre_boot`` | ``post_boot`` |
        ``boot_mount_failed``), ``kind`` (``_JS_ERROR_KINDS``: ``error`` |
        ``unhandledrejection`` | ``module_rebind`` | ``service_start`` |
        ``asset_load_error``), ``message``, ``cause``, ``filename``, ``line``,
        ``col``, ``stack``, ``url``, ``user_agent``, and ``reloaded``
        (``asset_load_error`` only — whether the loader's self-heal reload
        fired or the once-a-minute guard suppressed it).

        Logs each beacon as ``[js_error]`` at WARNING and persists it to
        ``web.js.error`` (list/form under Settings → Technical → Observability
        → JS Errors).
        The log line stays because it needs no DB query to inspect and
        survives even when the write fails; the model is what makes a
        post-deploy regression greppable by kind, phase and cause instead of
        by log scraping.

        ``csrf=False`` because ``navigator.sendBeacon`` cannot carry a CSRF
        token; the endpoint is purely write-only. The first-party client
        rate-limits itself (one beacon per
        ``(message,line,col,hash(stack+cause))`` per page lifetime), but a
        hostile caller ignores that, so the server also
        applies the same per-client fixed-window cap as ``cwv`` — each beacon
        emits a WARNING log line and must not be amplifiable without bound.
        The client key prefers ``session.uid`` (see ``cwv``) so users sharing an
        egress IP don't collapse into one bucket; anonymous callers fall back to
        ``remote_addr``.
        """
        client_key = _client_rate_key("js_error")
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
            return Response("", status=204)

        kind = (
            payload.get("kind") if payload.get("kind") in _JS_ERROR_KINDS else "error"
        )
        phase = (
            payload.get("phase")
            if payload.get("phase") in _JS_ERROR_PHASES
            else "unknown"
        )
        filename = _str_field(payload.get("filename"), _MAX_ERROR_FILENAME_LEN)
        url = _str_field(payload.get("url"), _MAX_URL_LEN)
        user_agent = _str_field(payload.get("user_agent"), _MAX_UA_LEN)
        stack = _str_field(payload.get("stack"), _MAX_ERROR_STACK_LEN)
        cause = _str_field(payload.get("cause"), _MAX_ERROR_CAUSE_LEN)
        line = _int_field(payload.get("line"))
        col = _int_field(payload.get("col"))
        # Only asset_load_error carries this: it says whether the loader's
        # one-per-minute self-heal reload actually fired or was suppressed by
        # the guard, which is the difference between a page that recovered and
        # one that stayed broken.
        reloaded = bool(payload.get("reloaded")) if "reloaded" in payload else None

        uid = request.session.uid or False
        in_test = bool(modules.module.current_test) or config["test_enable"]
        level = (
            logging.DEBUG if kind == "module_rebind" and in_test else logging.WARNING
        )
        _logger.log(
            level,
            "[js_error] uid=%s phase=%s kind=%s reloaded=%s msg=%r cause=%r"
            " at %r:%d:%d url=%r ua=%r stack=%r",
            uid or "anon",
            phase,
            kind,
            reloaded,
            message,
            cause,
            filename,
            line,
            col,
            url,
            user_agent,
            stack,
        )
        # sudo(): beacons arrive from anonymous frontend visitors too, and the
        # model is deliberately unreachable to everyone but base.group_system.
        # The per-client rate limit above is what bounds the insert volume.
        request.env["web.js.error"].sudo()._record_beacon(
            {
                "user_id": uid,
                "phase": phase,
                "kind": kind,
                "message": message,
                "cause": cause,
                "stack": stack,
                "filename": filename,
                "line": line,
                "col": col,
                "url": url,
                "user_agent": user_agent,
                "reloaded": (
                    None
                    if reloaded is None
                    else ("reloaded" if reloaded else "suppressed")
                ),
            }
        )
        return Response("", status=204)
