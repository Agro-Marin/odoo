"""Structural type definitions for the http package's external contracts.

The :class:`HttpExtension` protocol declares the methods on
``env["ir.http"]`` that the http package calls. It serves three purposes:

* Documents the contract in one place rather than scattered across call sites.
* Enables IDE navigation and static type checking when used at call sites
  via ``cast(HttpExtension, env["ir.http"])``.
* Surfaces breakage when ``ir.http`` changes a hook signature.

No static type checker is currently configured for this fork, so the third
guarantee is provided at *test* time instead of type-check time:
``odoo.addons.test_http.tests.test_http_audit.TestIrHttpContract`` asserts that
``IrHttp`` keeps satisfying this protocol (presence + argument arity). Keep the
two in sync — if you add or change a hook the http package calls on
``ir.http``, update this protocol and that test will confirm the match.

Implementation note: every method below is a ``@classmethod`` on
``odoo.addons.base.models.ir_http.IrHttp`` *except* :meth:`routing_map` (a
regular method). The protocol models the **caller-visible** shape — the http
package always invokes these on a model recordset
(``env["ir.http"].method(...)``), so they are declared as instance methods
here regardless of the classmethod implementation; Python's descriptor
protocol resolves both identically at the call site.

The protocol uses ``typing.Protocol`` so it does not impose nominal
inheritance on the ``ir.http`` model — duck-typing remains the runtime
discipline.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import werkzeug.datastructures
    import werkzeug.routing

    from .wrappers import Response


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
