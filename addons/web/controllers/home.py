import hashlib
import logging
import os
from typing import Any

import psycopg

import odoo.api
import odoo.db
import odoo.exceptions
from odoo import http
from odoo.exceptions import AccessError
from odoo.http import Response, request
from odoo.libs.json import dumps as json_dumps
from odoo.service import security
from odoo.tools import config, str2bool
from odoo.tools.json import orjson_default
from odoo.tools.misc import hmac
from odoo.tools.translate import LazyTranslate, _

from .utils import (
    _get_login_redirect_url,
    _is_local_url,
    ensure_db,
    is_user_internal,
)

_lt = LazyTranslate(__name__)
_logger = logging.getLogger(__name__)


# Shared parameters for all login/signup flows
SIGN_UP_REQUEST_PARAMS = {
    "db",
    "login",
    "debug",
    "token",
    "message",
    "error",
    "scope",
    "mode",
    "redirect",
    "redirect_hostname",
    "email",
    "name",
    "partner_id",
    "password",
    "confirm_password",
    "city",
    "country_id",
    "lang",
    "signup_email",
}
LOGIN_SUCCESSFUL_PARAMS = set()
CREDENTIAL_PARAMS = ["login", "password", "type"]


class Home(http.Controller):
    @http.route("/", type="http", auth="none")
    def index(
        self, s_action: str | None = None, db: str | None = None, **kw: Any
    ) -> Response:
        if (
            request.db
            and request.session.uid
            and not is_user_internal(request.session.uid)
        ):
            return request.redirect_query("/web/login_successful", query=request.params)
        return request.redirect_query("/odoo", query=request.params)

    def _web_client_readonly(self, rule: Any, args: Any) -> bool:
        return False

    # ideally, this route should be `auth="user"` but that doesn't work in non-monodb mode.
    @http.route(
        ["/web", "/odoo", "/odoo/<path:subpath>", "/scoped_app/<path:subpath>"],
        type="http",
        auth="none",
        readonly=_web_client_readonly,
    )
    def web_client(self, s_action: str | None = None, **kw: Any) -> Response:
        """Serve the main web client HTML page.

        Validates authentication, builds session info, and renders the
        ``web.webclient_bootstrap`` template with asset bundles.
        """
        ensure_db()
        if not request.session.uid:
            return request.redirect_query(
                "/web/login",
                query={"redirect": request.httprequest.full_path},
                code=303,
            )
        if kw.get("redirect") and _is_local_url(kw["redirect"]):
            return request.redirect(kw["redirect"], 303)
        if not security.check_session(request.session, request.env, request):
            msg = "Session expired"
            raise http.SessionExpiredException(msg)
        if not is_user_internal(request.session.uid):
            return request.redirect("/web/login_successful", 303)

        # Return value unused; kept for the side effect of extending the session lifetime.
        request.session.touch()

        # auth="none" doesn't populate the env user; restore it now that we know the uid.
        request.update_env(user=request.session.uid)
        try:
            if request.env.user:
                request.env.user._on_webclient_bootstrap()
            context = request.env["ir.http"].webclient_rendering_context()

            # Computed here rather than in session_info() so it's only ever sent on this
            # page, which is Cache-Control: no-store (see below).
            # Reuses the session-token fields so the secret rotates whenever a security
            # event (password/2FA change) invalidates the session token too.
            hmac_payload = (
                request.env.user._session_token_get_values()
            )  # order is stable, needed for a reproducible hmac
            session_info = context.get("session_info")
            session_info["browser_cache_secret"] = hmac(
                request.env(su=True), "browser_cache_key", hmac_payload
            )

            response = request.render("web.webclient_bootstrap", qcontext=context)
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Cache-Control"] = "no-store"
            response.set_cookie(
                "content_density", request.env["ir.http"].content_density()
            )
            return response
        except AccessError:
            return request.redirect("/web/login?error=access")

    @http.route(
        "/web/webclient/load_menus",
        type="http",
        auth="user",
        methods=["GET"],
        readonly=True,
    )
    def web_load_menus(
        self, lang: str | None = None, hash: str | None = None
    ) -> Response:
        """
        Loads the menus for the webclient.

        Conditional-fetch contract (mirrors ``/web/webclient/translations``):
        every 200 response carries an ``X-Menus-Hash`` header (SHA-256 of the
        JSON body). The client persists it next to its localStorage copy of
        the menus and sends it back as the ``hash`` query parameter on the
        next boot; when it still matches, an empty ``304 Not Modified``
        response is returned instead of the full payload (which includes the
        base64 app icons), so warm boots only transfer headers.

        ``Cache-Control: no-store`` is kept on purpose: the payload depends
        on session state (user access rights, debug mode), so it must never
        be stored by the browser HTTP cache or intermediaries — the explicit
        hash round-trip replaces HTTP caching.

        :param lang: language in which the menus should be loaded (only works if language is installed)
        :param hash: hash of the menus payload currently cached by the client
        :return: the menus (including the images in Base64), or an empty 304
            response when ``hash`` matches the current payload
        """
        if lang:
            request.update_context(lang=lang)

        menus = request.env["ir.ui.menu"].load_web_menus(request.session.debug)
        # Serialize with the same helper as make_json_response() so the
        # hashed bytes are exactly the bytes sent on the wire.
        body = json_dumps(menus, default=orjson_default)
        current_hash = hashlib.sha256(body.encode()).hexdigest()
        headers = [
            ("Cache-Control", "no-store"),
            ("X-Menus-Hash", current_hash),
        ]
        if hash and hash == current_hash:
            return request.make_response("", headers, status=304)
        headers.append(("Content-Type", "application/json; charset=utf-8"))
        return request.make_response(body, headers)

    def _login_redirect(self, uid: int, redirect: str | None = None) -> str:
        return _get_login_redirect_url(uid, redirect)

    @http.route(
        "/web/login",
        type="http",
        auth="none",
        readonly=False,
        list_as_website_content=_lt("Login"),
    )
    def web_login(self, redirect: str | None = None, **kw: Any) -> Response:
        ensure_db()
        request.params["login_success"] = False
        if request.httprequest.method == "GET" and redirect and request.session.uid:
            if not _is_local_url(redirect):
                redirect = "/odoo"
            return request.redirect(redirect)

        # simulate hybrid auth=user/auth=public, despite using auth=none to be able
        # to redirect users when no db is selected - cfr ensure_db()
        if request.env.uid is None:
            if request.session.uid is None:
                # no user -> auth=public with specific website public user
                request.env["ir.http"]._auth_method_public()
            else:
                # behave as authenticated user
                request.update_env(user=request.session.uid)

        values = {
            k: v for k, v in request.params.items() if k in SIGN_UP_REQUEST_PARAMS
        }
        try:
            values["databases"] = http.db_list()
        except odoo.exceptions.AccessDenied:
            values["databases"] = None

        if request.httprequest.method == "POST":
            try:
                credential = {
                    key: value
                    for key, value in request.params.items()
                    if key in CREDENTIAL_PARAMS and value
                }
                credential.setdefault("type", "password")
                if request.env["res.users"]._should_captcha_login(credential):
                    request.env["ir.http"]._verify_request_recaptcha_token("login")
                auth_info = request.session.authenticate(request.env, credential)
                request.params["login_success"] = True
                return request.redirect(
                    self._login_redirect(auth_info["uid"], redirect=redirect)
                )
            except odoo.exceptions.AccessDenied as e:
                if e.args == odoo.exceptions.AccessDenied().args:
                    values["error"] = _("Wrong login/password")
                else:
                    values["error"] = e.args[0]
        elif "error" in request.params and request.params.get("error") == "access":
            values["error"] = _(
                "Only employees can access this database. Please contact the administrator."
            )

        if "login" not in values and request.session.get("auth_login"):
            values["login"] = request.session.get("auth_login")

        if not odoo.tools.config["list_db"]:
            values["disable_database_manager"] = True

        response = request.render("web.login", values)
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        return response

    @http.route(
        "/web/login_successful",
        type="http",
        auth="user",
        website=True,
        sitemap=False,
    )
    def login_successful_external_user(self, **kwargs: Any) -> Response:
        """Landing page shown after a successful login to non-internal (external) users."""
        valid_values = {k: v for k, v in kwargs.items() if k in LOGIN_SUCCESSFUL_PARAMS}
        return request.render("web.login_successful", valid_values)

    # readonly=False: this route mutates — it clears the registry cache (queued
    # to the DB signaling sequence at commit) and rewrites the session token.
    # Declaring it readonly routed it to a read replica, forcing the
    # dispatcher's RO→RW retry (or failing on a strict replica) for a route
    # that is inherently a write.
    @http.route("/web/become", type="http", auth="user", sitemap=False, readonly=False)
    def switch_to_admin(self) -> Response:
        uid = request.env.user.id
        if request.env.user._is_system():
            uid = request.session.uid = odoo.SUPERUSER_ID
            # invalidate session token cache as we've changed the uid
            request.env.registry.clear_cache()
            request.session.session_token = security.compute_session_token(
                request.session, request.env
            )

        return request.redirect(self._login_redirect(uid))

    @http.route("/web/health", type="http", auth="none", save_session=False)
    def health(self, db_server_status: bool | str = False) -> Response:
        """Combined health endpoint, kept for backward compatibility.

        New deployments should target ``/web/healthz`` for liveness and
        ``/web/readyz`` for readiness — those follow Kubernetes/Nomad
        probe conventions and return 503 (not 500) when not ready.
        """
        health_info = {"status": "pass"}
        status = 200
        if str2bool(db_server_status, False):
            try:
                with odoo.db.db_connect("postgres").cursor():
                    pass
                health_info["db_server_status"] = True
            except psycopg.Error:
                health_info["db_server_status"] = False
                health_info["status"] = "fail"
                status = 500
        return self._health_response(health_info, status)

    @http.route("/web/healthz", type="http", auth="none", save_session=False)
    def healthz(self) -> Response:
        """Liveness probe — 200 iff the worker process can answer requests.

        Performs no I/O (no DB connection, no filestore read).  A failing
        ``healthz`` indicates the process should be restarted; orchestrators
        such as Kubernetes and Nomad consume this on the liveness probe.
        """
        return self._health_response({"status": "pass"}, 200)

    @http.route("/web/readyz", type="http", auth="none", save_session=False)
    def readyz(self) -> Response:
        """Readiness probe — 200 iff every subsystem can serve traffic.

        Checks PostgreSQL reachability (``postgres`` system DB cursor) and
        ``data_dir`` writability.  Returns 503 with a per-subsystem
        ``checks`` map otherwise — a failing ``readyz`` removes the
        worker from the load balancer without restarting it.
        """
        checks: dict[str, str] = {}
        status = 200
        try:
            with odoo.db.db_connect("postgres").cursor():
                pass
            checks["db"] = "pass"
        except psycopg.Error:
            checks["db"] = "fail"
            status = 503
        if os.access(config["data_dir"], os.W_OK):
            checks["data_dir"] = "pass"
        else:
            checks["data_dir"] = "fail"
            status = 503
        return self._health_response(
            {"status": "pass" if status == 200 else "fail", "checks": checks},
            status,
        )

    def _health_response(self, payload: dict[str, Any], status: int) -> Response:
        """Build a JSON health-check response with no-store headers."""
        return request.make_response(
            json_dumps(payload),
            [
                ("Content-Type", "application/json"),
                ("Cache-Control", "no-store"),
            ],
            status=status,
        )

    @http.route(["/robots.txt"], type="http", auth="none")
    def robots(self, **kwargs: Any) -> Response:
        allowed_routes = self._get_allowed_robots_routes()
        robots_content = ["User-agent: *", "Disallow: /"]
        robots_content.extend(f"Allow: {route}" for route in allowed_routes)

        return request.make_response(
            "\n".join(robots_content), [("Content-Type", "text/plain")]
        )

    def _get_allowed_robots_routes(self) -> list[str]:
        """Override this method to return a list of allowed routes.

        :return: A list of URL paths that should be allowed by robots.txt
              Examples: ['/social_instagram/', '/sitemap.xml', '/web/']
        """
        return []
