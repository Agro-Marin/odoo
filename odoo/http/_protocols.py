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


class HasHttpStatus(Protocol):
    """An exception that names the HTTP status it should be served as.

    A structural contract spanning two modules that do not import each other:
    ``odoo/exceptions.py`` sets it on ``UserError`` and four subclasses,
    ``odoo/http/exceptions.py`` on ``SessionExpiredException``, and
    ``http/dispatcher.py`` reads ``exc.http_status`` off a union of the two.
    Nothing declared it, and the two modules disagreed on the type -- plain
    ``int`` on one side, ``HTTPStatus`` on the other. Both work, because
    ``HTTPStatus`` is an ``IntEnum``; declaring the protocol is what makes the
    agreement checkable rather than incidental.
    """

    http_status: int


@runtime_checkable
class HttpExtension(Protocol):
    def routing_map(self, key: str | None = None) -> werkzeug.routing.Map:
        pass

    def _match(self, path_info: str) -> tuple[werkzeug.routing.Rule, dict[str, Any]]:
        pass

    def _dispatch(self, endpoint: Callable) -> Any:
        pass

    def _authenticate(self, endpoint: Callable) -> None:
        pass

    def _pre_dispatch(
        self,
        rule: werkzeug.routing.Rule,
        args: dict[str, Any],
    ) -> None:
        pass

    def _post_dispatch(self, response: Response) -> None:
        pass

    def _handle_error(self, exception: Exception) -> Response:
        pass

    def _serve_fallback(self) -> Response | None:
        pass

    def _redirect(self, location: str, code: int = 303) -> Response:
        pass

    def _is_allowed_cookie(self, cookie_type: str) -> bool:
        pass

    def _sanitize_cookies(
        self,
        cookies: werkzeug.datastructures.MultiDict,
    ) -> None:
        pass

    def _post_logout(self) -> None:
        pass

    def _auth_method_public(self) -> None:
        pass

    def _apply_max_upload_size(self) -> None:
        """Clamp ``httprequest.max_content_length`` to the configured ceiling.

        Reached from ``_serve.py``'s not-found fallback and, through
        ``_pre_dispatch``, from every dispatched request. It was called by the
        core and undeclared here until 2026-08-09 — the contract test only ever
        checked *declared -> implemented*, so a member reached from ``http/``
        and absent from this Protocol had its existence and its signature
        checked by nothing. ``model_member_surface_check.py`` reads the other
        direction and is what found it.
        """
