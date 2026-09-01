from __future__ import annotations

import collections.abc
import logging
from abc import ABC, abstractmethod
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
from ._protocols import ir_http
from .constants import (
    CORS_DEFAULT_ALLOWED_HEADERS,
    CORS_DEFAULT_ALLOWED_METHODS,
    CORS_MAX_AGE,
    MISSING_CSRF_WARNING,
    SAFE_HTTP_METHODS,
    prepare_allow_header,
)
from .exceptions import SessionExpiredException
from .helpers import serialize_exception
from .wrappers import Response, prepare_no_content_response

if TYPE_CHECKING:
    from ._protocols import Endpoint, RequestState

_logger = logging.getLogger(__name__)

_dispatchers: dict[str, type[Dispatcher]] = {}


def get_dispatcher_for_unmatched_route(request: RequestState) -> type[Dispatcher]:
    mimetype = request.httprequest.mimetype
    for routing_type in ("json2", "jsonrpc"):
        dispatcher = _dispatchers.get(routing_type)
        if dispatcher is not None and mimetype in dispatcher.mimetypes:
            return dispatcher
    return _dispatchers["http"]


def _get_cors_methods(
    dispatcher_methods: collections.abc.Collection[str] | None,
    routing: collections.abc.Mapping[str, Any],
) -> collections.abc.Collection[str]:
    if dispatcher_methods is not None:
        return dispatcher_methods
    routed = routing.get("methods")
    if routed is not None:
        return routed
    return CORS_DEFAULT_ALLOWED_METHODS


class Dispatcher(ABC):
    routing_type: str
    mimetypes: collections.abc.Collection[str] = ()

    cors_allowed_methods: collections.abc.Collection[str] | None = None

    serializes_errors_in_dev_mode: bool = False

    @classmethod
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        routing_type = getattr(cls, "routing_type", None)
        if routing_type is None:
            return
        existing = _dispatchers.get(routing_type)
        if existing is not None and existing is not cls:
            deliberate = issubclass(cls, existing)
            _logger.log(
                logging.DEBUG if deliberate else logging.WARNING,
                "Dispatcher routing_type=%r was %s; %s %s it.",
                routing_type,
                existing.__name__,
                cls.__name__,
                "extends" if deliberate else "unrelatedly replaces",
            )
        _dispatchers[routing_type] = cls

    def __init__(self, request: RequestState) -> None:
        self.request = request

    @classmethod
    @abstractmethod
    def is_compatible_with_request(cls, request: RequestState) -> bool:
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
                    ", ".join(_get_cors_methods(self.cors_allowed_methods, routing)),
                )
                expose = routing.get("cors_expose_headers")
                if expose:
                    set_header(
                        "Access-Control-Expose-Headers",
                        expose if isinstance(expose, str) else ", ".join(expose),
                    )

        is_preflight = bool(cors) and httprequest.method == "OPTIONS"
        if is_preflight:
            set_header("Access-Control-Max-Age", CORS_MAX_AGE)
            allow_headers = routing.get("cors_allow_headers")
            if allow_headers is None:
                set_header(
                    "Access-Control-Allow-Headers",
                    httprequest.headers.get("Access-Control-Request-Headers")
                    or CORS_DEFAULT_ALLOWED_HEADERS,
                )
                vary.append("Access-Control-Request-Headers")
            else:
                set_header(
                    "Access-Control-Allow-Headers",
                    allow_headers
                    if isinstance(allow_headers, str)
                    else ", ".join(allow_headers),
                )

        if vary:
            set_header("Vary", ", ".join(vary))

        if httprequest.method == "OPTIONS" and (
            is_preflight or "OPTIONS" not in (routing.get("methods") or ())
        ):
            werkzeug.exceptions.abort(
                prepare_no_content_response(
                    headers=[("Allow", prepare_allow_header(routing.get("methods")))]
                )
            )

        if "max_content_length" in routing:
            max_content_length = routing["max_content_length"]
            if callable(max_content_length):
                max_content_length = max_content_length(rule.endpoint.func.__self__)
            self.request.httprequest.max_content_length = max_content_length

    @abstractmethod
    def dispatch(self, endpoint: Endpoint, args: dict[str, Any]) -> Any:
        pass

    def post_dispatch(self, response: Response) -> None:
        root = self.request.app

        self.request._save_session()
        self.request._update_response_from_future(response)
        root.update_security_headers(response)

    def _call_endpoint(self, endpoint: Endpoint) -> Any:
        specs = getattr(endpoint, "_param_specs", None)
        if specs:
            self.request.params = coerce_params(self.request.params, specs)
        if self.request.db:
            registry = self.request.registry
            assert registry is not None, "a database-bound request has a registry"
            return ir_http(registry)._dispatch(endpoint)
        return endpoint(**self.request.params)

    @abstractmethod
    def prepare_error_response(self, exc: Exception) -> Response | HTTPException:
        pass


class HttpDispatcher(Dispatcher):
    routing_type = "http"

    mimetypes = (
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "*/*",
    )

    @classmethod
    def is_compatible_with_request(cls, request: RequestState) -> bool:
        return True

    def dispatch(self, endpoint: Endpoint, args: dict[str, Any]) -> Any:
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
            if not self.request.is_valid_csrf(token):
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

    def prepare_error_response(self, exc: Exception) -> Response | HTTPException:
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

    def __init__(self, request: RequestState) -> None:
        super().__init__(request)
        self.jsonrequest: dict[str, Any] = {}
        self.request_id: Any = None

    @classmethod
    def is_compatible_with_request(cls, request: RequestState) -> bool:
        return request.httprequest.mimetype in cls.mimetypes

    def dispatch(self, endpoint: Endpoint, args: dict[str, Any]) -> Any:
        try:
            self.jsonrequest = self.request.get_json_data()
        except ValueError as exc:
            raise self._prepare_bad_request_error("Invalid JSON data") from exc

        if not isinstance(self.jsonrequest, dict):
            raise self._prepare_bad_request_error("Invalid JSON-RPC data")

        self.request_id = self.jsonrequest.get("id")
        params = self.jsonrequest.get("params", {})
        if not isinstance(params, dict):
            e = f"JSON-RPC params must be an object (got {type(params).__name__!r})."
            raise werkzeug.exceptions.BadRequest(e)
        self.request.params = params | args

        result = self._call_endpoint(endpoint)
        return self._prepare_jsonrpc_response(result)

    def prepare_error_response(self, exc: Exception) -> Response:
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

        return self._prepare_jsonrpc_response(error=error)

    def _prepare_bad_request_error(self, message: str) -> HTTPException:
        body = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": 400, "message": message, "data": {}},
        }
        return HTTPException(
            response=self.request.prepare_json_response(body, status=400)
        )

    def _prepare_jsonrpc_response(
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

        return self.request.prepare_json_response(response)


class Json2Dispatcher(Dispatcher):
    routing_type = "json2"
    mimetypes = ("application/json",)

    def __init__(self, request: RequestState) -> None:
        super().__init__(request)
        self.jsonrequest: dict[str, Any] | None = None

    @classmethod
    def is_compatible_with_request(cls, request: RequestState) -> bool:
        return (
            request.httprequest.mimetype in cls.mimetypes
            or not request.httprequest.content_length
        )

    def dispatch(self, endpoint: Endpoint, args: dict[str, Any]) -> Any:
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
        return self.request.prepare_json_response(result)

    def prepare_error_response(self, exc: Exception) -> Response:
        if isinstance(exc, HTTPException) and exc.response:
            return Response(exc.response)

        headers = None
        if isinstance(exc, (UserError, SessionExpiredException)):
            status = exc.http_status
            body = serialize_exception(exc)
        elif isinstance(exc, HTTPException):
            status = exc.code or HTTPStatus.INTERNAL_SERVER_ERROR
            body = serialize_exception(
                exc,
                message=exc.description,
                arguments=(exc.description, status),
            )
            headers = [(k, v) for k, v in exc.get_headers() if k != "Content-Type"]
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            body = serialize_exception(exc)

        return self.request.prepare_json_response(body, headers=headers, status=status)
