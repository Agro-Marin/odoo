from typing import Self

from odoo import api, fields, models
from odoo.api import ValuesType


class ResUsers(models.Model):
    _inherit = "res.users"

    followed_project_ids = fields.Many2many(
        "project.project",
        string="Followed Projects",
        store=False,
        search="_search_followed_project_ids",
        export_string_translation=False,
    )

    def _search_followed_project_ids(self, operator, value) -> list:
        followers = self.env["mail.followers"].search(
            [("res_model", "=", "project.project"), ("res_id", operator, value)]
        )
        return [("partner_id", "in", followers.partner_id.ids)]

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        res = super().create(vals_list)
        self._onboard_users_into_project(res)
        return res

    def _onboard_users_into_project(self, users: Self) -> Self | None:
        if internal_users := users.filtered(lambda u: not u.share):
            TriageSudo = self.env["project.triage"].sudo()
            create_vals = []
            for user in internal_users:
                vals = (
                    self.env["project.task"]
                    .with_context(lang=user.lang)
                    ._get_default_triage_vals(user.id)
                )
                create_vals.extend(vals)

            if create_vals:
                TriageSudo.with_context(default_project_id=False).create(create_vals)

            return internal_users
        return None
