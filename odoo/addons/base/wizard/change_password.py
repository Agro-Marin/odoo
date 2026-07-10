from typing import Any

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command

from ..models.res_users import check_identity


class ChangePasswordWizard(models.TransientModel):
    """A wizard to manage the change of users' passwords."""

    _name = "change.password.wizard"
    _description = "Change Password Wizard"
    _transient_max_hours = 0.2

    def _default_user_ids(self) -> list[tuple[int, int, dict[str, Any]]]:
        user_ids = (
            self.env.context.get("active_model") == "res.users"
            and self.env.context.get("active_ids")
        ) or []
        return [
            Command.create({"user_id": user.id, "user_login": user.login})
            for user in self.env["res.users"].browse(user_ids)
        ]

    user_ids = fields.One2many(
        "change.password.user",
        "wizard_id",
        string="Users",
        default=_default_user_ids,
    )

    def change_password_button(self) -> dict[str, str]:
        """Apply the new password to every wizard line and close the wizard.

        :return: a client reload action if the acting user changed their own
            password, otherwise a window-close action.
        """
        self.ensure_one()
        self.user_ids.change_password_button()
        if self.env.user in self.user_ids.user_id:
            return {"type": "ir.actions.client", "tag": "reload"}
        return {"type": "ir.actions.act_window_close"}


class ChangePasswordUser(models.TransientModel):
    """A model to configure users in the change password wizard."""

    _name = "change.password.user"
    _description = "User, Change Password Wizard"
    wizard_id = fields.Many2one(
        "change.password.wizard",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )
    user_id = fields.Many2one(
        "res.users", string="User", required=True, ondelete="cascade"
    )
    user_login = fields.Char(string="User Login", readonly=True)
    new_passwd = fields.Char(string="New Password", default="")

    def change_password_button(self) -> None:
        """Write each line's new password onto its target user.

        Cross-user password setting is blocked upstream by three independent
        layers (do not weaken any): the ``change.password.user`` ACL is limited to
        ``base.group_erp_manager``; the ``change_password_rule`` record rule scopes
        lines to ``[('create_uid', '=', user.id)]``; and ``_change_password``'s
        ``res.users`` write needs real ORM rights (``password`` is not in
        ``SELF_WRITEABLE_FIELDS``).
        """
        for line in self:
            if line.new_passwd:
                line.user_id._change_password(line.new_passwd)
        # don't keep temporary passwords in the database longer than necessary
        self.write({"new_passwd": False})


class ChangePasswordOwn(models.TransientModel):
    """A wizard letting a user change only their own password.

    Unlike ``change.password.user`` this model has no ``user_id`` field: it is
    hard-bound to ``self.env.user`` and additionally protected by
    ``@check_identity``, so it can never target another user's record.
    """

    _name = "change.password.own"
    _description = "User, change own password wizard"
    _transient_max_hours = 0.1

    new_password = fields.Char(string="New Password")
    confirm_password = fields.Char(string="New Password (Confirmation)")

    @api.constrains("new_password", "confirm_password")
    def _check_password_confirmation(self) -> None:
        for record in self:
            if record.confirm_password != record.new_password:
                raise ValidationError(
                    _("The new password and its confirmation must be identical.")
                )

    @check_identity
    def change_password(self) -> dict[str, str]:
        self.env.user._change_password(self.new_password or "")
        self.unlink()
        # reload to avoid a session expired error
        return {"type": "ir.actions.client", "tag": "reload"}
