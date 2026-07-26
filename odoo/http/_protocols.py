"""Structural type definitions for the http package's contracts.

:class:`HttpExtension` declares the ``env["ir.http"]`` methods the http package
calls — documenting the contract in one place and surfacing breakage when a hook
signature changes. mypy checks this package (``mypy.ini``, ratcheted by
``.github/workflows/py_typecheck.yml``) but cannot see through
``env["ir.http"]``, which resolves to a registry model at runtime — so the
contract is additionally enforced by ``test_http/tests/test_ir_http_contract.py``,
asserting presence and positional arity of every hook against the real
``ir.http`` model.

Methods are declared as instance methods to model the **caller-visible** shape
(``env["ir.http"].method(...)``), even though most are ``@classmethod`` on
``IrHttp``. Being a ``typing.Protocol``, it imposes no nominal inheritance —
duck-typing stays the runtime discipline.

:class:`RequestState` covers the package's *internal* contract instead: what the
``Request`` mixins may assume ``Request`` itself provides.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import werkzeug.datastructures
    import werkzeug.routing

    import odoo.api
    from odoo.modules.registry import Registry

    from .dispatcher import Dispatcher
    from .geoip import GeoIP
    from .session import Session
    from .wrappers import FutureResponse, HTTPRequest, Response


if TYPE_CHECKING:

    class RequestState:
        """The state :class:`~odoo.http.Request` provides to its mixins.

        ``Request`` is split across ``_RequestServeMixin`` /
        ``_RequestResponseMixin`` / ``_RequestCsrfMixin`` for file size, so each
        mixin reads attributes it does not define. That borrowing used to live
        only in prose at the top of each mixin, where nothing could check it and
        a rename would leave the description behind; declaring it here makes the
        contract the thing the type checker verifies.

        Type-checking only — mixed in as ``object`` at runtime, since ``Request``
        supplies these for real.
        """

        app: Any
        db: str | None
        dispatcher: Dispatcher
        env: odoo.api.Environment | None
        future_response: FutureResponse
        geoip: GeoIP
        httprequest: HTTPRequest
        params: dict[str, Any]
        registry: Registry | None
        session: Session

        def _get_session_and_dbname(self) -> tuple[Session, str | None]: ...

        def _reset_for_replay(self, cr: Any = None) -> None: ...

        def get_http_params(self) -> dict[str, Any]: ...

else:
    RequestState = object


@runtime_checkable
class HttpExtension(Protocol):
    """Hooks the http package expects on ``env["ir.http"]``.

    Implemented by ``odoo.addons.base.models.ir_http.IrHttp`` and
    extended in modules like ``website``, ``portal`` and ``http_routing``.
    """

    def routing_map(self, key: str | None = None) -> werkzeug.routing.Map:
        """Return the werkzeug routing map for the active database.

        ``key`` is the ``ormcache`` key (``cache="routing"``); the http
        package always calls this with no argument and lets the cache fill it.
        """

    def _match(self, path_info: str) -> tuple[werkzeug.routing.Rule, dict[str, Any]]:
        """Match ``path_info`` against the routing map; raise NotFound on miss."""

    def _dispatch(self, endpoint: Callable) -> Any:
        """Invoke the controller endpoint, returning its raw result."""

    def _authenticate(self, endpoint: Callable) -> None:
        """Verify the request fulfils ``@route(auth=...)`` for ``endpoint``."""

    def _pre_dispatch(
        self,
        rule: werkzeug.routing.Rule,
        args: dict[str, Any],
    ) -> None:
        """Set up per-request state before the dispatcher runs."""

    def _post_dispatch(self, response: Response) -> None:
        """Post-process the response (CSP, headers, session save)."""

    def _handle_error(self, exception: Exception) -> Response:
        """Convert an unhandled exception into an HTTP response."""

    def _serve_fallback(self) -> Response | None:
        """Try alternative serving paths (attachment, blog, etc.) on 404."""

    def _redirect(self, location: str, code: int = 303) -> Response:
        """Build a redirect response targeting ``location`` with ``code``."""

    def _is_allowed_cookie(self, cookie_type: str) -> bool:
        """Return True when a cookie of ``cookie_type`` may be set."""

    def _sanitize_cookies(
        self,
        cookies: werkzeug.datastructures.MultiDict,
    ) -> None:
        """Mutate ``cookies`` in place to drop unwanted entries."""

    def _post_logout(self) -> None:
        """Run any side effects required after a session logout."""

    def _auth_method_public(self) -> None:
        """Promote the current request to the public-user identity."""
