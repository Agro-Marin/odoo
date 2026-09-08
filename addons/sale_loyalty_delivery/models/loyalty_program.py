from odoo import _, api, models


class LoyaltyProgram(models.Model):
    _inherit = "loyalty.program"

    @api.model
    def _program_type_default_values(self):
        res = super()._program_type_default_values()
        # Add a loyalty reward for free shipping, ordered (by loyalty.reward's
        # `required_points asc` _order) after the other template rewards, so a
        # DB-fresh read of reward_ids never surfaces it ahead of e.g. the base
        # discount reward.
        if "loyalty" in res:
            highest_points = max(
                (
                    vals.get("required_points", 0)
                    for command, _id, vals in res["loyalty"]["reward_ids"]
                    if command == 0
                ),
                default=0,
            )
            res["loyalty"]["reward_ids"].append(
                (
                    0,
                    0,
                    {
                        "reward_type": "shipping",
                        "required_points": highest_points + 1,
                    },
                )
            )
        return res

    @api.model
    def get_program_templates(self):
        # Override 'promotion' template to say free shipping
        res = super().get_program_templates()
        if "promotion" in res:
            res["promotion"]["description"] = _(
                "Automatic promotion: free shipping on orders higher than $50"
            )
        return res

    @api.model
    def _get_template_values(self):
        res = super()._get_template_values()
        if "promotion" in res:
            res["promotion"]["reward_ids"] = [
                (5, 0, 0),
                (
                    0,
                    0,
                    {
                        "reward_type": "shipping",
                    },
                ),
            ]
        return res
