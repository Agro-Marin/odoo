from odoo import models
from odoo.http import request

# The routes our own links carry a signup token to. Any other URL could plant
# someone else's token in a visitor's session for the next signup to consume.
SIGNUP_TOKEN_ROUTES = frozenset({"/web/signup", "/web/reset_password", "/mail/view"})


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _pre_dispatch(cls, rule, args):
        super()._pre_dispatch(rule, args)

        args_in = request.httprequest.args
        if (login := args_in.get("auth_login")) is not None:
            request.session["auth_login"] = login
        token = args_in.get("auth_signup_token")
        if token is not None and rule.rule in SIGNUP_TOKEN_ROUTES:
            request.session["auth_signup_token"] = token
