import collections.abc
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from .request_class import Request
else:
    # ``Request`` is used ONLY in annotations here, never as a runtime value, so
    # we don't import it at runtime — that would re-form the Request<->Dispatcher
    # cycle and force the old bottom-of-file late import. The ``else: Any``
    # fallback is the pattern blessed by ``test_lint.test_pep649`` (and used by
    # ``odoo.tools.{files,sql}``): annotations like ``request: Request`` resolve
    # to ``Any`` under PEP 649 introspection instead of raising ``NameError``.
    Request = Any

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
        controller. Modules customize this step by overriding the
        ``ir.http._pre_dispatch`` hook, which calls this method, e.g. to
        read info from the request query-string or headers into the
        session or context.
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
            # Reflect the exact headers the browser asks for (the standard
            # answer for a route that already opted into CORS) instead of a
            # hand-maintained allow-list — the static list silently broke
            # streaming clients until ``Range`` was added, and would break the
            # next custom header the same way. Header allowance is not an auth
            # boundary: forbidden headers stay browser-enforced and the actual
            # request still passes the route's own auth. The static list is
            # kept as fallback for preflights that name no headers.
            set_header(
                "Access-Control-Allow-Headers",
                self.request.httprequest.headers.get("Access-Control-Request-Headers")
                or "Origin, X-Requested-With, Content-Type, Accept, Authorization, Range",
            )
            # ``abort`` raises an HTTPException carrying our 204; _serve.py
            # catches it (``code is None`` branch), runs ``post_dispatch`` to add
            # CORS/CSP/session headers, and returns it. No endpoint runs.
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

        # ``get_http_params``'s flat merge keeps one value per key, silently
        # dropping the rest of ``?a=1&a=2``. For a typed route's
        # ``list``-annotated params (the only place multi-values have declared
        # meaning), re-read every value via ``getlist``. Path args are never
        # lists, so keys bound by the rule are left alone.
        list_params = getattr(endpoint, "typed_list_params", None)
        if list_params:
            httprequest = self.request.httprequest
            for name in list_params:
                if name in args:
                    continue
                values = httprequest.args.getlist(name) + httprequest.form.getlist(name)
                if len(values) > 1:
                    self.request.params[name] = values

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
                # Phrasing matches ``website.form``'s own raise (kept identical
                # for log scrapers / screens): an expired session is the dominant
                # cause of CSRF rejection in practice.
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
            # ``UserError`` and subclasses always define ``http_status``; read it
            # directly (consistent with ``Json2Dispatcher.handle_error``).
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

        # JSON-RPC requires a top-level object; check explicitly rather than
        # letting ``dict.get`` raise AttributeError on a list/scalar/null body.
        if not isinstance(self.jsonrequest, dict):
            # must use abort+Response to bypass handle_error
            werkzeug.exceptions.abort(Response("Invalid JSON-RPC data", status=400))

        self.request_id = self.jsonrequest.get("id")
        # Only by-name params (a JSON Object) are supported. A present-but-non
        # -object ``params`` cannot merge with the path-arg dict; reject it
        # clearly instead of an opaque ``dict | list`` TypeError. Missing
        # ``params`` defaults to ``{}``.
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
            # Envelope versioning: ``@versioned_envelope`` stashes a content hash
            # on ``request._response_version``. Lift it beside ``result`` so the JS
            # rpc layer can reattach it — works for list results, which can't carry
            # an in-payload ``__version`` key.
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
        httprequest = self.request.httprequest
        # CSRF defense for state-changing requests.  A json2 route is normally
        # called with ``Content-Type: application/json``, which forces a CORS
        # preflight cross-origin (the same protection jsonrpc relies on).  An
        # empty/non-JSON body on an unsafe method is a cross-site "simple
        # request" that skips that preflight and could drive a state change from
        # the path args alone, so reject it unless the route opts out
        # (``csrf=False``).  A non-JSON request WITH a body is already refused by
        # ``is_compatible_with`` (415); this closes the empty-body gap.
        if (
            httprequest.method not in SAFE_HTTP_METHODS
            and httprequest.mimetype not in self.mimetypes
            and endpoint.routing.get("csrf", True)
        ):
            raise werkzeug.exceptions.BadRequest(
                "State-changing json2 requests must use the 'application/json' "
                "Content-Type (CSRF protection)."
            )
        # Gate on the actual body, not content_length: a chunked request
        # (Transfer-Encoding: chunked) has content_length None, so gating on it
        # dropped the body and ran the endpoint with path args only — a
        # state-changing json2 route would silently execute with defaults.
        # get_data() reads (and caches) the full body regardless of framing;
        # get_json_data() below reuses that cache.
        if httprequest.get_data(cache=True):
            try:
                self.jsonrequest = self.request.get_json_data()
            except ValueError as exc:
                e = f"could not parse the body as json: {exc.args[0]}"
                raise werkzeug.exceptions.BadRequest(e) from exc
            if self.jsonrequest is not None and not isinstance(self.jsonrequest, dict):
                # Top-level arrays/scalars cannot merge with the path-arg dict and
                # have no sensible default; reject with a clear 400 instead of
                # silently discarding the body. ``null`` is exempt: it means "no
                # body", handled by the ``is None`` branch below (path args alone).
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
