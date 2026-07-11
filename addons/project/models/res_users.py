"""User onboarding for project triage buckets."""

from typing import Self

from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    favorite_project_ids = fields.Many2many(
        "project.project",
        "project_favorite_user_rel",
        "user_id",
        "project_id",
        string="Favorite Projects",
        export_string_translation=False,
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list: list[dict]) -> Self:
        res = super().create(vals_list)
        self._onboard_users_into_project(res)
        return res

    def _onboard_users_into_project(self, users: Self) -> Self | None:
        """Create default triage buckets for new internal users."""
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
