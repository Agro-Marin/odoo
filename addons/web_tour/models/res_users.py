from odoo import api, fields, models, modules


class ResUsers(models.Model):
    """Extend users with tour/onboarding preference."""

    _inherit = "res.users"

    tour_enabled = fields.Boolean(
        compute="_compute_tour_enabled", store=True, readonly=False, string="Onboarding"
    )

    @api.depends("create_date")
    def _compute_tour_enabled(self):
        """Enable onboarding for admin users when no demo data is installed."""
        has_demo = bool(
            self.env["ir.module.module"].sudo().search_count([("demo", "=", True)])
        )
        for user in self:
            user.tour_enabled = (
                user._is_admin() and not has_demo and not modules.module.current_test
            )

    @api.model
    def switch_tour_enabled(self, val):
        """Toggle the current user's onboarding preference and return the new state."""
        self.env.user.sudo().tour_enabled = val
        return self.env.user.tour_enabled
