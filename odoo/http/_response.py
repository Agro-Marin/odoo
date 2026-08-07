from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import werkzeug.datastructures
import werkzeug.utils
from werkzeug.exceptions import NotFound

from odoo.libs.json import dumps_bytes as _fast_dumps_bytes
from odoo.libs.worker_thread import current_worker_thread
from odoo.tools.json import orjson_default

from ._protocols import RequestState
from .wrappers import HTTPRequest, Response


class _RequestResponseMixin(RequestState):
    def make_response(
        self,
        data: str | bytes | None,
        headers: list[tuple[str, str]] | werkzeug.datastructures.Headers | None = None,
        cookies: Mapping[str, str] | None = None,
        status: int = 200,
    ) -> Response:
        response = Response(data, status=status, headers=headers)
        if cookies:
            for k, v in cookies.items():
                response.set_cookie(k, v)
        return response

    def make_json_response(
        self,
        data: Any,
        headers: list[tuple[str, str]] | None = None,
        cookies: Mapping[str, str] | None = None,
        status: int = 200,
    ) -> Response:
        data = _fast_dumps_bytes(data, default=orjson_default)

        headers = werkzeug.datastructures.Headers(headers)
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json; charset=utf-8"

        return self.make_response(data, headers, cookies, status)

    def not_found(self, description: str | None = None) -> NotFound:
        return NotFound(description)

    def redirect(self, location: str, code: int = 303, local: bool = True) -> Response:
        if local:
            location = "/" + urlunsplit(
                urlsplit(location)._replace(scheme="", netloc="")
            ).lstrip("/\\")
        if self.db and self.env is not None:
            return self.env["ir.http"]._redirect(location, code)
        return werkzeug.utils.redirect(location, code, Response=Response)

    def redirect_query(
        self,
        location: str,
        query: dict[str, str] | None = None,
        code: int = 303,
        local: bool = True,
    ) -> Response:
        if query:
            if isinstance(query, werkzeug.datastructures.MultiDict):
                query = list(query.items(multi=True))
            pre, hash_, fragment = location.partition("#")
            separator = "&" if "?" in pre else "?"
            pre += separator + urlencode(query)
            location = pre + hash_ + fragment
        return self.redirect(location, code=code, local=local)

    def render(
        self,
        template: str,
        qcontext: dict[str, Any] | None = None,
        lazy: bool = True,
        **kw: Any,
    ) -> Response:
        response = Response(template=template, qcontext=qcontext, **kw)
        if not lazy:
            return response.render()
        return response

    def reroute(self, path: str | bytes, query_string: str | None = None) -> None:
        if isinstance(path, str):
            path = path.encode("utf-8")
        path = path.decode("latin1")

        if query_string is None:
            query_string = self.httprequest.environ["QUERY_STRING"]

        environ = self.httprequest.raw_environ.copy()
        environ["PATH_INFO"] = path
        environ["QUERY_STRING"] = query_string
        environ["RAW_URI"] = f"{path}?{query_string}" if query_string else path

        httprequest = HTTPRequest(environ)
        httprequest._adopt_body_state(self.httprequest)
        current_worker_thread().url = httprequest.url
        self.httprequest = httprequest
