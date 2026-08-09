import collections.abc
import logging
import typing
from abc import ABC, abstractmethod
from collections.abc import Callable
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import werkzeug.exceptions
import werkzeug.wrappers
from werkzeug.exceptions import (
    HTTPException,
    InternalServerError,
    NotFound,
    UnprocessableEntity,
)
from werkzeug.exceptions import (
    default_exceptions as werkzeug_default_exceptions,
)

from odoo.exceptions import UserError

from ._params import coerce_params
from .constants import (
    CORS_DEFAULT_ALLOWED_METHODS,
    CORS_MAX_AGE,
    DEFAULT_ALLOWED_METHODS,
    MISSING_CSRF_WARNING,
    SAFE_HTTP_METHODS,
)
from .exceptions import SessionExpiredException
from .helpers import serialize_exception
from .wrappers import Response

if TYPE_CHECKING:
    from .request_class import Request
else:
    Request = Any

_logger = logging.getLogger(__name__)

_dispatchers: dict[str, type[Dispatcher]] = {}


def infer_dispatcher_for_unmatched(request: Request) -> type[Dispatcher]:
    mimetype = request.httprequest.mimetype
    for routing_type in ("json2", "jsonrpc"):
        dispatcher = _dispatchers.get(routing_type)
        if dispatcher is not None and mimetype in dispatcher.mimetypes:
            return dispatcher
    return _dispatchers["http"]


class Dispatcher(ABC):
    routing_type: str
    mimetypes: collections.abc.Collection[str] = ()

    cors_allowed_methods: collections.abc.Collection[str] | None = None
    """Methods to advertise in ``Access-Control-Allow-Methods``.

    ``None`` means "whatever the route declares". A dispatcher that accepts one
    verb regardless of the route says so here.

    Declared because :meth:`pre_dispatch` used to read
    ``routing["type"] == JsonRPCDispatcher.routing_type`` -- the abstract base
    naming one of its own concrete subclasses, defined 130 lines below it. That
    is the wrong direction for every reason: a fourth dispatcher with the same
    constraint would have had to be added to a condition in its own base class.
    """

    serializes_errors_in_dev_mode: bool = False
    """Whether to build a serialised error body even under ``--dev werkzeug``.

    Same inversion, same reason: ``_serve.py::_update_served_exception`` asked
    ``self.dispatcher.routing_type != JsonRPCDispatcher.routing_type`` to decide
    whether to let werkzeug's interactive debugger take the exception instead.
    The question it is actually asking is "does this transport's client need a
    structured error rather than an HTML traceback?", which is a property of the
    dispatcher, not a string comparison against a sibling.
    """

    @classmethod
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        routing_type = getattr(cls, "routing_type", None)
        if routing_type is None:
            return
        existing = _dispatchers.get(routing_type)
        if existing is not None and existing is not cls:
            _logger.warning(
                "Dispatcher routing_type=%r already registered as %s; %s overrides it.",
                routing_type,
                existing.__name__,
                cls.__name__,
            )
        _dispatchers[routing_type] = cls

    def __init__(self, request: Request) -> None:
        self.request = request

    @classmethod
    @abstractmethod
    def is_compatible_with(cls, request: Request) -> bool:
        pass

    def pre_dispatch(self, rule: Any, args: dict[str, Any]) -> None:
        routing = rule.endpoint.routing
        self.request.session.can_save &= routing.get("save_session", True)

        httprequest = self.request.httprequest
        set_header = self.request.future_response.headers.set
        cors = routing.get("cors")
        credentials = bool(routing.get("cors_credentials"))
        vary: list[str] = []

        if cors:
            if callable(cors):
                vary.append("Origin")
                allow_origin = cors(self.request)
            else:
                allow_origin = cors
            if credentials:
                if "Origin" not in vary:
                    vary.append("Origin")
                origin = httprequest.headers.get("Origin")
                if origin and allow_origin == origin:
                    set_header("Access-Control-Allow-Credentials", "true")
                else:
                    allow_origin = None
            if allow_origin:
                set_header("Access-Control-Allow-Origin", allow_origin)
                set_header(
                    "Access-Control-Allow-Methods",
                    # NOT `DEFAULT_ALLOWED_METHODS`, which is the six-verb list
                    # the OPTIONS handler below advertises. This fallback has
                    # always been the narrower pair and stays it; the two
                    # defaults look interchangeable and are not.
                    ", ".join(
                        self.cors_allowed_methods
                        or routing["methods"]
                        or CORS_DEFAULT_ALLOWED_METHODS
                    ),
                )

        is_preflight = bool(cors) and httprequest.method == "OPTIONS"
        if is_preflight:
            set_header("Access-Control-Max-Age", CORS_MAX_AGE)
            set_header(
                "Access-Control-Allow-Headers",
                httprequest.headers.get("Access-Control-Request-Headers")
                or "Origin, X-Requested-With, Content-Type, Accept, Authorization, Range",
            )
            vary.append("Access-Control-Request-Headers")

        if vary:
            set_header("Vary", ", ".join(vary))

        if is_preflight:
            werkzeug.exceptions.abort(Response(status=204))

        if httprequest.method == "OPTIONS" and "OPTIONS" not in (
            routing.get("methods") or ()
        ):
            response = Response(status=204)
            response.headers["Allow"] = ", ".join(
                [*(routing.get("methods") or DEFAULT_ALLOWED_METHODS), "OPTIONS"]
            )
            werkzeug.exceptions.abort(response)

        if "max_content_length" in routing:
            max_content_length = routing["max_content_length"]
            if callable(max_content_length):
                max_content_length = max_content_length(rule.endpoint.func.__self__)
            self.request.httprequest.max_content_length = max_content_length

    @abstractmethod
    def dispatch(self, endpoint: Callable, args: dict[str, Any]) -> Any:
        pass

    def post_dispatch(self, response: Response) -> None:
        root = self.request.app

        self.request._save_session()
        self.request._inject_future_response(response)
        root.set_csp(response)

    def _call_endpoint(self, endpoint: Callable) -> Any:
        specs = getattr(endpoint, "_param_specs", None)
        if specs:
            self.request.params = coerce_params(self.request.params, specs)
        if self.request.db:
            return self.request.registry["ir.http"]._dispatch(endpoint)
        return endpoint(**self.request.params)

    @abstractmethod
    def handle_error(self, exc: Exception) -> Response | HTTPException:
        """Turn *exc* into the thing to serve.

        Was annotated ``-> collections.abc.Callable``. True -- a werkzeug
        response is a WSGI callable -- and useless: it told a caller nothing
        about what it may do with the value, and admitted anything callable.
        Both implementors return a ``Response`` or an ``HTTPException``.
        """


class HttpDispatcher(Dispatcher):
    routing_type = "http"

    mimetypes = (
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "*/*",
    )

    @classmethod
    def is_compatible_with(cls, request: Request) -> bool:
        return True

    def dispatch(self, endpoint: Callable, args: dict[str, Any]) -> Any:
        self.request.params = self.request.get_http_params() | args

        list_params = getattr(endpoint, "typed_list_params", None)
        if list_params:
            httprequest = self.request.httprequest
            for name in list_params:
                if name in args:
                    continue
                values = (
                    httprequest.args.getlist(name)
                    + httprequest.form.getlist(name)
                    + httprequest.files.getlist(name)
                )
                if len(values) > 1:
                    self.request.params[name] = values

        if (
            self.request.httprequest.method not in SAFE_HTTP_METHODS
            and endpoint.routing.get("csrf", True)
        ):
            if not self.request.db:
                return self.request.redirect("/web/database/selector")

            token = self.request.params.pop("csrf_token", None)
            if not self.request.validate_csrf(token):
                if token is not None:
                    _logger.warning(
                        "CSRF validation failed on path '%s'",
                        self.request.httprequest.path,
                    )
                else:
                    _logger.warning(MISSING_CSRF_WARNING, self.request.httprequest.path)
                msg = "Session expired (invalid CSRF token)"
                raise werkzeug.exceptions.BadRequest(msg)

        return self._call_endpoint(endpoint)

    def handle_error(self, exc: Exception) -> Response | HTTPException:
        if isinstance(exc, SessionExpiredException):
            session = self.request.session
            was_connected = session.uid is not None
            session.logout(keep_db=True)
            if not was_connected:
                session.should_rotate = False
            return self.request.redirect_query(
                "/web/login", {"redirect": self.request.httprequest.full_path}
            )

        if isinstance(exc, HTTPException):
            return exc

        if isinstance(exc, UserError):
            description = exc.args[0] if exc.args else str(exc) or None
            status = exc.http_status
            exc_cls = werkzeug_default_exceptions.get(status)
            if exc_cls is not None:
                return exc_cls(description)
            return UnprocessableEntity(description)

        return InternalServerError()


class JsonRPCDispatcher(Dispatcher):
    routing_type = "jsonrpc"
    mimetypes = ("application/json", "application/json-rpc")
    cors_allowed_methods = ("POST",)
    serializes_errors_in_dev_mode = True

    def __init__(self, request: Request) -> None:
        super().__init__(request)
        self.jsonrequest: dict[str, Any] = {}
        self.request_id: Any = None

    @classmethod
    def is_compatible_with(cls, request: Request) -> bool:
        return request.httprequest.mimetype in cls.mimetypes

    def dispatch(self, endpoint: Callable, args: dict[str, Any]) -> Any:
        try:
            self.jsonrequest = self.request.get_json_data()
        except ValueError:
            self._abort_bad_request("Invalid JSON data")

        if not isinstance(self.jsonrequest, dict):
            self._abort_bad_request("Invalid JSON-RPC data")

        self.request_id = self.jsonrequest.get("id")
        params = self.jsonrequest.get("params", {})
        if not isinstance(params, dict):
            e = f"JSON-RPC params must be an object (got {type(params).__name__!r})."
            raise werkzeug.exceptions.BadRequest(e)
        self.request.params = params | args

        result = self._call_endpoint(endpoint)
        return self._response(result)

    def handle_error(self, exc: Exception) -> Response:
        error = {
            "code": 0,
            "message": "Odoo Server Error",
            "data": serialize_exception(exc),
        }
        if isinstance(exc, NotFound):
            error["code"] = 404
            error["message"] = "404: Not Found"
        elif isinstance(exc, SessionExpiredException):
            error["code"] = 100
            error["message"] = "Odoo Session Expired"

        return self._response(error=error)

    def _abort_bad_request(self, message: str) -> typing.NoReturn:
        body = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": 400, "message": message, "data": {}},
        }
        werkzeug.exceptions.abort(self.request.make_json_response(body, status=400))

    def _response(
        self, result: Any = None, error: dict[str, Any] | None = None
    ) -> Response:
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": self.request_id}
        if error is not None:
            response["error"] = error
        else:
            response["result"] = result
            version = getattr(self.request, "_response_version", None)
            if version is not None:
                response["version"] = version

        return self.request.make_json_response(response)


class Json2Dispatcher(Dispatcher):
    routing_type = "json2"
    mimetypes = ("application/json",)

    def __init__(self, request: Request) -> None:
        super().__init__(request)
        self.jsonrequest: dict[str, Any] | None = None

    @classmethod
    def is_compatible_with(cls, request: Request) -> bool:
        return (
            request.httprequest.mimetype in cls.mimetypes
            or not request.httprequest.content_length
        )

    def dispatch(self, endpoint: Callable, args: dict[str, Any]) -> Any:
        httprequest = self.request.httprequest
        if (
            httprequest.method not in SAFE_HTTP_METHODS
            and httprequest.mimetype not in self.mimetypes
            and endpoint.routing.get("csrf", True)
        ):
            raise werkzeug.exceptions.BadRequest(
                "State-changing json2 requests must use the 'application/json' "
                "Content-Type (CSRF protection)."
            )
        if httprequest.get_data(cache=True):
            try:
                self.jsonrequest = self.request.get_json_data()
            except ValueError as exc:
                e = f"could not parse the body as json: {exc.args[0]}"
                raise werkzeug.exceptions.BadRequest(e) from exc
            if self.jsonrequest is not None and not isinstance(self.jsonrequest, dict):
                e = (
                    "JSON request body must be an object (got "
                    f"{type(self.jsonrequest).__name__!r})."
                )
                raise werkzeug.exceptions.BadRequest(e)
        self.request.params = {
            **httprequest.args,
            **(self.jsonrequest or {}),
            **args,
        }

        result = self._call_endpoint(endpoint)
        if isinstance(result, Response):
            return result
        if isinstance(result, werkzeug.wrappers.Response):
            return Response(result)
        return self.request.make_json_response(result)

    def handle_error(self, exc: Exception) -> Response:
        if isinstance(exc, HTTPException) and exc.response:
            return exc.response

        headers = None
        if isinstance(exc, (UserError, SessionExpiredException)):
            status = exc.http_status
            body = serialize_exception(exc)
        elif isinstance(exc, HTTPException):
            status = exc.code
            body = serialize_exception(
                exc,
                message=exc.description,
                arguments=(exc.description, exc.code),
            )
            headers = [(k, v) for k, v in exc.get_headers() if k != "Content-Type"]
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            body = serialize_exception(exc)

        return self.request.make_json_response(body, headers=headers, status=status)
