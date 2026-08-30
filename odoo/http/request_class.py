import contextlib
import functools
import logging
import time
from collections.abc import Callable, Iterable
from typing import Any

import babel.core
import werkzeug.datastructures
import werkzeug.exceptions

import odoo
from odoo.libs.json import loads as _fast_loads
from odoo.libs.worker_thread import current_worker_thread
from odoo.modules.registry import Registry
from odoo.tools import profiler

from ._csrf import _RequestCsrfMixin
from ._response import _RequestResponseMixin
from ._serve import _RequestServeMixin
from .constants import (
    DEFAULT_LANG,
    SESSION_LIFETIME,
    SESSION_ROTATION_EXCLUDED_PATHS,
    SESSION_ROTATION_INTERVAL,
    get_default_session,
)
from .dispatcher import _dispatchers
from .geoip import GeoIP
from .helpers import (
    clear_db_list_cache,
    get_session_max_inactivity,
)
from .session import Session
from .wrappers import FutureResponse, HTTPRequest, Response, cookie_name

_logger = logging.getLogger(__name__)

_UNIONED_HEADERS = frozenset({"vary"})


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


# Resolve through the package's public ``db_list``, not around it.
#
# ``odoo.http.db_list`` is the name the database selector calls, the name
# ``iot_drivers`` replaces to say "this box serves no database", and the name
# ``test_http`` patches. Reaching past it into ``odoo.service.db`` -- which is
# what a private copy of the listing did -- made every one of those a half
# measure: it changed what was *listed* and not what was *resolved*.
#
# The import is function-local because ``odoo.http.__init__`` imports this
# module, so the package cannot be reached at import time. Measured at 211 ns
# against a 19 ns module-global lookup, once per ``_get_session_and_dbname`` and
# once more on the monodb path -- against 16 us to read a session off disk and 29
# to write one, so it is not worth a cached module reference. Frozen at
# 2026-08-29; re-measure before treating it as a cost.
def _monodb_dblist(host: str) -> list[str]:
    from odoo import http

    return http.db_list(force=True, host=host)


clear_monodb_cache = clear_db_list_cache


class Request(_RequestServeMixin, _RequestResponseMixin, _RequestCsrfMixin):
    def __init__(self, httprequest: HTTPRequest, app: Any) -> None:
        self.app = app

        self.httprequest: HTTPRequest = httprequest
        self.future_response: FutureResponse = FutureResponse()
        self.dispatcher = _dispatchers["http"](self)
        self._params: dict[str, Any] = {}
        self._params_source: Callable[[], dict[str, Any]] | None = None

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
        from odoo import http

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
        if session.db and http.db_filter([session.db], host=host):
            dbname = session.db
            if header_dbname and header_dbname != dbname:
                e = (
                    f"The session cookie is bound to database {dbname!r} and the "
                    f"X-Odoo-Database header names {header_dbname!r}. Send one or "
                    f"the other, or make them agree."
                )
                raise werkzeug.exceptions.Forbidden(e)
        elif header_dbname:
            session.can_save = False
            if http.db_filter([header_dbname], host=host):
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

    @property
    def params(self) -> dict[str, Any]:
        # Materialised on first read, so that a path with no endpoint does not
        # pay for a body nothing is going to look at.
        #
        # `_serve_ir_http_fallback` used to spell this `self.params =
        # self.get_http_params()`, which reads `httprequest.form` and
        # `httprequest.files` and therefore decodes the WHOLE body -- measured:
        # `request.params` on an unmatched path held a 1 000 000-character string
        # for a 1 MB form post, and a `FileStorage` wrapping 3 000 000 bytes for a
        # multipart one, at ~0.7 ms per MB. It cannot simply be dropped: `base`'s
        # `_serve_fallback` never reads `params`, but `website`'s does
        # (`_build_url_w_params(redirect.url_to, request.params)`). Deferring it
        # is what serves both -- the module that needs the body still gets it,
        # and the unauthenticated 404 that nobody routed stops decoding one.
        source = self._params_source
        if source is not None:
            self._params_source = None
            self._params = source()
        return self._params

    @params.setter
    def params(self, params: dict[str, Any]) -> None:
        self._params_source = None
        self._params = params

    def update_env(
        self,
        user: int | Any | None = None,
        context: dict[str, Any] | None = None,
        su: bool | None = None,
    ) -> None:
        env = self.env
        assert env is not None, "update_env() needs a database-bound request"
        self.env = env = env(None, user, context, su)
        env.transaction.default_env = env
        current_worker_thread().uid = env.uid

    def update_context(self, **overrides: Any) -> None:
        env = self.env
        assert env is not None, "update_context() needs a database-bound request"
        self.update_env(context=env.context | overrides)

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
        registry = self.registry
        sanitized = registry is not None
        memo = self._cookies_memo
        if memo is not None and memo[0] is sanitized:
            return memo[1]

        cookies = werkzeug.datastructures.MultiDict(self.httprequest.cookies)
        if registry is not None:
            registry["ir.http"]._sanitize_cookies(cookies)
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
            self.env = odoo.api.Environment(
                cr, self.session.uid, self.session.context or {}
            )

    def _inject_future_response(self, response: Response) -> Response:
        headers = response.headers
        staged = self.future_response.headers

        staged_cookies = staged.getlist("Set-Cookie")
        if staged_cookies:
            staged_names = {cookie_name(cookie) for cookie in staged_cookies}
            kept = [
                cookie
                for cookie in headers.getlist("Set-Cookie")
                if cookie_name(cookie) not in staged_names
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
            elif sess.is_dirty:
                # `modified` here would be `is_dirty`: the branch above already
                # claimed every state where `content_changed` holds.
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
