# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.http import Controller, request, route, SessionExpiredException
from odoo.libs.json import dumps as json_dumps
from ..models.bus import channel_with_db
from ..websocket import WebsocketConnectionHandler


class WebsocketController(Controller):
    @route('/websocket', type="http", auth="public", cors='*', websocket=True)
    def websocket(self, version=None):
        """
        Handle the websocket handshake, upgrade the connection if successfull.

        :param version: The version of the WebSocket worker that tries to
            connect. Connections with an outdated version will result in the
            websocket being closed. See :attr:`WebsocketConnectionHandler._VERSION`.
        """
        return WebsocketConnectionHandler.open_connection(request, version)

    @route('/websocket/health', type='http', auth='none', save_session=False)
    def health(self):
        data = json_dumps({
            'status': 'pass',
        })
        headers = [('Content-Type', 'application/json'),
                   ('Cache-Control', 'no-store')]
        return request.make_response(data, headers)

    @route('/websocket/peek_notifications', type='jsonrpc', auth='public', cors='*')
    def peek_notifications(self, channels, last, is_first_poll=False):
        if is_first_poll:
            # Used to detect when the current session is expired.
            request.session['is_websocket_session'] = True
        elif 'is_websocket_session' not in request.session:
            raise SessionExpiredException()
        subscribe_data = request.env["ir.websocket"]._prepare_subscribe_data(channels, last)
        request.env["ir.websocket"]._after_subscribe_data(subscribe_data)
        channels_with_db = [channel_with_db(request.db, c) for c in subscribe_data["channels"]]
        notifications = request.env["bus.bus"]._poll(channels_with_db, subscribe_data["last"])
        return {"channels": channels_with_db, "notifications": notifications}

    @route("/websocket/on_closed", type="jsonrpc", auth="public", cors="*")
    def on_websocket_closed(self):
        """Manually notify the closure of a websocket, useful when implementing custom websocket code.
        This is mainly used by Odoo.sh."""
        request.env["ir.websocket"]._on_websocket_closed(request.cookies)

    @route('/bus/websocket_worker_bundle', type='http', auth='public')
    def get_websocket_worker_bundle(self, v=None):  # pylint: disable=unused-argument
        """
        Serve the compiled websocket worker bundle.

        :param str v: Cache-busting version token (ignored server-side).

        CORS: We handle CORS manually rather than via the route ``cors='*'``
        decorator because ``Access-Control-Allow-Origin: *`` is forbidden by
        the CORS spec when the request carries credentials (session cookie).
        In prefork mode the HTTP workers (port 8069) and the gevent/WebSocket
        server (port 8072) have different origins, so the JS client fetches
        this bundle cross-origin *with* credentials so the gevent server can
        resolve the active database.  When an ``Origin`` header is present we
        echo it back and add ``Access-Control-Allow-Credentials: true``.
        Note: ``cors='*'`` writes to ``future_response`` in ``pre_dispatch``
        and is merged via ``extend`` in ``post_dispatch`` — it cannot be
        overridden from within a controller, hence the manual approach here.
        """
        bundle_name = 'bus.websocket_worker_assets'
        bundle = request.env["ir.qweb"]._get_asset_bundle(bundle_name, debug_assets="assets" in request.session.debug)
        stream = request.env['ir.binary']._get_stream_from(bundle.js())
        response = stream.get_response(content_security_policy=None)
        origin = request.httprequest.headers.get('Origin')
        if origin:
            # Credentials are present: wildcard is forbidden, echo the origin.
            # Vary: Origin is required so caches keep per-origin copies.
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Vary'] = 'Origin'
        else:
            response.headers['Access-Control-Allow-Origin'] = '*'
        return response
