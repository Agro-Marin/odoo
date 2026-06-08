from odoo import http
from odoo.http import request

from odoo.addons.web.controllers.home import Home as WebHome
from odoo.addons.web.controllers.utils import is_user_internal


class Home(WebHome):
    """Portal override: keep portal/external users in /my, never expose the backend.

    Internal users keep the upstream behaviour; everyone else (share users, portal
    users, anonymous-with-session) gets redirected to /my on the three routes that
    would otherwise land them on the backend client.
    """

    def _redirect_external_to_my(self):
        """Return a /my redirect when the current session is non-internal, else None."""
        if request.session.uid and not is_user_internal(request.session.uid):
            return request.redirect_query("/my", query=request.params)
        return None

    @http.route()
    def index(self, *args, **kw):
        if redirect := self._redirect_external_to_my():
            return redirect
        return super().index(*args, **kw)

    def _login_redirect(self, uid, redirect=None):
        """Send non-internal users to /my after login when no explicit redirect was requested."""
        if not redirect and not is_user_internal(uid):
            redirect = "/my"
        return super()._login_redirect(uid, redirect=redirect)

    @http.route()
    def web_client(self, s_action=None, **kw):
        if redirect := self._redirect_external_to_my():
            return redirect
        return super().web_client(s_action, **kw)
