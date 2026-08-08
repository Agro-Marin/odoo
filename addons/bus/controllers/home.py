import ipaddress

from odoo import SUPERUSER_ID, _
from odoo.http import request

from odoo.addons.web.controllers.home import Home as WebHome


def _is_private_address(remote_addr):
    """Whether ``remote_addr`` is on a private network.

    ``remote_addr`` is ``str | None``, and under ``proxy_mode`` it is whatever
    the proxy put in ``X-Forwarded-For`` -- which may be absent, or a non-address
    such as the ``unknown`` nodename RFC 7239 explicitly permits and real proxies
    do emit. Letting ``ValueError`` escape turned a login that had already
    *succeeded* into a 500: verified end to end, the same request answering 303
    with a routable address answered 500 with ``X-Forwarded-For: unknown``, the
    session authenticated and the user handed an error page.

    An address we cannot parse is not evidence of a private network, so treat it
    as public: that errs towards showing the default-password warning, which is
    the safe direction for a warning about being exposed.
    """
    try:
        return ipaddress.ip_address(remote_addr).is_private
    except ValueError:
        return False


def _admin_password_warn(uid):
    if request.params.get("password") != "admin":
        return
    if _is_private_address(request.httprequest.remote_addr):
        return
    env = request.env(user=SUPERUSER_ID, su=True)
    admin = env.ref("base.partner_admin")
    if uid not in admin.user_ids.ids:
        return
    has_demo = bool(env["ir.module.module"].search_count([("demo", "=", True)]))
    if has_demo:
        return
    admin.with_context(request.env(user=uid)["res.users"].context_get())._bus_send(
        "simple_notification",
        {
            "type": "danger",
            "message": _(
                "Your password is the default (admin)! If this system is exposed to untrusted users it is important to change it immediately for security reasons. I will keep nagging you about it!"
            ),
            "sticky": True,
        },
    )


class Home(WebHome):
    def _login_redirect(self, uid, redirect=None):
        if request.params.get("login_success"):
            _admin_password_warn(uid)
        return super()._login_redirect(uid, redirect)
