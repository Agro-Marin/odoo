import time
from collections.abc import Iterable

CORS_MAX_AGE = 60 * 60 * 24

SAFE_HTTP_METHODS = ("GET", "HEAD", "OPTIONS")

DEFAULT_ALLOWED_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")

STATIC_ALLOWED_METHODS = ("GET", "HEAD")
"""What a ``/<module>/static/<path>`` URL answers.

A file on disk is a read-only resource, and the static branch runs ahead of the
router, so no route can ever narrow it: whatever this names is what the whole
static tree accepts.
"""


def allow_header(methods: Iterable[str] | None = None) -> str:
    """Render the ``Allow`` header for a resource that accepts *methods*.

    ``OPTIONS`` is appended rather than declared by the caller because the
    framework answers it unconditionally -- :meth:`Dispatcher.pre_dispatch`
    replies 204 to a bare ``OPTIONS`` on every route, and
    :func:`rule_routing_kwargs` widens every rule's method allow-list to let it
    through. An ``Allow`` that omits it advertises less than the server does,
    which is how the entry point's rejection of ``TRACE`` came to name six
    verbs against ``pre_dispatch``'s seven.
    """
    # `is None`, not `or`: an EMPTY collection means "this resource accepts
    # nothing", which must not silently widen to the full default set.
    if methods is None:
        methods = DEFAULT_ALLOWED_METHODS
    return ", ".join(dict.fromkeys([*methods, "OPTIONS"]))


CORS_DEFAULT_ALLOWED_METHODS = ("GET", "POST")

REJECTED_HTTP_METHODS = ("TRACE",)

CSRF_TOKEN_MAX_AGE = 60 * 60 * 24 * 365

DEFAULT_LANG = "en_US"


def get_default_session() -> dict[str, object]:
    return {
        "context": {},
        "create_time": time.time(),
        "db": None,
        "debug": "",
        "login": None,
        "uid": None,
        "session_token": None,
        "_trace": [],
    }


DEFAULT_MAX_CONTENT_LENGTH = 128 * 1024 * 1024

MISSING_CSRF_WARNING = """\
No CSRF validation token provided for path %r

Odoo URLs are CSRF-protected by default (when accessed with unsafe
HTTP methods). See
https://www.odoo.com/documentation/master/developer/reference/addons/http.html#csrf
for more details.

* if this endpoint is accessed through Odoo via py-QWeb form, embed a CSRF
  token in the form, Tokens are available via `request.csrf_token()`
  can be provided through a hidden input and must be POST-ed named
  `csrf_token` e.g. in your form add:
      <input type="hidden" name="csrf_token" t-att-value="request.csrf_token()"/>

* if the form is generated or posted in javascript, the token value is
  available as `csrf_token` on `web.core` and as the `csrf_token`
  value in the default js-qweb execution context

* if the form is accessed by an external third party (e.g. REST API
  endpoint, payment gateway callback) you will need to disable CSRF
  protection (and implement your own protection if necessary) by
  passing the `csrf=False` parameter to the `route` decorator.
"""

NOT_FOUND_NODB = """\
<!DOCTYPE html>
<title>404 Not Found</title>
<h1>Not Found</h1>
<p>No database is selected and the requested URL was not found in the server-wide controllers.</p>
<p>Please verify the hostname, <a href=/web/login>login</a> and try again.</p>

<!-- Alternatively, use the X-Odoo-Database header. -->
"""

ENSURE_DB_PATHS: set[str] = set()
ENSURE_DB_PATH_PREFIXES: tuple[str, ...] = ()
"""A tuple, not a set, because its only reader feeds it to ``str.startswith``.

``startswith`` takes a tuple and nothing else, so a set here means the sole
call site rebuilds one on every request that loses its database.
"""


def register_ensure_db_paths(*paths: str, prefixes: Iterable[str] = ()) -> None:
    global ENSURE_DB_PATH_PREFIXES  # noqa: PLW0603  the module owns this registry
    ENSURE_DB_PATHS.update(paths)
    ENSURE_DB_PATH_PREFIXES = tuple(
        dict.fromkeys((*ENSURE_DB_PATH_PREFIXES, *prefixes))
    )


def is_ensure_db_path(path: str) -> bool:
    """Whether *path* insists on a database, exactly or by registered prefix.

    A function rather than two names the caller combines: the prefixes are
    rebound on every registration, so an importer holding the tuple itself
    would answer against whatever was registered when it was imported.
    """
    return path in ENSURE_DB_PATHS or path.startswith(ENSURE_DB_PATH_PREFIXES)


ROUTING_KEYS = frozenset(
    {
        "defaults",
        "subdomain",
        "build_only",
        "strict_slashes",
        "redirect_to",
        "alias",
        "host",
        "methods",
        "websocket",
    }
)

SESSION_LIFETIME = 60 * 60 * 24 * 7

SESSION_ROTATION_INTERVAL = 60 * 60 * 3

SESSION_DELETION_TIMER = 120

SESSION_ROTATION_EXCLUDED_PATHS: set[str] = set()


def register_session_rotation_excluded_paths(*paths: str) -> None:
    SESSION_ROTATION_EXCLUDED_PATHS.update(paths)


STORED_SESSION_BYTES = 42

STATIC_CACHE = 60 * 60 * 24 * 7

STATIC_CACHE_LONG = 60 * 60 * 24 * 365

DB_MONODB_CACHE_TTL = 5.0
