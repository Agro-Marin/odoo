from odoo.http import (
    Controller,
    SessionExpiredException,
    cors_same_host,
    request,
    route,
)
from odoo.libs.json import dumps as json_dumps

from ..models.bus import channel_with_db, dispatch
from ..websocket import WebsocketConnectionHandler


class WebsocketController(Controller):
    @route("/websocket", type="http", auth="public", cors="*", websocket=True)
    def websocket(self, version=None):
        """
        Handle the websocket handshake, upgrade the connection if successfull.

        :param version: The version of the WebSocket worker that tries to
            connect. Connections with an outdated version will result in the
            websocket being closed. See :attr:`WebsocketConnectionHandler._VERSION`.
        """
        return WebsocketConnectionHandler.open_connection(request, version)

    @route("/websocket/health", type="http", auth="none", save_session=False)
    def health(self):
        """Report whether this node can actually deliver bus notifications.

        This used to answer ``{"status": "pass"}`` unconditionally, which only
        ever proved that the WSGI stack was up -- a node whose ``ImDispatch``
        thread had died kept advertising itself as healthy and kept being sent
        websocket traffic it could never dispatch.

        ``dispatch.is_healthy`` deliberately reports a *never started*
        dispatcher as healthy: the thread starts lazily on the first
        subscriber, so probing ``is_alive()`` directly would fail every
        freshly booted server until someone connected. A shutting-down server
        reports "fail" so it drains out of the pool before it stops answering.
        """
        healthy = dispatch.is_healthy
        data = json_dumps({"status": "pass" if healthy else "fail"})
        headers = [("Content-Type", "application/json"), ("Cache-Control", "no-store")]
        # 503 so a load balancer / orchestrator acts on it without having to
        # parse the body (draft-inadarei-api-health-check conventions).
        return request.make_response(data, headers, status=200 if healthy else 503)

    @route("/websocket/peek_notifications", type="jsonrpc", auth="public", cors="*")
    def peek_notifications(self, channels, last, is_first_poll=False):
        if is_first_poll:
            # Used to detect when the current session is expired.
            request.session["is_websocket_session"] = True
        elif "is_websocket_session" not in request.session:
            raise SessionExpiredException
        subscribe_data = request.env["ir.websocket"]._prepare_subscribe_data(
            channels, last
        )
        request.env["ir.websocket"]._after_subscribe_data(subscribe_data)
        channels_with_db = [
            channel_with_db(request.db, c) for c in subscribe_data["channels"]
        ]
        notifications = request.env["bus.bus"]._poll(
            channels_with_db, subscribe_data["last"]
        )
        return {"channels": channels_with_db, "notifications": notifications}

    @route("/websocket/on_closed", type="jsonrpc", auth="public", cors="*")
    def on_websocket_closed(self):
        """Manually notify the closure of a websocket, useful when implementing custom websocket code.
        This is mainly used by Odoo.sh."""
        request.env["ir.websocket"]._on_websocket_closed(request.cookies)

    @route(
        "/bus/websocket_worker_bundle",
        type="http",
        auth="public",
        cors=cors_same_host,
        cors_credentials=True,
    )
    def get_websocket_worker_bundle(self, v=None):  # pylint: disable=unused-argument
        """
        Serve the compiled, self-contained websocket worker bundle.

        :param str v: Cache-busting version token (ignored server-side).

        The response is served with ETag revalidation (no ``max-age``): the
        worker graph's individual static files are cached for a week by the
        browser, so serving raw files here would keep tabs booting week-old
        worker code after an upgrade — invisible to the OUTDATED_VERSION
        check, whose version comes from the fresh page session, not from the
        stale worker. A worker boots once per browser session, so the
        conditional request is negligible.

        CORS: ``cors=cors_same_host, cors_credentials=True``. In prefork mode the
        HTTP workers (port 8069) and the gevent/WebSocket server (port 8072) have
        different origins, so the JS client fetches this bundle cross-origin
        *with* credentials and boots the worker from a blob: URL — which is also
        why the bundle must be a SINGLE file: module workers cannot resolve
        relative imports against a blob URL. ``Access-Control-Allow-Origin: *``
        is forbidden by the CORS spec once credentials are sent, and the
        framework refuses that pair outright, so the resolver narrows the echo to
        origins on this deployment's own host — the ports that actually need it —
        instead of every site on the internet.
        """
        bundle = request.env["ir.qweb"]._get_websocket_worker_bundle()
        if bundle:
            url, code = bundle
            response = request.make_response(
                code,
                [
                    ("Content-Type", "text/javascript; charset=utf-8"),
                    ("Cache-Control", "no-cache"),
                ],
            )
            # The URL's path segment is the content hash — a ready-made,
            # build-stable ETag.
            response.set_etag(url.rsplit("/", 2)[-2])
            response.make_conditional(request.httprequest)
        else:
            # Degraded path (esbuild declined): serve the raw ESM entry point;
            # the browser resolves its relative imports from the static file
            # path. Same-origin workers only — the cross-origin blob path
            # cannot work without a bundled file.
            response = request.redirect("/bus/static/src/workers/bus_worker_script.js")
        return response
