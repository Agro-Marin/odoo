import time
from typing import Any

from odoo import _, fields, models
from odoo.exceptions import AccessDenied, UserError
from odoo.http import request
from odoo.libs.json import loads as json_loads


class ResUsersIdentitycheck(models.TransientModel):
    """Wizard that re-checks the user's password before running a security-sensitive (``check_identity``) action."""

    _name = "res.users.identitycheck"
    _description = "Password Check Wizard"

    request = fields.Char(readonly=True, groups=fields.NO_ACCESS)
    auth_method = fields.Selection(
        [("password", "Password")],
        default=lambda self: self._get_default_auth_method(),
    )
    password = fields.Char(store=False)

    def _get_default_auth_method(self) -> str:
        return "password"

    def _check_identity(self) -> None:
        try:
            credential = {
                "login": self.env.user.login,
                "password": self.env.context.get("password"),
                "type": "password",
            }
            self.env.user._check_credentials(credential, {"interactive": True})
        except AccessDenied:
            raise UserError(
                _(
                    "Incorrect Password, try again or click on Forgot Password to reset your password."
                )
            ) from None

    def run_check(self) -> Any:
        """Run the deferred method after re-verifying the user's password.

        Requires an HTTP request and only runs methods flagged by the
        ``check_identity`` decorator.

        :return: the deferred method's return value (typically an
            ``ir.actions.*`` dict).
        """
        if not request:
            raise UserError(_("This method can only be accessed over HTTP."))
        self._check_identity()

        # RIC-L1 (audit 2026-05-28, S3 latent, inherited design): `identity-check-last`
        # is stamped before the allow-list check below and is session-global, so any
        # passing check opens a prompt-free 10-minute window for every @check_identity
        # method (even a rejected call refreshes it). This is the upstream decorator's
        # intended coarse "sudo window"; fixing it needs a decorator-level redesign.
        request.session["identity-check-last"] = time.time()
        ctx, model, ids, method_name, args, kwargs = json_loads(self.sudo().request)
        method = getattr(self.env(context=ctx)[model].browse(ids), method_name)
        if not getattr(method, "__has_check_identity", False):
            raise UserError(
                _("This method is not allowed for identity-checked execution.")
            )
        return method(*args, **kwargs)
