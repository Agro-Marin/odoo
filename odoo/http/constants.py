import time

# The validity duration of a preflight response, one day.
CORS_MAX_AGE = 60 * 60 * 24

# The HTTP methods that do not require a CSRF validation.
SAFE_HTTP_METHODS = ("GET", "HEAD", "OPTIONS", "TRACE")

# The default csrf token lifetime (one year). When used as the
# time-limit of :meth:`Request.csrf_token`, the embedded ``max_ts`` is
# ``int(now + max_age)``, so it changes on every issuance (per-second
# granularity) and effectively acts as a per-token salt, defeating
# BREACH-style compression-ratio attacks that need a stable token to
# recover bytes one at a time.
CSRF_TOKEN_MAX_AGE = 60 * 60 * 24 * 365

# The default lang to use when the browser doesn't specify it
DEFAULT_LANG = "en_US"


def get_default_session() -> dict[str, object]:
    """The dictionary to initialise a new session with."""
    return {
        "context": {},  # 'lang': request.default_lang()  # must be set at runtime
        "create_time": time.time(),
        "db": None,
        "debug": "",
        "login": None,
        "uid": None,
        "session_token": None,
        "_trace": [],
    }


DEFAULT_MAX_CONTENT_LENGTH = 128 * 1024 * 1024  # 128MiB

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

# Paths whose controllers call ``web.ensure_db()`` and therefore must, when the
# database becomes unusable mid-request, drop the ``?db=`` query parameter and
# retry without a database rather than surfacing the registry error. Matched by
# exact path or the ``ENSURE_DB_PATH_PREFIX`` prefix. ``/test_http/ensure_db``
# only resolves when the ``test_http`` addon is installed; it is inert otherwise.
ENSURE_DB_PATH_PREFIX = "/odoo/"
ENSURE_DB_PATHS = frozenset({"/odoo", "/web", "/web/login", "/test_http/ensure_db"})

# The @route arguments to propagate from the decorated method to the
# routing rule. ``frozenset`` (not a plain ``set``): this is a shared,
# read-only module global consumed by ``submap(endpoint.routing, ROUTING_KEYS)``
# in both ``application.py`` and ``ir_http``; freezing it makes accidental
# mutation of the shared constant impossible rather than merely unlikely.
ROUTING_KEYS = frozenset({
    "defaults",
    "subdomain",
    "build_only",
    "strict_slashes",
    "redirect_to",
    "alias",
    "host",
    "methods",
    "websocket",
})

# The default duration of a user session cookie. Inactive sessions are reaped
# server-side as well with a threshold that can be set via an optional
# config parameter `sessions.max_inactivity_seconds` (default: SESSION_LIFETIME)
SESSION_LIFETIME = 60 * 60 * 24 * 7

# The default duration (3h) before a session is rotated, changing the
# session id (also on the cookie) but keeping the same content.
SESSION_ROTATION_INTERVAL = 60 * 60 * 3

# After a session is rotated, the session should be kept for a couple of
# seconds to account for network delay between multiple requests which are
# made at the same time and all use the same old cookie.
SESSION_DELETION_TIMER = 120

# URL paths for which automatic session rotation is disabled.
# Websocket polling hits these endpoints many times per minute; rotating the
# session there wastes a disk write on every call and reopens the soft-rotate
# race window — rotation should fire on a real user action instead.
SESSION_ROTATION_EXCLUDED_PATHS = (
    "/websocket/on_closed",
    "/websocket/peek_notifications",
    "/websocket/update_bus_presence",
)

# The amount of bytes (characters) of the session id that remain stable
# across a "soft" rotation. These first ``STORED_SESSION_BYTES`` characters
# are used to compute the CSRF token (so it survives soft rotation) and
# to correlate device-log rows. 42 base64-urlsafe characters yield about
# 252 bits of entropy; see :meth:`FilesystemSessionStore.generate_key`
# for the full collision analysis.
STORED_SESSION_BYTES = 42

# The cache duration for static content from the filesystem, one week.
STATIC_CACHE = 60 * 60 * 24 * 7

# The cache duration for content where the url uniquely identifies the
# content (usually using a hash), one year.
STATIC_CACHE_LONG = 60 * 60 * 24 * 365

# Monodb detection — the database-less request fast path in
# ``Request._get_session_and_dbname`` calls ``db_list(force=True)``, which issues
# a ``pg_database`` catalog query whenever a ``dbfilter`` is configured (the
# ``--database`` allowlist path skips PG). That query ran on EVERY db-less
# request: anonymous traffic, bots, health checks. ``db_list_for_monodb``
# memoises the per-host result for this many seconds, so a burst of such requests
# shares a single query. Staleness is benign and self-healing: a freshly created
# DB is detected after at most this delay (until then the request falls through
# to the DB selector), and a dropped DB that is still cached routes to a
# ``RegistryError`` that the WSGI entrypoint already recovers from. Local DB
# create/drop runs in a separate code path with no cross-worker cache hook, so
# this TTL — not invalidation — is the backstop. Only the HTTP monodb path is
# cached; the shared ``list_dbs`` (DB-manager and cron existence checks that need
# freshness) is deliberately left uncached.
DB_MONODB_CACHE_TTL = 5.0


# GeoIP / MaxMind — only available if geoip2 is installed.
# maxminddb is a transitive dependency of geoip2; we import them together
# so either both modules are available or both are ``None``. Callers MUST
# still guard code paths that reference ``maxminddb.InvalidDatabaseError``
# or ``geoip2.errors.AddressNotFoundError`` with an ``if geoip2 is not None``
# check — otherwise an ``AttributeError`` is raised when Python evaluates
# the except-clause type expressions against ``None``.


class _GeoIPNull:
    """Chainable null sentinel returned by :class:`GeoIP` when geoip2 isn't installed.

    Mimics an empty geoip2 record so chained access (``g.country.iso_code``,
    ``g.location.latitude``) returns this same instance instead of raising,
    while ``bool(g)`` and ``g == None`` are False/True respectively.
    """
    __slots__ = ()

    def __getattr__(self, _name):
        return self

    def __bool__(self):
        return False

    def __eq__(self, other):
        return other is self or other is None

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(None)

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __getitem__(self, _key):
        # Subdivisions[0] etc. are always gated by truthiness in callers.
        raise IndexError

    def __str__(self):
        return ""

    def __repr__(self):
        return "<GeoIPNull>"


_GEOIP_NULL = _GeoIPNull()

try:
    import geoip2.database
    import geoip2.errors
    import geoip2.models
    import maxminddb

    GEOIP_EMPTY_COUNTRY = geoip2.models.Country(None)
    GEOIP_EMPTY_CITY = geoip2.models.City(None)
except ImportError:
    geoip2 = None
    maxminddb = None
    GEOIP_EMPTY_COUNTRY = _GEOIP_NULL
    GEOIP_EMPTY_CITY = _GEOIP_NULL
