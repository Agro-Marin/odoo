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
        payload = _fast_dumps_bytes(data, default=orjson_default)

        json_headers = werkzeug.datastructures.Headers(headers)
        if "Content-Type" not in json_headers:
            json_headers["Content-Type"] = "application/json; charset=utf-8"

        return self.make_response(payload, json_headers, cookies, status)

    def not_found(self, description: str | None = None) -> NotFound:
        return NotFound(description)

    def redirect(self, location: str, code: int = 303, local: bool = True) -> Response:
        if local:
            try:
                stripped = urlsplit(location)._replace(scheme="", netloc="")
            except ValueError:
                # `urlsplit` raises "Invalid IPv6 URL" on an unbalanced bracket,
                # and this is fed straight from a query parameter --
                # `auth_signup.web_login` passes `request.params.get("redirect")`
                # and `auth_oauth` does the same -- so `/web/login?redirect=http://[`
                # was a 500 on the login flow. Measured against a real server.
                #
                # The root is not a new answer invented for this case: a hostile
                # absolute URL with no path already lands there, because
                # `https://evil.com` splits to an empty path and this builds
                # `"/" + ""`. A location with nothing local that can be recovered
                # from it goes where every other such location goes.
                location = "/"
            else:
                location = "/" + urlunsplit(stripped).lstrip("/\\")
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
            pairs: Any = (
                list(query.items(multi=True))
                if isinstance(query, werkzeug.datastructures.MultiDict)
                else query
            )
            pre, hash_, fragment = location.partition("#")
            separator = "&" if "?" in pre else "?"
            pre += separator + urlencode(pairs)
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
            # `flatten` renders into the body and clears the template, so an
            # eager render still answers the `Response` this is annotated to
            # return. It used to hand back the raw bytes of `render()`.
            response.flatten()
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
