from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from types import MethodType

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
        _params_source: Callable[[], dict[str, Any]] | None
        registry: Registry | None
        session: Session

        def _get_session_and_dbname(
            self, sid: str | None = None
        ) -> tuple[Session, str | None]: ...

        def _update_response_from_future(self, response: Response) -> Response: ...

        def _reset_for_replay(self, cr: Any = None) -> None: ...

        def _save_session(self, env: odoo.api.Environment | None = None) -> None: ...

        def get_http_params(self) -> dict[str, Any]: ...

        def get_json_data(self) -> Any: ...

        def prepare_json_response(
            self,
            data: Any,
            headers: list[tuple[str, str]] | None = None,
            cookies: Mapping[str, str] | None = None,
            status: int = 200,
        ) -> Response: ...

        def redirect(
            self, location: str, code: int = 303, local: bool = True
        ) -> Response: ...

        def redirect_query(
            self,
            location: str,
            query: dict[str, str] | None = None,
            code: int = 303,
            local: bool = True,
        ) -> Response: ...

        def is_valid_csrf(self, csrf: str | None) -> bool: ...

else:
    RequestState = object


class HasHttpStatus(Protocol):
    http_status: int


class HasRouting(Protocol):
    routing: Mapping[str, Any]


class RoutedMethod(Protocol):
    original_routing: Mapping[str, Any]
    original_endpoint: Callable

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class Endpoint(HasRouting, RoutedMethod, Protocol):
    func: MethodType
    _param_specs: dict[str, Any] | None
    typed_list_params: frozenset[str] | None


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


def ir_http(source: Registry | odoo.api.Environment) -> HttpExtension:
    """`ir.http`, carrying the protocol its implementation is pinned to.

    Both spellings reach the same object. Every hook `HttpExtension` declares
    except `routing_map` is a `classmethod` on `ir.http`, so `registry["ir.http"]._match`
    and `env["ir.http"]._match` are the same bound callable, and the protocol
    describes exactly that bound surface -- `test_ir_http_contract` compares it
    against the model hook by hook, dropping the leading `self`. One return type
    therefore serves a registry and an environment alike.

    Neither container can carry the type on its own. `Registry.__getitem__` is
    `str -> type[BaseModel]`, and the per-model `Literal` overloads on
    `Environment.__getitem__` reach only protocols that `odoo/orm` owns, which
    `HttpExtension` is not and must not become: `orm` may not import `http`.
    """
    return cast("HttpExtension", source["ir.http"])
