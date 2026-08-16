import hashlib
import logging
from urllib.parse import urlencode

import requests
from werkzeug.exceptions import BadRequest

from odoo.http import Controller, request, route

KLIPY_CONTENT_FILTER = "medium"
KLIPY_GIF_LIMIT = 8

_logger = logging.getLogger(__name__)


class DiscussGifController(Controller):
    def _gif_client_key(self) -> str:
        return hashlib.sha256(request.env.cr.dbname.encode()).hexdigest()[:32]

    def _request_gifs(self, endpoint: str) -> requests.Response:
        response = None
        try:
            response = requests.get(f"https://api.klipy.com/v2/{endpoint}", timeout=3)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            _logger.error("Klipy GIF API request failed: %s", e)

        if not response:
            raise BadRequest
        return response

    @route("/discuss/gif/search", type="jsonrpc", auth="user", readonly=True)
    def search(
        self,
        search_term: str,
        locale: str = "en",
        country: str = "US",
        position: str | None = None,
    ) -> dict:
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
    def categories(self, locale: str = "en", country: str = "US") -> dict:
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
    def add_favorite(self, tenor_gif_id: str) -> None:
        request.env["discuss.gif.favorite"].create({"tenor_gif_id": tenor_gif_id})

    def _gif_posts(self, ids: list[str]) -> list:
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
    def get_favorites(self, offset: int = 0) -> tuple:
        tenor_gif_ids = request.env["discuss.gif.favorite"].search(
            [("create_uid", "=", request.env.user.id)], limit=20, offset=offset
        )
        if not tenor_gif_ids.mapped("tenor_gif_id"):
            return ([],)
        return (self._gif_posts(tenor_gif_ids.mapped("tenor_gif_id")) or [],)

    @route("/discuss/gif/remove_favorite", type="jsonrpc", auth="user")
    def remove_favorite(self, tenor_gif_id: str) -> None:
        request.env["discuss.gif.favorite"].search(
            [
                ("create_uid", "=", request.env.user.id),
                ("tenor_gif_id", "=", tenor_gif_id),
            ]
        ).unlink()
