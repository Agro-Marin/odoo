import functools
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import werkzeug.datastructures
import werkzeug.exceptions
import werkzeug.wrappers
from werkzeug.exceptions import HTTPException

from odoo.libs._vendor.useragents import UserAgent
from odoo.libs.facade import Proxy, ProxyAttr, ProxyFunc

from .constants import DEFAULT_MAX_CONTENT_LENGTH
from .core import request

_logger = logging.getLogger(__name__)


def _apply_cookie_defaults(
    expires: datetime | int | None,
    max_age: int | None,
    cookie_type: str,
    secure: bool | None,
    samesite: str | None,
) -> tuple[datetime | int | None, int | None, bool, str | None]:
    """Apply shared ``set_cookie`` defaults: expiry fallback, consent filtering
    and security attributes. Shared by :class:`_Response` and
    :class:`FutureResponse`.

    ``secure`` defaults to ``request.httprequest.is_secure`` and ``samesite`` to
    ``"Lax"``, so no cookie leaves the server without Secure / SameSite when they
    apply.
    """
    if expires == -1:  # not provided → default 1 year
        # Timezone-aware: werkzeug's ``http_date`` treats a naive datetime as
        # UTC, so a naive ``datetime.now()`` shifted the Expires header by the
        # server's UTC offset (6h early on a UTC-6 host).
        expires = datetime.now(tz=UTC) + timedelta(days=365)

    # Guard on ``env`` not ``db``: ``_is_allowed_cookie`` is an ``ir.http`` (ORM)
    # call needing a live env. They diverge on the error path, where
    # ``_serve_db``'s ``finally`` nulled ``env`` but ``db`` is still set. The only
    # cookie set env-less is ``session_id`` (``cookie_type="required"``), always
    # allowed, so skipping the consent check there is correct.
    if (
        request
        and request.env is not None
        and not request.env["ir.http"]._is_allowed_cookie(cookie_type)
    ):
        max_age = 0

    if secure is None:
        secure = bool(request and request.httprequest.is_secure)
    if samesite is None:
        samesite = "Lax"

    return expires, max_age, secure, samesite


def make_request_wrap_methods(attr: str) -> tuple[Any, Any]:
    """Create getter/setter pair proxying to the wrapped werkzeug Request."""

    def getter(self: HTTPRequest) -> Any:
        return getattr(self._HTTPRequest__wrapped, attr)

    def setter(self: HTTPRequest, value: Any) -> None:
        return setattr(self._HTTPRequest__wrapped, attr, value)

    return getter, setter


class HTTPRequest:
    def __init__(self, environ: dict[str, Any]) -> None:
        httprequest = werkzeug.wrappers.Request(environ)
        httprequest.user_agent_class = (
            UserAgent  # vendored: werkzeug removed its built-in parser
        )
        httprequest.parameter_storage_class = werkzeug.datastructures.ImmutableMultiDict
        httprequest.max_content_length = DEFAULT_MAX_CONTENT_LENGTH
        # Werkzeug 3.1 capped these at 500 KB / 1000 parts; Odoo needs more for
        # base64 fields, HTML and import data, and One2many forms can exceed 1000
        # parts (e.g. 200 invoice lines x 5+ fields each).
        httprequest.max_form_memory_size = 10 * 1024 * 1024
        httprequest.max_form_parts = 10_000

        self.__wrapped = httprequest
        self.__environ = self.__wrapped.environ
        self.environ = self.headers.environ = {
            key: value
            for key, value in self.__environ.items()
            if (
                not key.startswith(("werkzeug.", "wsgi.", "socket"))
                or key in ["wsgi.url_scheme", "werkzeug.proxy_fix.orig"]
            )
        }

    @property
    def session_id(self) -> str | None:
        """Value of the ``session_id`` cookie on the incoming request."""
        return self.__wrapped.cookies.get("session_id")

    @property
    def raw_environ(self) -> dict[str, Any]:
        """The original, unfiltered WSGI environ.

        Use for low-level operations (:meth:`Request.reroute`) that need
        the werkzeug/wsgi keys filtered out of :attr:`environ`.
        """
        return self.__environ

    def __enter__(self) -> HTTPRequest:
        return self


HTTPREQUEST_ATTRIBUTES = [
    "__str__",
    "__repr__",
    "__exit__",
    "accept_charsets",
    "accept_encodings",
    "accept_languages",
    "accept_mimetypes",
    "access_route",
    "args",
    "authorization",
    "base_url",
    "cache_control",
    "close",
    "content_encoding",
    "content_length",
    "content_md5",
    "content_type",
    "cookies",
    "data",
    "date",
    "files",
    "form",
    "full_path",
    "get_data",
    "get_json",
    "headers",
    "host",
    "host_url",
    "if_match",
    "if_modified_since",
    "if_none_match",
    "if_range",
    "if_unmodified_since",
    "input_stream",
    "is_json",
    "is_secure",
    "json",
    "max_content_length",
    "method",
    "mimetype",
    "mimetype_params",
    "origin",
    "path",
    "pragma",
    "query_string",
    "range",
    "referrer",
    "remote_addr",
    "remote_user",
    "root_path",
    "root_url",
    "scheme",
    "script_root",
    "server",
    "stream",
    "trusted_hosts",
    "url",
    "url_root",
    "user_agent",
    "values",
]
for attr in HTTPREQUEST_ATTRIBUTES:
    setattr(HTTPRequest, attr, property(*make_request_wrap_methods(attr)))


class _Response(werkzeug.wrappers.Response):
    """
    Outgoing HTTP response with body, status, headers and qweb support.
    In addition to the :class:`werkzeug.wrappers.Response` parameters,
    this class's constructor can take the following additional
    parameters for QWeb Lazy Rendering.

    :param str template: template to render
    :param dict qcontext: Rendering context to use
    :param int uid: User id to use for the ir.ui.view render call,
        ``None`` to use the request's user (the default)

    these attributes are available as parameters on the Response object
    and can be altered at any time before rendering

    Also exposes all the attributes and methods of
    :class:`werkzeug.wrappers.Response`.
    """

    default_mimetype = "text/html"

    def __init__(self, *args: Any, **kw: Any) -> None:
        template = kw.pop("template", None)
        qcontext = kw.pop("qcontext", None)
        uid = kw.pop("uid", None)
        super().__init__(*args, **kw)
        self.set_default(template, qcontext, uid)

    @classmethod
    def load(cls, result: Any, fname: str = "<function>") -> Response:
        """
        Convert the return value of an endpoint into a Response.

        :param result: The endpoint return value to load the Response from.
        :type result: Response | werkzeug.wrappers.Response |
            werkzeug.exceptions.HTTPException | str | bytes | None
        :param str fname: The endpoint function name wherefrom the
            result emanated, used for logging.
        :returns: The created :class:`~odoo.http.Response`.
        :rtype: Response
        :raises TypeError: When ``result`` type is none of the above-
            mentioned type.
        """
        if isinstance(result, Response):
            return result

        if isinstance(result, werkzeug.exceptions.HTTPException):
            _logger.warning("%s returns an HTTPException instead of raising it.", fname)
            raise result

        if isinstance(result, werkzeug.wrappers.Response):
            # Wrap in the facade like every other branch: a raw ``_Response``
            # fails ``isinstance(x, Response)`` (ProxyMeta has no
            # ``__instancecheck__``), so a facade-typed check downstream —
            # e.g. ``Json2Dispatcher.dispatch`` deciding pass-through vs
            # re-serialization — would silently misroute it.
            response = cls.force_type(result)
            response.set_default()
            return Response(response)

        if isinstance(result, (bytes, str, type(None))):
            return Response(result)

        raise TypeError(
            f"{fname} returns an invalid value: {result!r}. type='http' routes "
            "return str/bytes/None/Response; for a dict or list, return "
            "request.make_json_response(...) or use a jsonrpc/json2 route."
        )

    def set_default(
        self,
        template: str | None = None,
        qcontext: dict[str, Any] | None = None,
        uid: int | None = None,
    ) -> None:
        self.template = template
        self.qcontext = qcontext or {}
        self.qcontext["response_template"] = self.template
        self.uid = uid

    @property
    def is_qweb(self) -> bool:
        return self.template is not None

    def render(self) -> bytes:
        """Render the Response's template and return the result."""
        self.qcontext["request"] = request
        return request.env["ir.ui.view"]._render_template(self.template, self.qcontext)

    def flatten(self) -> None:
        """
        Force rendering of the response's template, set the result as the
        response body and unset :attr:`.template`.
        """
        if self.template:
            self.response.append(self.render())
            self.template = None

    def set_cookie(
        self,
        key: str,
        value: str = "",
        max_age: int | None = None,
        expires: datetime | int | None = -1,
        path: str | None = "/",
        domain: str | None = None,
        secure: bool | None = None,
        httponly: bool = False,
        samesite: str | None = None,
        partitioned: bool = False,
        cookie_type: str = "required",
    ) -> None:
        """
        Werkzeug defaults ``expires`` to ``None`` (a session cookie); we default
        to 1 year instead. Pass ``expires=None`` explicitly for a session cookie.

        ``secure`` and ``samesite`` default to ``None`` (let
        :func:`_apply_cookie_defaults` pick the right values based on
        the current request scheme). Pass ``secure=False`` explicitly
        only when you really need an insecure cookie.
        """
        expires, max_age, secure, samesite = _apply_cookie_defaults(
            expires,
            max_age,
            cookie_type,
            secure,
            samesite,
        )
        super().set_cookie(
            key,
            value=value,
            max_age=max_age,
            expires=expires,
            path=path,
            domain=domain,
            secure=secure,
            httponly=httponly,
            samesite=samesite,
            partitioned=partitioned,
        )


class Headers(Proxy):
    _wrapped__ = werkzeug.datastructures.Headers

    __getitem__ = ProxyFunc()
    __repr__ = ProxyFunc(str)
    __setitem__ = ProxyFunc(None)
    __str__ = ProxyFunc(str)
    __contains__ = ProxyFunc(bool)
    add = ProxyFunc(None)
    add_header = ProxyFunc(None)
    clear = ProxyFunc(None)
    copy = ProxyFunc(lambda v: Headers(v))  # noqa: PLW0108
    extend = ProxyFunc(None)
    get = ProxyFunc()
    get_all = ProxyFunc()
    getlist = ProxyFunc()
    items = ProxyFunc()
    keys = ProxyFunc()
    pop = ProxyFunc()
    popitem = ProxyFunc()
    remove = ProxyFunc(None)
    set = ProxyFunc(None)
    setdefault = ProxyFunc()
    setlist = ProxyFunc(None)
    setlistdefault = ProxyFunc()
    to_wsgi_list = ProxyFunc()
    update = ProxyFunc(None)
    values = ProxyFunc()


class ResponseCacheControl(Proxy):
    _wrapped__ = werkzeug.datastructures.ResponseCacheControl

    __getitem__ = ProxyFunc()
    __setitem__ = ProxyFunc(None)
    immutable = ProxyAttr(bool)
    max_age = ProxyAttr(int)
    must_revalidate = ProxyAttr(bool)
    must_understand = ProxyAttr(bool)
    no_cache = ProxyAttr(bool)
    no_store = ProxyAttr(bool)
    no_transform = ProxyAttr(bool)
    public = ProxyAttr(bool)
    private = ProxyAttr(bool)
    proxy_revalidate = ProxyAttr(bool)
    s_maxage = ProxyAttr(int)
    stale_if_error = ProxyAttr(int)
    stale_while_revalidate = ProxyAttr(int)
    pop = ProxyFunc()


class ResponseStream(Proxy):
    _wrapped__ = werkzeug.wrappers.ResponseStream

    write = ProxyFunc(int)
    writelines = ProxyFunc(None)
    tell = ProxyFunc(int)


class Response(Proxy):
    _wrapped__ = _Response

    # werkzeug.wrappers.Response attributes
    __call__ = ProxyFunc()
    add_etag = ProxyFunc(None)
    age = ProxyAttr()
    autocorrect_location_header = ProxyAttr(bool)
    cache_control = ProxyAttr(ResponseCacheControl)
    call_on_close = ProxyFunc()
    content_encoding = ProxyAttr(str)
    content_length = ProxyAttr(int)
    content_location = ProxyAttr(str)
    content_md5 = ProxyAttr(str)
    content_type = ProxyAttr(str)
    data = ProxyAttr()
    default_mimetype = ProxyAttr(str)
    default_status = ProxyAttr(int)
    delete_cookie = ProxyFunc(None)
    direct_passthrough = ProxyAttr(bool)
    expires = ProxyAttr()
    force_type = ProxyFunc(lambda v: Response(v))  # noqa: PLW0108
    freeze = ProxyFunc(None)
    get_data = ProxyFunc()
    get_etag = ProxyFunc()
    get_json = ProxyFunc()
    headers = ProxyAttr(Headers)
    is_json = ProxyAttr(bool)
    is_sequence = ProxyAttr(bool)
    is_streamed = ProxyAttr(bool)
    iter_encoded = ProxyFunc()
    json = ProxyAttr()
    last_modified = ProxyAttr()
    location = ProxyAttr(str)
    make_conditional = ProxyFunc(lambda v: Response(v))  # noqa: PLW0108
    make_sequence = ProxyFunc(None)
    max_cookie_size = ProxyAttr(int)
    mimetype = ProxyAttr(str)
    response = ProxyAttr()
    retry_after = ProxyAttr()
    set_cookie = ProxyFunc(None)
    set_data = ProxyFunc(None)
    set_etag = ProxyFunc(None)
    status = ProxyAttr(str)
    status_code = ProxyAttr(int)
    stream = ProxyAttr(ResponseStream)

    # odoo.http._response attributes
    load = ProxyFunc()
    set_default = ProxyFunc(None)
    qcontext = ProxyAttr()
    template = ProxyAttr(str)
    is_qweb = ProxyAttr(bool)
    render = ProxyFunc()
    flatten = ProxyFunc(None)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        response = None
        if len(args) == 1:
            arg = args[0]
            if isinstance(arg, Response):
                response = arg._wrapped__
            elif isinstance(arg, _Response):
                response = arg
            elif isinstance(arg, werkzeug.wrappers.Response):
                # Build the wrapped ``_Response`` directly — ``load`` now
                # returns the facade, which must not be nested inside another.
                response = _Response.force_type(arg)
                response.set_default()
        if response is not None and kwargs:
            # Wrapping an existing response: constructor kwargs (``status=``,
            # ``headers=`` …) would be silently dropped, since the wrapped object
            # keeps its own. Fail loudly so the caller sets them on the response
            # itself instead of shipping a response with the wrong status.
            raise TypeError(
                f"Response(existing_response) ignores keyword arguments "
                f"{sorted(kwargs)}; set them on the response object instead."
            )
        if response is None:
            if isinstance(kwargs.get("headers"), Headers):
                kwargs["headers"] = kwargs["headers"]._wrapped__
            response = _Response(*args, **kwargs)

        super().__init__(response)


# Monkey-patch werkzeug.exceptions so ``HTTPException.get_response`` returns our
# :class:`Response` and ``abort`` accepts our :class:`Response`. The originals are
# stashed on the module so a reload (test isolation, importlib.reload) doesn't
# re-wrap an already-patched version into infinite recursion.
#
# This is the SECOND werkzeug patch site; the first is ``odoo/_monkeypatches/
# werkzeug.py`` (the conventional home). These two cannot be merged: the patches
# below wrap werkzeug objects *into* :class:`Response`/:class:`_Response`, so they
# need ``odoo.http.wrappers`` loaded — whereas ``_monkeypatches`` fires the moment
# ``werkzeug`` is first imported, long before this module exists. They therefore
# live where their dependency is satisfied, applied when http is imported.
if not hasattr(werkzeug.exceptions, "_odoo_original_get_response"):
    werkzeug.exceptions._odoo_original_get_response = HTTPException.get_response
if not hasattr(werkzeug.exceptions, "_odoo_original_abort"):
    werkzeug.exceptions._odoo_original_abort = werkzeug.exceptions.abort


def get_response(
    self: HTTPException, environ: dict[str, Any] | None = None, scope: Any = None
) -> Response:
    """Return an Odoo :class:`Response` wrapping the werkzeug exception response."""
    return Response(
        werkzeug.exceptions._odoo_original_get_response(self, environ, scope)
    )


def abort(status: int | Response, *args: Any, **kwargs: Any) -> None:
    """Abort the current request with an HTTP error, unwrapping Odoo Response if needed."""
    if isinstance(status, Response):
        status = status._wrapped__
    werkzeug.exceptions._odoo_original_abort(status, *args, **kwargs)


HTTPException.get_response = get_response
werkzeug.exceptions.abort = abort


class FutureResponse:
    """
    werkzeug.Response mock class that only serves as placeholder for
    headers to be injected in the final response.
    """

    max_cookie_size = 4093

    def __init__(self) -> None:
        self.headers = werkzeug.datastructures.Headers()

    @functools.wraps(werkzeug.Response.set_cookie)
    def set_cookie(
        self,
        key: str,
        value: str = "",
        max_age: int | None = None,
        expires: datetime | int | None = -1,
        path: str | None = "/",
        domain: str | None = None,
        secure: bool | None = None,
        httponly: bool = False,
        samesite: str | None = None,
        partitioned: bool = False,
        cookie_type: str = "required",
    ) -> None:
        expires, max_age, secure, samesite = _apply_cookie_defaults(
            expires,
            max_age,
            cookie_type,
            secure,
            samesite,
        )
        werkzeug.Response.set_cookie(
            self,
            key,
            value=value,
            max_age=max_age,
            expires=expires,
            path=path,
            domain=domain,
            secure=secure,
            httponly=httponly,
            samesite=samesite,
            partitioned=partitioned,
        )
