import contextlib
import functools
import logging
import threading
import time
from typing import Any

import babel.core
import werkzeug.datastructures

import odoo
from odoo.libs.json import loads as _fast_loads
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
from .geoip import GeoIP
from .helpers import (
    db_filter,
    db_list,
    get_session_max_inactivity,
)
from .session import Session
from .wrappers import FutureResponse, HTTPRequest, Response

_logger = logging.getLogger(__name__)


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

    def __init__(self, httprequest: HTTPRequest) -> None:
        self.httprequest: HTTPRequest = httprequest
        self.future_response: FutureResponse = FutureResponse()
        self.dispatcher = _dispatchers["http"](self)  # until we match
        self.params: dict[str, Any] = {}

        self.geoip: GeoIP = GeoIP(httprequest.remote_addr)
        self.registry: Registry | None = None
        self.env: odoo.api.Environment | None = None
        self._post_init_done: bool = False

    def _post_init(self) -> None:
        if self._post_init_done:
            return
        self.session, self.db = self._get_session_and_dbname()
        self._post_init_done = True

    def _get_session_and_dbname(self) -> tuple[Session, str | None]:
        from .application import (
            root,
        )

        sid = self.httprequest.session_id
        if not sid or not root.session_store.is_valid_key(sid):
            session = root.session_store.new()
        else:
            # ``get()`` honours ``renew_missing=True`` and returns a session
            # with a freshly generated sid when the file does not exist. Do
            # NOT override ``session.sid`` back to the client-supplied value
            # — that would let any client dictate their own session id,
            # weakening the defence-in-depth around session fixation (the
            # primary mitigation is the hard rotation performed by
            # :meth:`Session.finalize` on login).
            session = root.session_store.get(sid)

        for key, val in get_default_session().items():
            session.setdefault(key, val)
        if not session.context.get("lang"):
            session.context["lang"] = self.default_lang()

        dbname = None
        host = self.httprequest.environ["HTTP_HOST"]
        header_dbname = self.httprequest.headers.get("X-Odoo-Database")
        if session.db and db_filter([session.db], host=host):
            dbname = session.db
            if header_dbname and header_dbname != dbname:
                e = "Cannot use both the session_id cookie and the x-odoo-database header."
                raise werkzeug.exceptions.Forbidden(e)
        elif header_dbname:
            session.can_save = False  # stateless
            if db_filter([header_dbname], host=host):
                dbname = header_dbname
        else:
            all_dbs = db_list(force=True, host=host)
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

        session.is_dirty = False
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
        # Passing ``cr=None`` to ``env(...)`` keeps the current cursor; the
        # ``Environment.__call__`` body resolves ``cr = self.cr if cr is
        # None else cr`` before constructing the new environment.
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
            code, territory, _, _ = babel.core.parse_locale(lang, sep="-")
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
        # ``get_default_session()['context']`` is currently ``{}`` so the
        # only effective key is ``lang``. If the default session ever
        # acquires more context keys, add them here explicitly rather
        # than re-introducing a ``dict|dict`` merge that obscures intent.
        return {"lang": self.default_lang()}

    def default_lang(self) -> str:
        """Returns default user language according to request specification

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
        return _fast_loads(self.httprequest.get_data(as_text=True))

    def _get_profiler_context_manager(self) -> contextlib.AbstractContextManager:
        """
        Get a profiler when the profiling is enabled and the requested
        URL is profile-safe. Otherwise, get a context-manager that does
        nothing.
        """
        if self.session.get("profile_session") and self.db:
            # ``.get(..., "")`` (not ``[...]``) so a session that somehow has
            # ``profile_session`` without ``profile_expiration`` (manual edit,
            # cross-version migration) treats the missing expiration as
            # already-elapsed and disables profiling, instead of crashing the
            # request with KeyError.
            if self.session.get("profile_expiration", "") < str(odoo.fields.Datetime.now()):
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
                    # Use ``.get`` with the same defaults ir_profile sets
                    # (``collectors=[]``, ``params={}``) so a session missing
                    # those keys (cross-version migration, manual edit) gets
                    # the documented default instead of a KeyError caught only
                    # by the broad ``except`` below — which would log
                    # "Failure during Profiler creation" with a misleading
                    # traceback rooted in the missing-key error.
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

        ``Set-Cookie`` is the only header in our pipeline that can
        legitimately appear multiple times (one per cookie) and is
        accumulated. Every other header that the dispatcher / session
        save flow puts on ``future_response`` (CORS, Content-Security-
        Policy, custom session-id replacement) is single-valued in
        practice; using :meth:`Headers.extend` blindly duplicated them
        when both ``future_response`` and ``response`` had a value, which
        produced HTTP responses with two ``Content-Type`` headers when
        controllers built responses by hand.
        """
        for key, value in self.future_response.headers.items():
            if key.lower() == "set-cookie":
                response.headers.add(key, value)
            else:
                response.headers.set(key, value)
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
        from .application import (
            root,
        )

        sess = self.session
        if env is None:
            env = self.env

        if not sess.can_save:
            return

        if sess.should_rotate:
            root.session_store.rotate(sess, env)  # it saves
        elif (
            sess.uid
            and time.time() >= sess["create_time"] + SESSION_ROTATION_INTERVAL
            and self.httprequest.path not in SESSION_ROTATION_EXCLUDED_PATHS
        ):
            root.session_store.rotate(sess, env, True)
        elif sess.is_dirty:
            root.session_store.save(sess)

        cookie_sid = self.cookies.get("session_id")
        if sess.is_dirty or cookie_sid != sess.sid:
            # For logged-out sessions (e.g. after DB drop or explicit
            # logout), skip the DB query — the custom inactivity timeout
            # only matters for authenticated sessions, and the DB
            # connection may already be dead.
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


# Late import to break the Request <-> Dispatcher cycle.  ``_dispatchers``
# is referenced only inside ``Request.__init__`` at runtime (never at
# class-definition time), so moving the import below the class definition
# is safe.  dispatcher.py does the mirror move with
# ``from .request_class import Request`` at its own bottom, making the cycle
# resolvable regardless of which module Python loads first.
from .dispatcher import _dispatchers  # noqa: E402  — see note above
