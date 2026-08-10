import functools
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Self

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
    if expires == -1:
        expires = datetime.now(tz=UTC) + timedelta(days=365)

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

    def getter(self: HTTPRequest) -> Any:
        return getattr(self._HTTPRequest__wrapped, attr)

    def setter(self: HTTPRequest, value: Any) -> None:
        return setattr(self._HTTPRequest__wrapped, attr, value)

    return getter, setter


if TYPE_CHECKING:
    _HTTPRequestProxied = werkzeug.wrappers.Request
else:
    _HTTPRequestProxied = object


class HTTPRequest(_HTTPRequestProxied):
    def __init__(self, environ: dict[str, Any]) -> None:
        httprequest = werkzeug.wrappers.Request(environ)
        httprequest.user_agent_class = UserAgent
        httprequest.parameter_storage_class = werkzeug.datastructures.ImmutableMultiDict
        httprequest.max_content_length = DEFAULT_MAX_CONTENT_LENGTH
        httprequest.max_form_memory_size = 10 * 1024 * 1024
        httprequest.max_form_parts = 10_000

        self.__wrapped = httprequest
        self.__environ = httprequest.environ
        filtered = {
            key: value
            for key, value in self.__environ.items()
            if (
                not key.startswith(("werkzeug.", "wsgi.", "socket"))
                or key in ["wsgi.url_scheme", "werkzeug.proxy_fix.orig"]
            )
        }
        self.environ = filtered
        httprequest.headers = werkzeug.datastructures.EnvironHeaders(filtered)

    @property
    def session_id(self) -> str | None:
        return self.__wrapped.cookies.get("session_id")

    @property
    def raw_environ(self) -> dict[str, Any]:
        return self.__environ

    def _adopt_body_state(self, other: HTTPRequest) -> None:
        src = other.__wrapped
        dst = self.__wrapped
        for key in ("stream", "data", "form", "files"):
            if key in src.__dict__:
                dst.__dict__[key] = src.__dict__[key]
        if getattr(src, "_cached_data", None) is not None:
            dst._cached_data = src._cached_data

    def __enter__(self) -> Self:
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
    default_mimetype = "text/html"

    def __init__(self, *args: Any, **kw: Any) -> None:
        template = kw.pop("template", None)
        qcontext = kw.pop("qcontext", None)
        uid = kw.pop("uid", None)
        super().__init__(*args, **kw)
        self.set_default(template, qcontext, uid)

    @classmethod
    def load(cls, result: Any, fname: str = "<function>") -> Response:
        if isinstance(result, Response):
            return result

        if isinstance(result, werkzeug.exceptions.HTTPException):
            _logger.warning("%s returns an HTTPException instead of raising it.", fname)
            raise result

        if isinstance(result, werkzeug.wrappers.Response):
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
        # `template` is `str | None` and `_render_template` takes `int | str`,
        # so this could hand QWeb a None -- the precondition `is_qweb()` states
        # one line above, which nothing enforced. Surfaced by mypy once
        # `env["ir.ui.view"]` typed as a Protocol rather than as `BaseModel`.
        if self.template is None:
            raise ValueError(
                "Response.render() needs a template; guard the call with "
                "is_qweb() or set one before rendering."
            )
        self.qcontext["request"] = request
        return request.env["ir.ui.view"]._render_template(self.template, self.qcontext)

    def flatten(self) -> None:
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
    # PLW0108: the lambda is load-bearing — `Headers` is the class this body is
    # still defining, so a bare reference would NameError at import time.
    copy = ProxyFunc(lambda v: Headers(v))  # noqa: PLW0108  see comment above
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
    force_type = ProxyFunc(lambda v: Response(v))  # noqa: PLW0108  self-reference, see Headers.copy
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
    make_conditional = ProxyFunc(lambda v: Response(v))  # noqa: PLW0108  self-reference, see Headers.copy
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
                response = _Response.force_type(arg)
                response.set_default()
        if response is not None and kwargs:
            raise TypeError(
                f"Response(existing_response) ignores keyword arguments "
                f"{sorted(kwargs)}; set them on the response object instead."
            )
        if response is None:
            if isinstance(kwargs.get("headers"), Headers):
                kwargs["headers"] = kwargs["headers"]._wrapped__
            response = _Response(*args, **kwargs)

        super().__init__(response)


if not hasattr(werkzeug.exceptions, "_odoo_original_get_response"):
    werkzeug.exceptions._odoo_original_get_response = HTTPException.get_response
if not hasattr(werkzeug.exceptions, "_odoo_original_abort"):
    werkzeug.exceptions._odoo_original_abort = werkzeug.exceptions.abort


def get_response(
    self: HTTPException, environ: dict[str, Any] | None = None, scope: Any = None
) -> Response:
    return Response(
        werkzeug.exceptions._odoo_original_get_response(self, environ, scope)
    )


def abort(status: int | Response, *args: Any, **kwargs: Any) -> None:
    if isinstance(status, Response):
        status = status._wrapped__
    werkzeug.exceptions._odoo_original_abort(status, *args, **kwargs)


HTTPException.get_response = get_response
werkzeug.exceptions.abort = abort


class FutureResponse:
    max_cookie_size = 4093

    def __init__(self) -> None:
        self.headers = werkzeug.datastructures.Headers()

    def _drop_staged_cookie(self, key: str) -> None:
        prefix = f"{key}="
        staged = self.headers.getlist("Set-Cookie")
        kept = [cookie for cookie in staged if not cookie.startswith(prefix)]
        if len(kept) != len(staged):
            self.headers.setlist("Set-Cookie", kept)

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
        self._drop_staged_cookie(key)
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
