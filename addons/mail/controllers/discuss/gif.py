import hashlib
import logging
from urllib.parse import urlencode

import requests
from werkzeug.exceptions import BadRequest

from odoo.http import Controller, request, route

# The proxied provider is Klipy (api.klipy.com); the constants kept the Tenor
# name from a previous integration, which was misleading.
KLIPY_CONTENT_FILTER = "medium"
KLIPY_GIF_LIMIT = 8

_logger = logging.getLogger(__name__)


class DiscussGifController(Controller):
    def _gif_client_key(self):
        """A stable, opaque per-database identifier for the GIF provider's
        rate-limiting ``client_key``. Previously we sent ``cr.dbname`` verbatim,
        disclosing the internal database name to a third party; a hash gives the
        provider the same stable-per-tenant key without leaking the name."""
        return hashlib.sha256(request.env.cr.dbname.encode()).hexdigest()[:32]

    def _request_gifs(self, endpoint):
        response = None
        try:
            response = requests.get(f"https://api.klipy.com/v2/{endpoint}", timeout=3)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            # covers ConnectionError, HTTPError AND Timeout (not a subclass of the
            # first two) — an unhandled Timeout previously surfaced as a raw 500.
            _logger.error("Klipy GIF API request failed: %s", e)

        if not response:
            raise BadRequest
        return response

    @route("/discuss/gif/search", type="jsonrpc", auth="user", readonly=True)
    def search(self, search_term, locale="en", country="US", position=None):
        # sudo: ir.config_parameter - read keys are hard-coded and values are only used for server requests
        ir_config = request.env["ir.config_parameter"].sudo()
        query_string = urlencode(
            {
                "q": search_term,
                "key": ir_config.get_param("discuss.klipy_api_key"),
                "client_key": self._gif_client_key(),
                "limit": KLIPY_GIF_LIMIT,
                "contentfilter": KLIPY_CONTENT_FILTER,
                "locale": locale,
                "country": country,
                "media_filter": "tinygif",
                "pos": position,
            }
        )
        return self._request_gifs(f"search?{query_string}").json()

    @route("/discuss/gif/categories", type="jsonrpc", auth="user", readonly=True)
    def categories(self, locale="en", country="US"):
        # sudo: ir.config_parameter - read keys are hard-coded and values are only used for server requests
        ir_config = request.env["ir.config_parameter"].sudo()
        query_string = urlencode(
            {
                "key": ir_config.get_param("discuss.klipy_api_key"),
                "client_key": self._gif_client_key(),
                "limit": KLIPY_GIF_LIMIT,
                "contentfilter": KLIPY_CONTENT_FILTER,
                "locale": locale,
                "country": country,
            }
        )
        return self._request_gifs(f"categories?{query_string}").json()

    @route("/discuss/gif/add_favorite", type="jsonrpc", auth="user")
    def add_favorite(self, tenor_gif_id):
        request.env["discuss.gif.favorite"].create({"tenor_gif_id": tenor_gif_id})

    def _gif_posts(self, ids):
        # sudo: ir.config_parameter - read keys are hard-coded and values are only used for server requests
        ir_config = request.env["ir.config_parameter"].sudo()
        query_string = urlencode(
            {
                "ids": ",".join(ids) or None,
                "key": ir_config.get_param("discuss.klipy_api_key"),
                "client_key": self._gif_client_key(),
                "media_filter": "tinygif",
            }
        )
        return self._request_gifs(f"posts?{query_string}").json()["results"]

    @route("/discuss/gif/favorites", type="jsonrpc", auth="user", readonly=True)
    def get_favorites(self, offset=0):
        tenor_gif_ids = request.env["discuss.gif.favorite"].search(
            [("create_uid", "=", request.env.user.id)], limit=20, offset=offset
        )
        if not tenor_gif_ids.mapped("tenor_gif_id"):
            return ([],)
        return (self._gif_posts(tenor_gif_ids.mapped("tenor_gif_id")) or [],)

    @route("/discuss/gif/remove_favorite", type="jsonrpc", auth="user")
    def remove_favorite(self, tenor_gif_id):
        request.env["discuss.gif.favorite"].search(
            [
                ("create_uid", "=", request.env.user.id),
                ("tenor_gif_id", "=", tenor_gif_id),
            ]
        ).unlink()
