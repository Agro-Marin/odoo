import time
from typing import Any

from odoo import _, fields, models
from odoo.exceptions import AccessDenied, UserError
from odoo.http import request
from odoo.libs.json import loads as json_loads


class ResUsersIdentitycheck(models.TransientModel):
    """Wizard used to re-check the user's credentials (password) and eventually
    revoke access to his account to every device he has an active session on.

    Might be useful before the more security-sensitive operations, users might be
    leaving their computer unlocked & unattended. Re-checking credentials mitigates
    some of the risk of a third party using such an unattended device to manipulate
    the account.
    """

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
        """Execute the deferred method after re-verifying the user's identity.

        Safe as a button target: requires an HTTP request, re-checks the
        password against the current user, and runs only methods flagged by the
        ``check_identity`` decorator (see ``res_users.check_identity``).

        :return: the deferred action method's return value (typically an
            ``ir.actions.*`` dict).
        :rtype: typing.Any
        """
        if not request:
            raise UserError(_("This method can only be accessed over HTTP."))
        self._check_identity()

        # RIC-L1 (audit 2026-05-28, S3 latent, inherited design — no local fix):
        # `identity-check-last` is stamped here, *before* the allow-list check
        # below, and is session-global / method-agnostic. Once any identity check
        # passes, every @check_identity method runs prompt-free for the decorator's
        # 10-minute window, and even a rejected (disallowed-method) call refreshes
        # that clock. This is the intended coarse "sudo window" of the upstream
        # check_identity decorator, not a defect introduced here; changing it
        # requires a coordinated decorator-level redesign (per-action token binding).
        request.session["identity-check-last"] = time.time()
        ctx, model, ids, method_name, args, kwargs = json_loads(self.sudo().request)
        method = getattr(self.env(context=ctx)[model].browse(ids), method_name)
        if not getattr(method, "__has_check_identity", False):
            raise UserError(
                _("This method is not allowed for identity-checked execution.")
            )
        return method(*args, **kwargs)
