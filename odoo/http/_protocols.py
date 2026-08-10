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
        pass
