import contextlib
import functools
import logging
import threading
import time
from typing import Any

import babel.core
import werkzeug.datastructures
import werkzeug.exceptions

import odoo
from odoo.libs.json import loads as _fast_loads
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


@functools.lru_cache(maxsize=1)
def _all_dbs_cached(_ttl_bucket: int) -> tuple[str, ...]:
    # Host-independent catalog read cached under a single entry (see
    # :data:`DB_MONODB_CACHE_TTL`): a burst of db-less requests across many Hosts
    # costs one ``pg_database`` query per TTL bucket, not one per host. The key
    # ``_ttl_bucket`` (``int(time()//DB_MONODB_CACHE_TTL)``) expires the entry
    # every TTL seconds; ``maxsize=1`` keeps only the live bucket; a tuple is
    # cached so the shared entry can't be mutated. ``_list_all_dbs`` resolves from
    # this module's namespace, keeping the ``request_class._list_all_dbs`` test
    # monkeypatch effective.
    return tuple(_list_all_dbs(force=True))


def _monodb_dblist(host: str) -> list[str]:
    """Databases visible for monodb detection, filtered for ``host``.

    The expensive catalog read is memoised host-independently (see
    :func:`_all_dbs_cached` and :data:`DB_MONODB_CACHE_TTL` for the staleness
    contract); the cheap, host-dependent :func:`db_filter` (whose regex is itself
    cached) runs per call. Only this db-less detection path is cached; the shared
    :func:`db_list` is not. Returns a fresh, caller-owned list.
    """
    all_dbs = _all_dbs_cached(int(time.time() // DB_MONODB_CACHE_TTL))
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

    def __init__(self, httprequest: HTTPRequest, app: Any = None) -> None:
        # ``app`` is the :class:`Application` serving this request.
        # ``Application.__call__`` injects ``app=self``, making the dependency
        # explicit on the hot path instead of a ``root`` singleton lazy import;
        # the fallback keeps standalone constructors (tests, tooling) working and
        # lets a test inject a fake app. ``Any`` (not ``Application``) avoids a
        # request_class<->application import cycle, staying ``test_pep649``-clean.
        if app is None:
            from .application import root

            app = root
        self.app = app

        self.httprequest: HTTPRequest = httprequest
        self.future_response: FutureResponse = FutureResponse()
        self.dispatcher = _dispatchers["http"](self)  # until we match
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
            # ``get()`` honours ``renew_missing=True``, returning a fresh sid when
            # the file is missing. Do NOT override ``session.sid`` back to the
            # client value — that lets a client dictate their own session id,
            # weakening session-fixation defence (hard rotation on login is the
            # primary mitigation, see :meth:`Session.finalize`).
            session = root.session_store.get(sid)

        for key, val in get_default_session().items():
            session.setdefault(key, val)
        # A hand-edited / cross-version session file can carry ``"context": null``;
        # ``setdefault`` won't overwrite that ``None``, so ``.get("lang")`` and
        # later in-place ``context[...] = ...`` would AttributeError — a 500 on
        # every request with that cookie. Normalise a non-dict context to a fresh
        # dict here (the getter can't coerce on read: callers mutate it in place).
        if not isinstance(session.context, dict):
            session.context = {}
        if not session.context.get("lang"):
            session.context["lang"] = self.default_lang()

        dbname = None
        # HTTP/1.0 or malformed clients may omit Host; fall back to "" (db_filter's
        # default) rather than KeyError-ing the request into a 500.
        host = self.httprequest.environ.get("HTTP_HOST", "")
        header_dbname = self.httprequest.headers.get("X-Odoo-Database")
        if session.db and db_filter([session.db], host=host):
            dbname = session.db
            if header_dbname and header_dbname != dbname:
                e = "Cannot use both the session_id cookie and the x-odoo-database header."
                raise werkzeug.exceptions.Forbidden(e)
        elif header_dbname:
            # The X-Odoo-Database header marks a stateless API call, so the session
            # is never persisted — even when ``db_filter`` rejects the named db and
            # the request is served db-less. Only API clients send it (browsers
            # never do), so degrading to "no session save" is harmless.
            session.can_save = False  # stateless
            if db_filter([header_dbname], host=host):
                dbname = header_dbname
        else:
            # Memoised per host (short TTL): otherwise this ``pg_database`` query
            # runs on every db-less request. See ``_monodb_dblist``.
            all_dbs = _monodb_dblist(host)
            if len(all_dbs) == 1:
                dbname = all_dbs[0]  # monodb

        if session.db != dbname:
            if session.db:
                _logger.warning(
                    "Logged into database %r, but dbfilter rejects it; logging session out.",
                    session.db,
                )
                session.logout(keep_db=False)
            session.db = dbname

        # Baseline the session after framework setup so application changes —
        # including in-place nested mutation (``session.context[...] = ...``) —
        # are detected by ``is_modified`` at save time.
        session.mark_clean()
        return session, dbname

    # =====================================================
    # Getters and setters
    # =====================================================
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
        # ``cr=None`` keeps the current cursor: ``Environment.__call__`` resolves
        # ``cr = self.cr if cr is None else cr``.
        self.env = self.env(None, user, context, su)
        self.env.transaction.default_env = self.env
        threading.current_thread().uid = self.env.uid

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
            # ``parse_locale`` returns a 4- or 5-tuple (5th is a modifier, e.g.
            # ``it-IT@euro``, which a client can send via Accept-Language). Slice
            # to the first two so a modifier resolves instead of ValueError-ing.
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
        if self.registry:
            self.registry["ir.http"]._sanitize_cookies(cookies)
        return werkzeug.datastructures.ImmutableMultiDict(cookies)

    # =====================================================
    # Helpers
    # =====================================================
    # CSRF helpers (``csrf_token``/``validate_csrf``) live on
    # :class:`_RequestCsrfMixin`.

    def default_context(self) -> dict[str, Any]:
        # ``get_default_session()['context']`` is ``{}`` today, so ``lang`` is the
        # only effective key. Add new keys here explicitly rather than a
        # ``dict|dict`` merge.
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
        # orjson parses UTF-8 bytes directly (RFC 8259), so feed it the raw body
        # and skip werkzeug's decode-to-str. Invalid UTF-8 (already malformed JSON)
        # raises the same ValueError callers handle.
        return _fast_loads(self.httprequest.get_data())

    def _get_profiler_context_manager(self) -> contextlib.AbstractContextManager:
        """
        Get a profiler when the profiling is enabled and the requested
        URL is profile-safe. Otherwise, get a context-manager that does
        nothing.
        """
        if self.session.get("profile_session") and self.db:
            # ``.get(..., "")`` not ``[...]`` so a session with ``profile_session``
            # but no ``profile_expiration`` (manual edit) treats it as elapsed and
            # disables profiling instead of KeyError-ing the request.
            if self.session.get("profile_expiration", "") < str(
                odoo.fields.Datetime.now()
            ):
                # avoid having session profiling for too long if user forgets to disable profiling
                self.session["profile_session"] = None
                _logger.warning("Profiling expiration reached, disabling profiling")
            elif "set_profiling" in self.httprequest.path:
                _logger.debug("Profiling disabled on set_profiling route")
            elif self.httprequest.path.startswith("/websocket"):
                _logger.debug("Profiling disabled for websocket")
            elif odoo.evented:
                # only longpolling should be in a evented server, but this is an additional safety
                _logger.debug("Profiling disabled for evented server")
            else:
                try:
                    # ``.get`` with ir_profile's defaults (``collectors=[]``,
                    # ``params={}``) so a session missing those keys gets the
                    # default instead of a KeyError mislogged as "Failure during
                    # Profiler creation" by the broad ``except`` below.
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

    def _inject_future_response(self, response: Response) -> Response:
        """Merge ``future_response`` headers into ``response``.

        ``Set-Cookie`` (one per cookie) is accumulated; every other header on
        ``future_response`` (CORS, CSP, session-id replacement) is single-valued
        and is set, not extended — a blind :meth:`Headers.extend` duplicated them,
        yielding two ``Content-Type`` headers on hand-built responses.
        """
        # ``response.headers`` builds a fresh facade on each access; hoist it once.
        # The facade wraps the live werkzeug ``Headers``, so writes still land on
        # the real response.
        headers = response.headers
        for key, value in self.future_response.headers.items():
            if key.lower() == "set-cookie":
                headers.add(key, value)
            else:
                headers.set(key, value)
        return response

    # Response builders (``make_response``/``make_json_response``/``redirect``/
    # ``render``/``reroute``/``not_found``) live on
    # :class:`_RequestResponseMixin`.

    def _save_session(self, env: odoo.api.Environment | None = None) -> None:
        """
        Save a modified session on disk.

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

        # Computed once for both the save gate and the cookie check below: the
        # branches in between either don't mutate the session, or are rotations
        # that change ``sess.sid`` (making the cookie check true regardless).
        modified = sess.is_modified()

        if sess.should_rotate:
            root.session_store.rotate(sess, env)  # it saves
        elif (
            sess.uid
            and time.time() >= sess["create_time"] + SESSION_ROTATION_INTERVAL
            and self.httprequest.path not in SESSION_ROTATION_EXCLUDED_PATHS
        ):
            root.session_store.rotate(sess, env, True)
        elif modified:
            root.session_store.save(sess)

        # Compare against the RAW client cookie, not the sanitized ``self.cookies``
        # facade: the values are identical (``_sanitize_cookies`` ignores
        # ``session_id``), but reading the facade forces an ``ir.http`` call on the
        # session-save path of requests that never touch ``request.cookies``.
        cookie_sid = self.httprequest.session_id
        if modified or cookie_sid != sess.sid:
            # Logged-out sessions skip the DB query: the inactivity timeout only
            # matters when authenticated, and the connection may be dead.
            max_age = get_session_max_inactivity(env) if sess.uid else SESSION_LIFETIME
            # secure / samesite are filled in by ``_apply_cookie_defaults``
            # based on request scheme.
            self.future_response.set_cookie(
                "session_id",
                sess.sid,
                max_age=max_age,
                httponly=True,
            )


# Routing methods (`_set_request_dispatcher`, `_serve_static`, `_serve_db`,
# `_serve_nodb`, `_update_served_exception`, `_serve_ir_http_fallback`,
# `_serve_ir_http`) live on :class:`_RequestServeMixin` in `_serve.py`.
