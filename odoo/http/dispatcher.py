import collections.abc
import logging
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

from .constants import CORS_MAX_AGE, MISSING_CSRF_WARNING, SAFE_HTTP_METHODS
from .exceptions import SessionExpiredException
from .helpers import serialize_exception
from .wrappers import Response

if TYPE_CHECKING:
    from .request_class import Request
else:
    Request = Any

_logger = logging.getLogger(__name__)

_dispatchers: dict[str, type[Dispatcher]] = {}

_DEFAULT_ALLOWED_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")


def infer_dispatcher_for_unmatched(request: Request) -> type[Dispatcher]:
    """The dispatcher to answer a request that matched no route.

    A matched request gets its dispatcher from ``@route(type=...)``. An unmatched
    one has no route to ask, and :meth:`Request.__init__` seeds ``HttpDispatcher``
    "until we match" — but nothing ever revised it, so *every* unmatched URL was
    answered in HTML no matter what the client sent. A JSON caller hitting a
    typo'd path got ``404`` with ``Content-Type: text/html``; the web client's rpc
    layer can only classify that as a generic ``InvalidResponseError``, unable to
    tell "this route does not exist" from "the server returned garbage".

    Selection is by request ``Content-Type``, most specific first:

    * ``application/json-rpc`` — claimed only by :class:`JsonRPCDispatcher`.
    * ``application/json`` — claimed by BOTH JSON dispatchers, so the tie is
      broken toward :class:`Json2Dispatcher`, because it is the one that
      PRESERVES THE STATUS CODE. ``JsonRPCDispatcher`` follows the JSON-RPC
      convention of answering ``200`` with the error in the body; for a path that
      does not exist that would turn a ``404`` into a ``200``, hiding a broken
      integration from any client that (correctly) keys on the status. ``json2``
      answers ``404`` with a JSON body, which fixes the actual defect — an HTML
      body sent to a JSON caller — without trading away HTTP semantics.
      The web client is no worse off than before: ``rpc.js`` classifies a non-2xx
      JSON body without an ``error`` key as ``InvalidResponseError``
      (``!parsed.error && !response.ok``), exactly as it already did for the HTML
      one.
    * anything else — :class:`HttpDispatcher`, as before.

    Explicit precedence, not ``_dispatchers`` iteration order: registration order
    is an accident of import order and must not decide what a client is sent.
    """
    mimetype = request.httprequest.mimetype
    for routing_type in ("json2", "jsonrpc"):
        dispatcher = _dispatchers.get(routing_type)
        if dispatcher is not None and mimetype in dispatcher.mimetypes:
            return dispatcher
    return _dispatchers["http"]


class Dispatcher(ABC):
    routing_type: str
    mimetypes: collections.abc.Collection[str] = ()

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
        """
        Determine if the current request is compatible with this
        dispatcher.
        """

    def pre_dispatch(self, rule: Any, args: dict[str, Any]) -> None:
        """
        Prepare the system before dispatching the request to its
        controller. Modules customize this step by overriding the
        ``ir.http._pre_dispatch`` hook, which calls this method, e.g. to
        read info from the request query-string or headers into the
        session or context.
        """
        routing = rule.endpoint.routing
        self.request.session.can_save &= routing.get("save_session", True)

        httprequest = self.request.httprequest
        set_header = self.request.future_response.headers.set
        cors = routing.get("cors")
        vary: list[str] = []

        if cors:
            allow_origin = cors
            if routing.get("cors_credentials"):
                vary.append("Origin")
                origin = httprequest.headers.get("Origin")
                if origin and cors in ("*", origin):
                    allow_origin = origin
                    set_header("Access-Control-Allow-Credentials", "true")
                else:
                    allow_origin = None
            if allow_origin:
                set_header("Access-Control-Allow-Origin", allow_origin)
                set_header(
                    "Access-Control-Allow-Methods",
                    (
                        "POST"
                        if routing["type"] == JsonRPCDispatcher.routing_type
                        else ", ".join(routing["methods"] or ["GET", "POST"])
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
                [*(routing.get("methods") or _DEFAULT_ALLOWED_METHODS), "OPTIONS"]
            )
            werkzeug.exceptions.abort(response)

        if "max_content_length" in routing:
            max_content_length = routing["max_content_length"]
            if callable(max_content_length):
                max_content_length = max_content_length(rule.endpoint.func.__self__)
            self.request.httprequest.max_content_length = max_content_length

    @abstractmethod
    def dispatch(self, endpoint: Callable, args: dict[str, Any]) -> Any:
        """
        Extract the params from the request's body and call the
        endpoint. While it is preferred to override ir.http._pre_dispatch
        and ir.http._post_dispatch, this method can be overridden to have
        a tight control over the dispatching.
        """

    def post_dispatch(self, response: Response) -> None:
        """
        Manipulate the HTTP response to inject various headers, also
        save the session when it is dirty.
        """
        root = self.request.app

        self.request._save_session()
        self.request._inject_future_response(response)
        root.set_csp(response)

    def _call_endpoint(self, endpoint: Callable) -> Any:
        """Invoke ``endpoint`` with the request's deserialized params.

        With a database, route through ``ir.http._dispatch`` (which layers
        captcha/recaptcha and module overrides); without one (``auth='none'``)
        call the endpoint directly. Shared so the db/no-db branch lives in one
        place rather than each ``dispatch``.
        """
        if self.request.db:
            return self.request.registry["ir.http"]._dispatch(endpoint)
        return endpoint(**self.request.params)

    @abstractmethod
    def handle_error(self, exc: Exception) -> collections.abc.Callable:
        """
        Transform the exception into a valid HTTP response. Called upon
        any exception while serving a request.
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
        """
        Perform http-related actions such as deserializing the request
        body and query-string and checking csrf while dispatching a
        request to a ``type='http'`` route.

        See :meth:`~odoo.http.Response.load` method for the compatible
        endpoint return types.
        """
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

    def handle_error(self, exc: Exception) -> collections.abc.Callable:
        """
        Handle any exception that occurred while dispatching a request
        to a `type='http'` route. Also handle exceptions that occurred
        when no route matched the request path, when no fallback page
        could be delivered and that the request ``Content-Type`` was not
        json.

        :param Exception exc: the exception that occurred.
        :returns: a WSGI application
        """
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

    def __init__(self, request: Request) -> None:
        super().__init__(request)
        self.jsonrequest: dict[str, Any] = {}
        self.request_id: Any = None

    @classmethod
    def is_compatible_with(cls, request: Request) -> bool:
        return request.httprequest.mimetype in cls.mimetypes

    def dispatch(self, endpoint: Callable, args: dict[str, Any]) -> Any:
        """
        `JSON-RPC 2 <http://www.jsonrpc.org/specification>`_ over HTTP.

        Our implementation differs from the specification on two points:

        1. The ``method`` member of the JSON-RPC request payload is
           ignored as the HTTP path is already used to route the request
           to the controller.
        2. We only support parameter structures by-name, i.e. the
           ``params`` member of the JSON-RPC request payload MUST be a
           JSON Object and not a JSON Array.

        There is NO framework-level ``context`` handling: every ``params`` key is
        forwarded by name, so ``context`` is just an ordinary argument. Callers
        that need it (e.g. ``call_kw``) read it from their own kwargs and apply it
        at the ORM layer.

        Successful request::

          --> {"jsonrpc": "2.0", "method": "call", "params": {"arg1": "val1" }, "id": null}

          <-- {"jsonrpc": "2.0", "result": { "res1": "val1" }, "id": null}

        Request producing an error::

          --> {"jsonrpc": "2.0", "method": "call", "params": {"arg1": "val1" }, "id": null}

          <-- {"jsonrpc": "2.0", "error": {"code": 1, "message": "End user error message.", "data": {"code": "codestring", "debug": "traceback" } }, "id": null}

        """
        try:
            self.jsonrequest = self.request.get_json_data()
        except ValueError:
            werkzeug.exceptions.abort(Response("Invalid JSON data", status=400))

        if not isinstance(self.jsonrequest, dict):
            werkzeug.exceptions.abort(Response("Invalid JSON-RPC data", status=400))

        self.request_id = self.jsonrequest.get("id")
        params = self.jsonrequest.get("params", {})
        if not isinstance(params, dict):
            e = f"JSON-RPC params must be an object (got {type(params).__name__!r})."
            raise werkzeug.exceptions.BadRequest(e)
        self.request.params = params | args

        result = self._call_endpoint(endpoint)
        return self._response(result)

    def handle_error(self, exc: Exception) -> collections.abc.Callable:
        """
        Handle any exception that occurred while dispatching a request to
        a `type='jsonrpc'` route. Also handle exceptions that occurred when
        no route matched the request path, that no fallback page could
        be delivered and that the request ``Content-Type`` was json.

        :param exc: the exception that occurred.
        :returns: a WSGI application
        """
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
        if self.jsonrequest is None:
            self.request.params = dict(args)
        else:
            self.request.params = self.jsonrequest | args

        result = self._call_endpoint(endpoint)
        if isinstance(result, Response):
            return result
        if isinstance(result, werkzeug.wrappers.Response):
            return Response(result)
        return self.request.make_json_response(result)

    def handle_error(self, exc: Exception) -> collections.abc.Callable:
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
