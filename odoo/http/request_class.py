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
from odoo.service.db import register_catalog_listener
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
    return set_cookie_value.partition("=")[0].strip()


def _union_header_tokens(values: Iterable[str]) -> str:
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


@functools.lru_cache(maxsize=64)
def _monodb_dblist_cached(_ttl_bucket: int, host: str) -> tuple[str, ...]:
    return tuple(db_filter(list(_all_dbs_cached(_ttl_bucket)), host=host))


def _monodb_dblist(host: str) -> list[str]:
    """The databases *host* may pick from when nothing else names one.

    Reached by every request that carries neither a session database nor an
    ``X-Odoo-Database`` header -- which is every anonymous website hit and
    every request before login, the highest-volume path there is.

    The *filtering* is cached, not only the catalogue it reads. ``db_filter``
    walks the whole catalogue per call (``is_maintenance_db``, the dbfilter
    regex, the ``db_name`` allow-list), so caching the catalogue alone left an
    O(databases) scan on that path: 40us per request against 53 databases on
    the machine this was measured on, and it grows with the server.
    """
    try:
        return list(
            _monodb_dblist_cached(int(time.time() // DB_MONODB_CACHE_TTL), host)
        )
    except psycopg.Error:
        # An empty list here is indistinguishable, to every caller, from "this
        # instance serves no database": the monodb rule needs exactly one
        # survivor, so a session-less request answers 404 and says nothing
        # about why. `list_dbs` logs only failures of its SELECT -- the
        # `db_connect` and `.cursor()` above it are outside that try -- so a
        # cluster refusing connections lands here and nowhere else. It cost a
        # `web` test run an unreproducible 404 on a route that was fine.
        #
        # Logged, not raised: falling back to "no database" is the right
        # behaviour for a transient blip, and the 5 s TTL means the next
        # request retries. lru_cache does not memoise exceptions, so this
        # reflects live connectivity rather than one stale failure.
        _logger.warning(
            "Could not list databases to resolve a session-less request; "
            "answering as though this instance serves none.",
            exc_info=True,
        )
        return []


def clear_monodb_cache() -> None:
    _all_dbs_cached.cache_clear()
    _monodb_dblist_cached.cache_clear()


register_catalog_listener(clear_monodb_cache)
"""Expire the catalogue caches the moment this process changes the catalogue.

Until this was wired, ``clear_monodb_cache`` had no production caller at all --
every reference in four repos was a test. A database created or dropped through
the database manager stayed invisible, or visible, for the rest of the TTL, and
on a single-database deployment that is the difference between the selector
working and 404-ing right after a restore.
"""


class Request(_RequestServeMixin, _RequestResponseMixin, _RequestCsrfMixin):
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
        self.database_detached: bool = False
        self._cookies_memo: tuple[bool, Any] | None = None

    def detach_database(self) -> None:
        self.database_detached = True
        if self.env is not None and not self.env.cr.closed:
            self.env.cr.close()

    def _post_init(self) -> None:
        if self._post_init_done:
            return
        self.session, self.db = self._get_session_and_dbname()
        self._post_init_done = True

    def _get_session_and_dbname(
        self, sid: str | None = None
    ) -> tuple[Session, str | None]:
        root = self.app

        if sid is None:
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
        self.env = self.env(None, user, context, su)
        self.env.transaction.default_env = self.env
        current_worker_thread().uid = self.env.uid

    def update_context(self, **overrides: Any) -> None:
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

    @property
    def cookies(self):
        """The request cookies, with ``ir.http._sanitize_cookies`` applied.

        Memoised against *whether the sanitiser ran*, not once and for all.
        ``_sanitize_cookies`` is a security hook -- addons drop from it the
        cookies a visitor has not consented to -- and it needs a registry,
        which ``_serve_db`` only acquires part-way through the request. A plain
        ``cached_property`` therefore froze the **unsanitised** answer for the
        whole request if anything read it before then. Nothing does today; this
        makes that structural rather than a coincidence, at the cost of one
        extra rebuild on the first read after the registry lands.
        """
        sanitized = self.registry is not None
        memo = self._cookies_memo
        if memo is not None and memo[0] is sanitized:
            return memo[1]

        cookies = werkzeug.datastructures.MultiDict(self.httprequest.cookies)
        if sanitized:
            self.registry["ir.http"]._sanitize_cookies(cookies)
        result = werkzeug.datastructures.ImmutableMultiDict(cookies)
        self._cookies_memo = (sanitized, result)
        return result

    def default_context(self) -> dict[str, Any]:
        return {"lang": self.default_lang()}

    def default_lang(self) -> str:
        return self.best_lang or DEFAULT_LANG

    def get_http_params(self) -> dict[str, Any]:
        return {
            **self.httprequest.args,
            **self.httprequest.form,
            **self.httprequest.files,
        }

    def get_json_data(self) -> Any:
        return _fast_loads(self.httprequest.get_data())

    def _get_profiler_context_manager(self) -> contextlib.AbstractContextManager:
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
        self.future_response = FutureResponse()
        if cr is None and self.env is not None:
            cr = self.env.cr
        if cr is not None:
            self.env = odoo.api.Environment(cr, self.session.uid, self.session.context)

    def _inject_future_response(self, response: Response) -> Response:
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
