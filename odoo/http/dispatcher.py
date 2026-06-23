import collections.abc
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from http import HTTPStatus
from typing import Any

import werkzeug.exceptions
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
from .helpers import get_session_max_inactivity, serialize_exception
from .wrappers import Response

_logger = logging.getLogger(__name__)

_dispatchers: dict[str, type[Dispatcher]] = {}


class Dispatcher(ABC):
    routing_type: str
    mimetypes: collections.abc.Collection[str] = ()

    @classmethod
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        existing = _dispatchers.get(cls.routing_type)
        if existing is not None and existing is not cls:
            # Silently overriding here masked typo'd ``routing_type``
            # collisions during fork refactors; warn so reviewers see it.
            _logger.warning(
                "Dispatcher routing_type=%r already registered as %s; %s overrides it.",
                cls.routing_type,
                existing.__name__,
                cls.__name__,
            )
        _dispatchers[cls.routing_type] = cls

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
        controller. This method is often overridden in ir.http to
        extract some info from the request query-string or headers and
        to save them in the session or in the context.
        """
        routing = rule.endpoint.routing
        self.request.session.can_save &= routing.get("save_session", True)

        set_header = self.request.future_response.headers.set
        cors = routing.get("cors")
        if cors:
            set_header("Access-Control-Allow-Origin", cors)
            set_header(
                "Access-Control-Allow-Methods",
                (
                    "POST"
                    if routing["type"] == JsonRPCDispatcher.routing_type
                    else ", ".join(routing["methods"] or ["GET", "POST"])
                ),
            )

        if cors and self.request.httprequest.method == "OPTIONS":
            set_header("Access-Control-Max-Age", CORS_MAX_AGE)
            set_header(
                "Access-Control-Allow-Headers",
                "Origin, X-Requested-With, Content-Type, Accept, Authorization",
            )
            # ``abort`` raises an HTTPException carrying our 204 Response;
            # _serve.py catches it (HTTPException w/ ``code is None`` branch),
            # runs ``post_dispatch`` so CORS+CSP+session headers land on the
            # 204, and returns it to the WSGI server. No endpoint runs.
            werkzeug.exceptions.abort(Response(status=204))

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

        With a database, the call is routed through ``ir.http._dispatch``
        (which layers captcha/recaptcha checks and module overrides on top);
        without one (``auth='none'`` / no-db serving) the endpoint is called
        directly. Shared by every dispatcher so the db/no-db branch lives in a
        single place instead of being copied into each ``dispatch``.
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
        body and query-string and checking cors/csrf while dispatching a
        request to a ``type='http'`` route.

        See :meth:`~odoo.http.Response.load` method for the compatible
        endpoint return types.
        """
        self.request.params = self.request.get_http_params() | args

        # Check for CSRF token for relevant requests
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
                # Phrasing matters: an expired session is the dominant
                # cause of CSRF rejection in practice (tab left open past
                # session lifetime).  ``website.form`` controller emits
                # the same wording on its own raise — kept identical so
                # log scrapers and user-facing screens stay consistent.
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
        root = self.request.app

        if isinstance(exc, SessionExpiredException):
            session = self.request.session
            was_connected = session.uid is not None
            session.logout(keep_db=True)
            response = self.request.redirect_query(
                "/web/login", {"redirect": self.request.httprequest.full_path}
            )
            if was_connected:
                root.session_store.rotate(session, self.request.env)
                # secure / samesite come from ``_apply_cookie_defaults``.
                response.set_cookie(
                    "session_id",
                    session.sid,
                    max_age=get_session_max_inactivity(self.request.env),
                    httponly=True,
                )
            return response

        if isinstance(exc, HTTPException):
            return exc

        if isinstance(exc, UserError):
            description = exc.args[0] if exc.args else str(exc) or None
            # ``UserError`` and its subclasses always define ``http_status``;
            # read it directly, consistent with ``Json2Dispatcher.handle_error``
            # (the previous ``getattr(..., None)`` implied an absence that
            # cannot occur for this branch).
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

        Unlike older Odoo versions, there is NO framework-level ``context``
        handling here: every key of ``params`` is forwarded to the endpoint
        by name, so a ``context`` key is just an ordinary argument (dropped
        with an "ignoring args" warning if the endpoint does not declare it).
        RPC calls that need to influence the environment context pass it
        through their own argument instead — e.g. ``call_kw`` reads it from
        ``kwargs['context']`` and applies it at the ORM layer.

        Successful request::

          --> {"jsonrpc": "2.0", "method": "call", "params": {"arg1": "val1" }, "id": null}

          <-- {"jsonrpc": "2.0", "result": { "res1": "val1" }, "id": null}

        Request producing a error::

          --> {"jsonrpc": "2.0", "method": "call", "params": {"arg1": "val1" }, "id": null}

          <-- {"jsonrpc": "2.0", "error": {"code": 1, "message": "End user error message.", "data": {"code": "codestring", "debug": "traceback" } }, "id": null}

        """
        try:
            self.jsonrequest = self.request.get_json_data()
        except ValueError:
            # Malformed JSON: no request id is parseable, so a JSON-RPC error
            # envelope cannot be built — abort+Response bypasses handle_error.
            werkzeug.exceptions.abort(Response("Invalid JSON data", status=400))

        # JSON-RPC requires a top-level object. Check it explicitly rather than
        # letting ``dict.get`` raise AttributeError on a list/scalar/null body
        # (which conflated unrelated AttributeErrors with a malformed payload).
        if not isinstance(self.jsonrequest, dict):
            # must use abort+Response to bypass handle_error
            werkzeug.exceptions.abort(Response("Invalid JSON-RPC data", status=400))

        self.request_id = self.jsonrequest.get("id")
        # We only support by-name params (a JSON Object). A present-but-non-object
        # ``params`` (array/scalar/null) cannot be merged with the path-argument
        # dict; reject it with a clear message instead of letting ``dict | list``
        # raise an opaque TypeError that surfaces as a generic "Odoo Server Error".
        # A missing ``params`` defaults to an empty object.
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
            "code": 0,  # we don't care of this code
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
            # Plan-C envelope versioning: methods decorated with
            # ``@versioned_envelope`` (``odoo.tools.cache_version``) stash a
            # content hash on ``request._response_version``.  Lift it to a
            # sibling of ``result`` so the JS rpc layer can transfer it back
            # onto the result object — sidesteps the "lists can't carry a
            # __version key in-payload" limitation of the dict-only
            # ``@versioned`` decorator.
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
        # "args" are the path parameters, "id" in /web/image/<id>
        if self.request.httprequest.content_length:
            try:
                self.jsonrequest = self.request.get_json_data()
            except ValueError as exc:
                e = f"could not parse the body as json: {exc.args[0]}"
                raise werkzeug.exceptions.BadRequest(e) from exc
            if self.jsonrequest is not None and not isinstance(self.jsonrequest, dict):
                # Top-level JSON arrays/scalars cannot be merged with the
                # path-argument dict, and there is no sensible default
                # mapping. Previously the TypeError was swallowed and the
                # body was silently discarded — clients got "missing
                # argument" errors instead of a clear 400.
                #
                # ``null`` is intentionally exempt: it is the JSON spelling
                # of "no body content", semantically equivalent to an
                # empty request, and is handled by the ``self.jsonrequest is None``
                # branch below (path args alone, endpoint surfaces its own
                # ``missing argument`` error if applicable).
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
            # strip Content-Type (we set our own) but keep the remaining headers
            headers = [(k, v) for k, v in exc.get_headers() if k != "Content-Type"]
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            body = serialize_exception(exc)

        return self.request.make_json_response(body, headers=headers, status=status)


# Late import to break the Dispatcher <-> Request cycle.  ``Request`` is used
# only in annotations and method bodies of the classes above, so it does not
# need to be resolvable at class-definition time.  By the time this import
# runs, the ABC and its subclasses are already in this module's namespace,
# so request_class.py's top-of-file import of ``HttpDispatcher`` /
# ``JsonRPCDispatcher`` (which it does from its own bottom-of-file import)
# resolves against our partially-initialised module successfully.
# See odoo.addons.test_lint.tests.test_pep649.KNOWN_FAILURES for context.
from .request_class import Request  # noqa: E402  — see note above
