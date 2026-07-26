"""Response-building helpers for :class:`~odoo.http.Request`.

Mixed into Request via :class:`_RequestResponseMixin`. Provides
``make_response``/``make_json_response`` constructors, redirect helpers
that defang external URLs when ``local=True``, lazy QWeb ``render``,
and the WSGI-environ rewriting ``reroute``.
"""

from __future__ import annotations

import threading
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
    """Response constructors and redirect/render/reroute helpers for Request.

    The ``Request`` state it reads is declared by
    :class:`~odoo.http._protocols.RequestState`.
    """

    def make_response(
        self,
        data: str | bytes | None,
        headers: list[tuple[str, str]] | werkzeug.datastructures.Headers | None = None,
        cookies: Mapping[str, str] | None = None,
        status: int = 200,
    ) -> Response:
        """Helper for non-HTML responses, or HTML responses with custom
        response headers or cookies.

        Handlers may return a page's HTML markup directly as a string; for
        non-HTML data they must build a complete response object, or clients
        will not interpret the returned data correctly.

        :param str data: response body
        :param int status: http status code
        :param headers: HTTP headers to set on the response
        :type headers: ``[(name, value)]``
        :param collections.abc.Mapping cookies: cookies to set on the client
        :returns: a response object.
        :rtype: :class:`~odoo.http.Response`
        """
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
        """Helper for JSON responses, it json-serializes ``data`` and
        sets the Content-Type header accordingly if none is provided.

        :param data: the data that will be json-serialized into the response body
        :param int status: http status code
        :param list[tuple[str, str]] headers: HTTP headers to set on the response
        :param collections.abc.Mapping cookies: cookies to set on the client
        :rtype: :class:`~odoo.http.Response`
        """
        data = _fast_dumps_bytes(data, default=orjson_default)

        headers = werkzeug.datastructures.Headers(headers)
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json; charset=utf-8"

        return self.make_response(data, headers, cookies, status)

    def not_found(self, description: str | None = None) -> NotFound:
        """Shortcut for a `HTTP 404
        <http://tools.ietf.org/html/rfc7231#section-6.5.4>`_ (Not Found)
        response
        """
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
        """Lazy render of a QWeb template.

        The actual rendering of the given template will occur at the end of
        the dispatching. Meanwhile, the template and/or qcontext can be
        altered or even replaced by a static response.

        :param str template: template to render
        :param dict qcontext: Rendering context to use
        :param bool lazy: whether the template rendering should be deferred
                          until the last possible moment
        :param dict kw: forwarded to werkzeug's Response object
        """
        response = Response(template=template, qcontext=qcontext, **kw)
        if not lazy:
            return response.render()
        return response

    def reroute(self, path: str | bytes, query_string: str | None = None) -> None:
        """
        Rewrite the current request URL using the new path and query
        string. This acts as a light redirection: it does not return a
        3xx response to the browser but still changes the current URL.
        """
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
