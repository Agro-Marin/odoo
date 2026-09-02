# `odoo/http/` — the HTTP layer / WSGI application

This package prepares and dispatches every HTTP request to its controller: from
a raw request arriving on the WSGI entrypoint to a `Request` reaching a module
controller with a fully set-up ORM.

Application developers meet this package through `Controller` and the `@route`
decorator, which register the methods that deliver web content to matching URLs.

`doc/architecture/runtime.md` sketches this flow in three lines and
flattens it deliberately; **this file is the canonical, unflattened version.**
It lived in
`odoo/http/__init__.py`'s module docstring until `4ffeacacd8c` stripped
docstrings from `odoo/`, which left the sketch as the only surviving copy. It is
a document rather than a docstring now so that the strip policy and the call
graph stop competing for the same lines.

## Call graph

Every processing layer a request passes through before the `@route`-decorated
endpoint runs:

```
Application.__call__
    if path is like '/<module>/static/<path>':
        Request._serve_static

    elif not request.db:
        Request._serve_nodb
            App.nodb_routing_map.match
            Dispatcher.pre_dispatch
            Dispatcher.dispatch
                route_wrapper
                    endpoint
            Dispatcher.post_dispatch

    else:
        Request._serve_db
            env['ir.http']._match
            if not match:
                transaction.retrying(Request._serve_ir_http_fallback)
                    env['ir.http']._serve_fallback
                    env['ir.http']._post_dispatch
            else:
                transaction.retrying(Request._serve_ir_http)
                    env['ir.http']._authenticate
                    env['ir.http']._pre_dispatch
                    Dispatcher.pre_dispatch
                    Dispatcher.dispatch
                        env['ir.http']._dispatch
                            route_wrapper
                                endpoint
                    env['ir.http']._post_dispatch
```

The `Request._serve_*` methods are defined on `_RequestServeMixin` in
`_serve.py`; `Request` (in `request_class.py`) composes it.

## The stages

**`Application.__call__`** — WSGI entry point. Sanitizes the request, wraps it in
a werkzeug request and itself in an Odoo HTTP request, exposes it at
`http.request`, then forwards to `_serve_static`, `_serve_nodb` or `_serve_db`
depending on the request path and the presence of a database. Also responsible
for logging any error and encapsulating it in an HTTP error response.

**`Request._serve_static`** — streams an already-resolved file via
`Stream.get_response`. It does **not** resolve the path: `Application.get_static_file`
does, before the request reaches here, with `file_path()` plus a
`Path.resolve().is_relative_to()` containment check. There is one resolver on
purpose — a second one lived in this method until it was found to be unreachable.

**`Request._serve_nodb`** — handles `@route(auth='none')` endpoints when there is
no database connection. It matches the `auth='none'` endpoint from the request
path and delegates to the `Dispatcher`. An unmatched path infers a dispatcher
from the request's media type, exactly as `_serve_db` does, so a JSON client is
answered in JSON and a browser gets the `NOT_FOUND_NODB` page.

**`Request._serve_db`** — handles every non-static request when a database can be
reached. Opens a registry, manages the request cursor and environment, and
decides read-only versus read/write: `check_signaling`, `match` and
`serve_fallback` share one read-only cursor; `_serve_ir_http` reuses that same
(reset) read-only cursor, or a new read/write one.

**`Request._serve_aborted`** — the short path for a request werkzeug rejected
before dispatch; it does not appear in the graph above. An exception carrying
its own response (`abort(prepare_no_content_response())`, the CORS preflight) is delivered
verbatim; a status-less one goes through the dispatcher, so the error body
matches the route's media type rather than always being werkzeug's HTML page.

**`service.transaction.retrying`** — manages the cursor, the environment, and the
exceptions raised while executing the wrapped callable. Recovers from
serialization errors; resets the environment and **re-raises** everything else.
It does *not* attach an HTTP response — `_serve._update_served_exception`, which
wraps both `retrying()` calls, is what asks `ir.http._handle_error` for one. The
read-only → read/write promotion is `_serve_db`'s, not `retrying`'s: it catches
`psycopg.errors.ReadOnlySqlTransaction`, replays the retry participant and calls
`retrying()` a second time on a fresh read/write cursor. `retrying` also
performs the commit: `env.cr.commit()` is the last thing it does once the
callable returns.

**`ir.http._match`** — matches the controller endpoint corresponding to the
request path. Note the significant override for portal and website in the
`http_routing` module.

**`ir.http._serve_fallback`** — finds alternative ways to serve a request whose
path matches no controller: an attachment URL, a blog page, and so on.

**`ir.http._authenticate`** — ensures the user on the current environment
satisfies `@route(auth=...)`. Using the ORM outside abstract models is unsafe
before this runs.

**`ir.http._pre_dispatch` / `Dispatcher.pre_dispatch`** — prepares the system for
the request; often saves extra query-string parameters in the session (`?debug=1`).

**`ir.http._dispatch` / `Dispatcher.dispatch`** — deserializes the request body
into `request.params` according to `@route(type=...)`, calls the endpoint, and
serializes the return value into a `Response`.

**`ir.http._post_dispatch` / `Dispatcher.post_dispatch`** — post-processes the
response: injects headers such as Content-Security-Policy, and writes the
session (`Request._save_session()`), which is therefore saved *before* the commit
`retrying` performs.

**`ir.http._handle_error`** — absent from the graph; called for unmanaged
exceptions (serialization or read-only) raised inside
`service.transaction.retrying`. Returns an HTTP response wrapping the error.

**`Application._finalize_error_response`** — the error response built above
bypasses the normal dispatch flow, so the entrypoint runs
`Dispatcher.post_dispatch` over it explicitly before handing it to the WSGI
server. Without that step an error response would carry none of what
post-dispatch contributes — CORS headers, the `session_id` cookie and the session
save behind it, CSP — which is why the error path is the *only* place that calls
post_dispatch out of band.

## Module map

`doc/architecture/module.md` groups these modules into `[foundation]`,
`[serving]` and `[features]` tiers; the direction between them is enforced by
the `http-features-below-serving` contract, which holds `[foundation]` below
`[serving]` as well.

| Module | Tier | Contents |
|---|---|---|
| `__init__.py` | — | Public API: re-exports every symbol of the package |
| `application.py` | serving | `Application`: the WSGI callable, static/nodb/db routing decision, error logging and `_finalize_error_response` |
| `_serve.py` | serving | `_RequestServeMixin`: `_serve_static`, `_serve_nodb`, `_serve_db`, `_serve_aborted`, `_serve_ir_http`, `_serve_ir_http_fallback` |
| `request_class.py` | serving | `Request`, composed from the serve / response / CSRF mixins |
| `_response.py` | serving | `_RequestResponseMixin`: `prepare_response`, `prepare_json_response`, redirects, `render` |
| `_csrf.py` | serving | `_RequestCsrfMixin`: CSRF token generation and validation |
| `dispatcher.py` | serving | `Dispatcher` and its three subclasses (`HttpDispatcher`, `JsonRPCDispatcher`, `Json2Dispatcher`), selected by `routing["type"]` |
| `routing.py` | serving | `route()`, the `route_wrapper` it builds, `LazyCompiledBuilder` / `FasterRule`, `prepare_routing_map` (used by both maps the framework serves from) and the routing-parameter registry |
| `controller.py` | serving | `Controller` and the controller registry |
| `session.py` | serving | `Session`, `FilesystemSessionStore`, session rotation and GC |
| `stream.py` | serving | `Stream`: file/attachment streaming and conditional responses |
| `wrappers.py` | serving | `HTTPRequest`, `_Response`, `Headers`, `ResponseCacheControl`, `prepare_no_content_response` — the werkzeug wrappers, cookie defaults, and the `HTTPException.get_response` override that keeps a status-less exception from answering 200. **`HTTPRequest.environ` is a filtered copy**: every `werkzeug.*`, `wsgi.*` and `socket*` key is dropped except `wsgi.url_scheme` and `werkzeug.proxy_fix.orig`, so `environ["wsgi.input"]` raises `KeyError` — `raw_environ` is the unfiltered one |
| `core.py` | serving | `_request_stack` (a werkzeug `LocalStack`), the `request` proxy bound to it, and `borrow_request` |
| `helpers.py` | serving | `content_disposition`, `rewind_uploaded_files`, `db_list` — the package's one database-listing entry point, cached and read by both the selector and `Request._get_session_and_dbname` — and the `dbfilter` machinery |
| `_retry.py` | serving | `RequestRetryParticipant`: restores the session and rewinds uploads when `retrying()` replays a handler, installed on `service.transaction` at import |
| `openapi.py` | features | `prepare_openapi_document`: an OpenAPI `3.1.0` document generated from the routing map |
| `_params.py` | features | `ParamSpec` and the annotation-driven coercion behind `@route(typed=True)` |
| `geoip.py` | features | `GeoIP` lookup exposed on the request (`_GeoIPNull` when unavailable) |
| `constants.py` | foundation | Package-wide constants, `prepare_allow_header`, and the session/ensure-db path registries with their `is_ensure_db_path` predicate |
| `exceptions.py` | foundation | the HTTP exception vocabulary addon code raises — werkzeug's `NotFound`, `Forbidden`, `BadRequest`, `Unauthorized`, `HTTPException`, `abort` and the rest, re-exported so a controller never imports werkzeug — plus `RegistryError`, `SessionExpiredException`, and `get_error_response`/`set_error_response` — the only sanctioned way to read and write the `error_response` an exception carries |
| `_protocols.py` | foundation | `HttpExtension` — the `Protocol` `ir.http` satisfies, pinned by `TestIrHttpImplementsProtocol`; `Endpoint`/`HasRouting`/`RoutedMethod` for the attributes `@route` stuffs onto a handler; `HasHttpStatus`. `RequestState` alone is `if TYPE_CHECKING:` — it is `object` at runtime |

## Related

- `doc/architecture/module.md` — the framework-wide subsystem map and the
  enforced dependency contracts, including `http-features-below-serving`.
- `doc/architecture/ARCHITECTURE.md` — the front door: context, forces,
  mechanisms, and the index of the views.
- `odoo/service/transaction.py` — `retrying()`, which owns the commit and the
  read-only → read/write promotion.
