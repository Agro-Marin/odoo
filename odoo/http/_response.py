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

from odoo.libs.json import dumps as _fast_dumps
from odoo.tools.json import orjson_default

from .wrappers import HTTPRequest, Response


class _RequestResponseMixin:
    """Response constructors and redirect/render/reroute helpers for Request.

    Reads/writes ``self.httprequest``, ``self.env``, ``self.db``.
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

        While handlers can just return the HTML markup of a page they want to
        send as a string if non-HTML data is returned they need to create a
        complete response object, or the returned data will not be correctly
        interpreted by the clients.

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
        data = _fast_dumps(data, default=orjson_default)

        # Don't pre-set Content-Length: ``data`` is a ``str``, so ``len(data)`` is
        # a char count, but werkzeug computes the byte length on serialize and
        # overrides it anyway.
        headers = werkzeug.datastructures.Headers(headers)
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json; charset=utf-8"

        # Pass the ``Headers`` object straight through (not ``to_wsgi_list()``):
        # werkzeug keeps a ``Headers`` as-is, so flattening to a list just to have
        # it rebuilt is wasted work on this hot path.
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
        # Gate the ORM-backed redirect on ``env`` not ``db``: on the error path
        # ``_serve_db``'s ``finally`` nulls ``env`` while ``db`` stays set (e.g.
        # the SessionExpired branch redirects here), and ``self.env["ir.http"]``
        # would raise. The plain werkzeug redirect skips website/portal rewriting
        # but is the right degradation while the request is unwinding an error.
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
            # A MultiDict (e.g. ``request.httprequest.args``, forwarded by every
            # lang-ladder redirect in http_routing) holds repeated keys, but its
            # ``items()`` yields one value per key and ``urlencode`` consumes it
            # as a plain mapping -- ``?attrib=1&attrib=2`` would collapse to
            # ``?attrib=1``. Flatten to pairs first.
            if isinstance(query, werkzeug.datastructures.MultiDict):
                query = list(query.items(multi=True))
            # Per RFC 3986 the query must precede the fragment. Append ?<query>
            # to the pre-'#' part, then reattach #<fragment>; otherwise
            # /foo#bar + ?a=b yields /foo#bar?a=b and the server never sees ?a=b.
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
        string. This act as a light redirection, it does not return a
        3xx responses to the browser but still change the current URL.
        """
        # WSGI encoding dance (PEP 3333): re-encode UTF-8 then decode latin-1, so
        # every byte maps to one char. latin-1 covers all bytes 0-255, so strict
        # decode never fails.
        if isinstance(path, str):
            path = path.encode("utf-8")
        path = path.decode("latin1")

        if query_string is None:
            query_string = self.httprequest.environ["QUERY_STRING"]

        # Change the WSGI environment
        environ = self.httprequest.raw_environ.copy()
        environ["PATH_INFO"] = path
        environ["QUERY_STRING"] = query_string
        environ["RAW_URI"] = f"{path}?{query_string}"
        # REQUEST_URI left as-is so it still contains the original URI

        # Create and expose a new request from the modified WSGI env
        httprequest = HTTPRequest(environ)
        threading.current_thread().url = httprequest.url
        self.httprequest = httprequest
