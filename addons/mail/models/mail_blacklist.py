from typing import Literal, Self

from odoo import _, api, fields, models, tools
from odoo.api import DomainType, ValuesType
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import Query


class MailBlacklist(models.Model):
    _name = "mail.blacklist"
    _inherit = ["mixin.mail.thread"]
    _description = "Mail Blacklist"
    _rec_name = "email"

    email = fields.Char(
        string="Email Address",
        required=True,
        index="trigram",
        help="This field is case insensitive.",
        tracking=1,
    )
    active = fields.Boolean(default=True, tracking=2)

    _unique_email = models.Constraint(
        "unique (email)",
        "Email address already exists!",
    )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        new_values = []
        all_emails = []
        for value in vals_list:
            email = tools.email_normalize(value.get("email"))
            if not email:
                raise UserError(_("Invalid email address “%s”", value["email"]))
            if email in all_emails:
                continue
            all_emails.append(email)
            new_value = dict(value, email=email)
            new_values.append(new_value)

        to_create = []
        bl_entries = {}
        if new_values:
            sql = """SELECT email, id FROM mail_blacklist WHERE email = ANY(%s)"""
            emails = [v["email"] for v in new_values]
            self.env.cr.execute(sql, (emails,))
            bl_entries = dict(self.env.cr.fetchall())
            to_create = [v for v in new_values if v["email"] not in bl_entries]

        results = super().create(to_create)
        return self.env["mail.blacklist"].browse(bl_entries.values()) | results

    def write(self, vals: ValuesType) -> Literal[True]:
        if "email" in vals:
            normalized = tools.email_normalize(vals["email"])
            if not normalized:
                raise UserError(_("Invalid email address “%s”", vals["email"]))
            vals["email"] = normalized
        return super().write(vals)

    def _search(self, domain: DomainType, *args, **kwargs) -> Query:
        domain = Domain(domain).map_conditions(
            lambda cond: (
                Domain(cond.field_expr, cond.operator, norm_value)
                if cond.field_expr == "email"
                and isinstance(cond.value, str)
                and (norm_value := tools.email_normalize(cond.value))
                else cond
            )
        )
        return super()._search(domain, *args, **kwargs)

    def _add(self, email: str, message: str | None = None) -> Self:
        normalized = tools.email_normalize(email)
        record = (
            self.env["mail.blacklist"]
            .with_context(active_test=False)
            .search([("email", "=", normalized)])
        )
        if len(record) > 0:
            if message:
                record._track_set_log_message(message)
            record.action_unarchive()
        else:
            record = self.create({"email": email})
            if message:
                record.with_context(mail_post_autofollow_author_skip=True).message_post(
                    body=message,
                    subtype_xmlid="mail.mt_note",
                )
        return record

    def _remove(self, email: str, message: str | None = None) -> Self:
        normalized = tools.email_normalize(email)
        record = (
            self.env["mail.blacklist"]
            .with_context(active_test=False)
            .search([("email", "=", normalized)])
        )
        if len(record) > 0:
            if message:
                record._track_set_log_message(message)
            record.action_archive()
        else:
            record = record.create({"email": email, "active": False})
            if message:
                record.with_context(mail_post_autofollow_author_skip=True).message_post(
                    body=message,
                    subtype_xmlid="mail.mt_note",
                )
        return record

    def mail_action_blacklist_remove(self) -> dict:
        return {
            "name": _("Are you sure you want to unblacklist this email address?"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "mail.blacklist.remove",
            "target": "new",
            "context": {"dialog_size": "medium"},
        }

    def action_add(self) -> None:
        self._add(self.email)
