import contextlib
import functools
import logging
import time
from collections.abc import Iterable
from typing import Any

import babel.core
import psycopg
import werkzeug.datastructures
import werkzeug.exceptions

import odoo
from odoo.libs.json import loads as _fast_loads
from odoo.libs.worker_thread import current_worker_thread
from odoo.modules.registry import Registry
from odoo.service.db import list_dbs as _list_all_dbs
from odoo.tools import profiler

from ._csrf import _RequestCsrfMixin
from ._response import _RequestResponseMixin
from ._serve import _RequestServeMixin
from .constants import (
    DB_MONODB_CACHE_TTL,
    DEFAULT_LANG,
    SESSION_LIFETIME,
    SESSION_ROTATION_EXCLUDED_PATHS,
    SESSION_ROTATION_INTERVAL,
    get_default_session,
)
from .dispatcher import _dispatchers
from .geoip import GeoIP
from .helpers import (
    db_filter,
    get_session_max_inactivity,
)
from .session import Session
from .wrappers import FutureResponse, HTTPRequest, Response

_logger = logging.getLogger(__name__)

_UNIONED_HEADERS = frozenset({"vary"})


def _cookie_name(set_cookie_value: str) -> str:
    """The cookie name of a ``Set-Cookie`` header value.

    ``"session_id=abc; Path=/; HttpOnly"`` -> ``"session_id"``. A cookie name
    cannot contain ``=``, so the first one always delimits it.
    """
    return set_cookie_value.partition("=")[0].strip()


def _union_header_tokens(values: Iterable[str]) -> str:
    """Combine comma-separated header token lists into one, order-preserving.

    Tokens are de-duplicated case-insensitively while keeping the first spelling
    seen. ``*`` absorbs everything: for ``Vary`` it means "varies on unspecified
    dimensions", which no list of named tokens can narrow.
    """
    seen: dict[str, str] = {}
    for value in values:
        for token in value.split(","):
            token = token.strip()
            if token:
                seen.setdefault(token.lower(), token)
    if "*" in seen:
        return "*"
    return ", ".join(seen.values())


@functools.lru_cache(maxsize=1)
def _all_dbs_cached(_ttl_bucket: int) -> tuple[str, ...]:
    return tuple(_list_all_dbs(force=True))


def _monodb_dblist(host: str) -> list[str]:
    """Databases visible for monodb detection, filtered for ``host``.

    The expensive catalog read is memoised host-independently (see
    :func:`_all_dbs_cached` and :data:`DB_MONODB_CACHE_TTL` for the staleness
    contract); the cheap, host-dependent :func:`db_filter` (whose regex is itself
    cached) runs per call. Only this db-less detection path is cached; the shared
    :func:`db_list` is not. Returns a fresh, caller-owned list.

    Degrades to ``[]`` when PostgreSQL is unreachable, like :func:`db_list`
    (whose ``OperationalError`` guard this cached path bypasses): monodb
    detection failing must serve the request db-less, not 500 it — this runs in
    ``_post_init`` for every cookie-less request, including static assets and
    ``/web/login``. ``lru_cache`` does not cache exceptions, so a failed probe
    is retried on the next request.
    """
    try:
        all_dbs = _all_dbs_cached(int(time.time() // DB_MONODB_CACHE_TTL))
    except psycopg.Error:
        return []
    return db_filter(list(all_dbs), host=host)


def clear_monodb_cache() -> None:
    """Drop the memoised monodb database list.

    For tests only (production relies on TTL expiry): they monkeypatch
    ``_list_all_dbs`` / ``db_filter`` per request and must not see a value cached
    under a prior patch.
    """
    _all_dbs_cached.cache_clear()


class Request(_RequestServeMixin, _RequestResponseMixin, _RequestCsrfMixin):
    """
    Wrapper around the incoming HTTP request with deserialized request
    parameters, session utilities and request dispatching logic.

    Concerns split across mixins for file-size hygiene:

    * :class:`_RequestServeMixin` — routing (``_serve_static``/``_serve_db``/
      ``_serve_nodb`` and helpers).
    * :class:`_RequestResponseMixin` — response builders (``make_response``,
      ``make_json_response``, ``redirect``, ``render``, ``reroute``).
    * :class:`_RequestCsrfMixin` — CSRF token issuance and validation.
    """

    def __init__(self, httprequest: HTTPRequest, app: Any) -> None:
        self.app = app

        self.httprequest: HTTPRequest = httprequest
        self.future_response: FutureResponse = FutureResponse()
        self.dispatcher = _dispatchers["http"](self)
        self.params: dict[str, Any] = {}

        self.geoip: GeoIP = GeoIP(httprequest.remote_addr, app=app)
        self.registry: Registry | None = None
        self.env: odoo.api.Environment | None = None
        self._post_init_done: bool = False

    def _post_init(self) -> None:
        if self._post_init_done:
            return
        self.session, self.db = self._get_session_and_dbname()
        self._post_init_done = True

    def _get_session_and_dbname(self) -> tuple[Session, str | None]:
        root = self.app

        sid = self.httprequest.session_id
        if not sid or not root.session_store.is_valid_key(sid):
            session = root.session_store.new()
        else:
            session = root.session_store.get(sid)

        for key, val in get_default_session().items():
            session.setdefault(key, val)
        if not isinstance(session.context, dict):
            session.context = {}
        if not session.context.get("lang"):
            session.context["lang"] = self.default_lang()
        if session.pop("_rotate_pending", None):
            session.should_rotate = True

        dbname = None
        host = self.httprequest.environ.get("HTTP_HOST", "")
        header_dbname = self.httprequest.headers.get("X-Odoo-Database")
        if session.db and db_filter([session.db], host=host):
            dbname = session.db
            if header_dbname and header_dbname != dbname:
                e = "Cannot use both the session_id cookie and the x-odoo-database header."
                raise werkzeug.exceptions.Forbidden(e)
        elif header_dbname:
            session.can_save = False
            if db_filter([header_dbname], host=host):
                dbname = header_dbname
        else:
            all_dbs = _monodb_dblist(host)
            if len(all_dbs) == 1:
                dbname = all_dbs[0]

        if session.db != dbname:
            if session.db:
                _logger.warning(
                    "Logged into database %r, but dbfilter rejects it; logging session out.",
                    session.db,
                )
                session.logout(keep_db=False)
            session.db = dbname

        session.mark_clean()
        return session, dbname

    def update_env(
        self,
        user: int | Any | None = None,
        context: dict[str, Any] | None = None,
        su: bool | None = None,
    ) -> None:
        """Update the environment of the current request.

        :param user: optional user/user id to change the current user
        :type user: int or :class:`res.users record<~odoo.addons.base.models.res_users.ResUsers>`
        :param dict context: optional context dictionary to change the current context
        :param bool su: optional boolean to change the superuser mode
        """
        self.env = self.env(None, user, context, su)
        self.env.transaction.default_env = self.env
        current_worker_thread().uid = self.env.uid

    def update_context(self, **overrides: Any) -> None:
        """
        Override the environment context of the current request with the
        values of ``overrides``. To replace the entire context, please
        use :meth:`~update_env` instead.
        """
        self.update_env(context=self.env.context | overrides)

    @functools.cached_property
    def best_lang(self):
        lang = self.httprequest.accept_languages.best
        if not lang:
            return None

        try:
            code, territory = babel.core.parse_locale(lang, sep="-")[:2]
            if territory:
                lang = f"{code}_{territory}"
            else:
                lang = babel.core.LOCALE_ALIASES[code]
            return lang
        except ValueError, KeyError:
            return None

    @functools.cached_property
    def cookies(self):
        cookies = werkzeug.datastructures.MultiDict(self.httprequest.cookies)
        if self.registry is not None:
            self.registry["ir.http"]._sanitize_cookies(cookies)
        return werkzeug.datastructures.ImmutableMultiDict(cookies)

    def default_context(self) -> dict[str, Any]:
        return {"lang": self.default_lang()}

    def default_lang(self) -> str:
        """Return the default user language for the request.

        :returns: Preferred language if specified or 'en_US'
        :rtype: str
        """
        return self.best_lang or DEFAULT_LANG

    def get_http_params(self) -> dict[str, Any]:
        """
        Extract key=value pairs from the query string and the forms
        present in the body (both application/x-www-form-urlencoded and
        multipart/form-data).

        :returns: The merged key-value pairs.
        :rtype: dict
        """
        return {
            **self.httprequest.args,
            **self.httprequest.form,
            **self.httprequest.files,
        }

    def get_json_data(self) -> Any:
        return _fast_loads(self.httprequest.get_data())

    def _get_profiler_context_manager(self) -> contextlib.AbstractContextManager:
        """
        Get a profiler when the profiling is enabled and the requested
        URL is profile-safe. Otherwise, get a context-manager that does
        nothing.
        """
        if self.session.get("profile_session") and self.db:
            if self.session.get("profile_expiration", "") < str(
                odoo.fields.Datetime.now()
            ):
                self.session["profile_session"] = None
                _logger.warning("Profiling expiration reached, disabling profiling")
            elif "set_profiling" in self.httprequest.path:
                _logger.debug("Profiling disabled on set_profiling route")
            elif self.httprequest.path.startswith("/websocket"):
                _logger.debug("Profiling disabled for websocket")
            elif odoo.evented:
                _logger.debug("Profiling disabled for evented server")
            else:
                try:
                    return profiler.Profiler(
                        db=self.db,
                        description=self.httprequest.full_path,
                        profile_session=self.session["profile_session"],
                        collectors=self.session.get("profile_collectors", []),
                        params=self.session.get("profile_params", {}),
                    )._get_cm_proxy()
                except Exception:
                    _logger.exception("Failure during Profiler creation")
                    self.session["profile_session"] = None

        return contextlib.nullcontext()

    def _reset_for_replay(self, cr: Any = None) -> None:
        """Return per-request state to what the FIRST dispatch attempt started from.

        A handler body can run more than once for a single client request: the
        read-only → read/write promotion in :meth:`_serve_db` replays it, and so
        does the serialization-retry loop in
        :func:`odoo.service.transaction.retrying`. A replay that inherits the
        aborted attempt's state is not a replay — it is a different request:

        * ``env`` — a handler that called :meth:`update_env` (user, context, and
          notably ``su=True``, which no ``ir.http._auth_method_*`` resets) before
          its failing write would pre-seed the retry with those privileges.
          Rebuilt from the session, the same expression that built attempt one.
        * ``future_response`` — headers are *staged* here and merged into the
          response at the end. ``Set-Cookie`` is accumulated (one per cookie), so
          a cookie set before the failing write is emitted once per attempt;
          everything staged is re-staged by the replayed run anyway.

        Both replay sites call this, so they cannot drift. ``params`` is NOT
        reset: the dispatcher rebuilds it from the (rewound) request body on each
        attempt. Uploaded files are rewound separately by
        :func:`~odoo.http.helpers.rewind_uploaded_files`, which the retry loop
        also shares.

        :param cr: cursor for the rebuilt environment; defaults to the current
            one. Pass it explicitly when the cursor is being swapped.
        """
        self.future_response = FutureResponse()
        if cr is None and self.env is not None:
            cr = self.env.cr
        if cr is not None:
            self.env = odoo.api.Environment(cr, self.session.uid, self.session.context)

    def _inject_future_response(self, response: Response) -> Response:
        """Merge ``future_response`` headers into ``response``.

        Single-valued headers (CORS, CSP, ``Content-Type``…) are *set*, not
        extended — a blind :meth:`Headers.extend` duplicated them, yielding two
        ``Content-Type`` headers on hand-built responses. A name staged more than
        once is appended after the first, so a legitimately repeatable header is
        not collapsed to its last value.

        LIST-valued headers are exempt from the override, because "override" is
        meaningless for them: both sides contributed real values and replacing
        one discards it. They are combined instead, per :data:`_UNIONED_HEADERS`
        and, for ``Set-Cookie``, by the name-wise merge below.

        * ``Set-Cookie`` repeats *across producers*, not just within the staging
          area: handlers set cookies straight on the response (``auth_totp``'s
          trusted-device cookie, ``web``'s ``content_density``, ``utm``'s
          attribution cookies, ``frontend_lang`` on website redirects) while the
          framework stages ``session_id`` here. ``set()`` on the staged one
          dropped *every* cookie the handler had put on the response — silently,
          on every session-modifying request, which is most of them.

          Appending instead keeps them, but then a staged cookie and a handler
          cookie of the SAME name both ship, and which one the browser stores is
          left to header order. Merge by cookie NAME: a staged cookie replaces
          its namesake and nothing else, so ``session_id`` wins deterministically
          while every unrelated handler cookie survives.
        * ``Vary`` is a token list, and ``pre_dispatch`` stages it for every
          ``cors_credentials`` route and every preflight. Overriding it would
          drop a handler's own ``Vary: Accept-Encoding`` and leave the response
          cached under a key that ignores an axis it really varies on.

        Everything else is single-valued (CORS origin, CSP, ``Content-Type``…):
        the staged value wins, so a route's declaration cannot be quietly
        weakened from inside a handler. A name staged more than once is appended
        after the first, so a repeatable header is never collapsed to its last
        value.
        """
        headers = response.headers
        staged = self.future_response.headers

        staged_cookies = staged.getlist("Set-Cookie")
        if staged_cookies:
            staged_names = {_cookie_name(cookie) for cookie in staged_cookies}
            kept = [
                cookie
                for cookie in headers.getlist("Set-Cookie")
                if _cookie_name(cookie) not in staged_names
            ]
            headers.setlist("Set-Cookie", kept + staged_cookies)

        overridden: set[str] = set()
        for key, value in staged.items():
            lowered = key.lower()
            if lowered == "set-cookie":
                continue
            if lowered in _UNIONED_HEADERS:
                headers.set(key, _union_header_tokens([*headers.getlist(key), value]))
            elif lowered in overridden:
                headers.add(key, value)
            else:
                headers.set(key, value)
                overridden.add(lowered)
        return response

    def _save_session(self, env: odoo.api.Environment | None = None) -> None:
        """
        Save a modified session on disk.

        Two different questions, deliberately kept apart. ``content_changed``
        asks whether the stored bytes differ, which is what makes a rewrite
        necessary. ``modified`` is the broader "does the client need to hear
        about this", and is additionally true for a bare :meth:`Session.touch`
        -- a request that only asks to extend the session's lifetime. Those get
        :meth:`~odoo.http.session.FilesystemSessionStore.keep_alive`, an
        ``utime``, rather than an atomic rewrite + fsync of identical bytes.
        Both still count as *written*, so the cookie is refreshed either way.

        ``expires=None`` is passed explicitly: the shared cookie default is a
        one-year ``Expires``, which would contradict the ``Max-Age`` computed
        here from the session's real lifetime. ``Max-Age`` wins wherever both are
        understood, so the second date only ever misinformed whoever read the
        header.

        :param env: an environment to compute the session token.
            MUST be left ``None`` (in which case it uses the request's
            env) UNLESS the database changed.
        """
        root = self.app

        sess = self.session
        if env is None:
            env = self.env

        if not sess.can_save:
            return

        content_changed = sess.has_content_changed()
        modified = sess.is_dirty or content_changed

        can_rotate = not sess.uid or (env is not None and not env.cr.closed)

        try:
            if sess.should_rotate and can_rotate:
                root.session_store.rotate(sess, env)
                written = True
            elif sess.should_rotate:
                sess["_rotate_pending"] = True
                root.session_store.save(sess)
                written = True
            elif (
                can_rotate
                and sess.uid
                and time.time() >= sess["create_time"] + SESSION_ROTATION_INTERVAL
                and self.httprequest.path not in SESSION_ROTATION_EXCLUDED_PATHS
            ):
                root.session_store.rotate(sess, env, True)
                written = True
            elif content_changed:
                root.session_store.save(sess)
                written = True
            elif modified:
                root.session_store.keep_alive(sess)
                written = True
            else:
                written = False
        except OSError:
            # Persisting the session failed (disk full, EACCES). The business
            # response already succeeded, so degrade rather than 500: leave the
            # client's *current* cookie in place instead of advancing it to a sid
            # with no file behind it. The old session file is intact — save()
            # now re-raises instead of half-writing, and hard rotation writes the
            # new file before removing the old — so the current cookie keeps
            # working and no silent logout follows (B4/B3).
            _logger.warning(
                "Could not persist session %r; keeping the current cookie",
                sess.sid,
                exc_info=True,
            )
            return

        on_disk = written or not sess.is_new

        cookie_sid = self.httprequest.session_id
        if on_disk and (modified or cookie_sid != sess.sid):
            max_age = get_session_max_inactivity(env) if sess.uid else SESSION_LIFETIME
            self.future_response.set_cookie(
                "session_id",
                sess.sid,
                max_age=max_age,
                expires=None,
                httponly=True,
            )
