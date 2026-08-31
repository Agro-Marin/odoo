from odoo import api, fields, models


class CrmMergeOpportunity(models.TransientModel):
    _name = "crm.merge.opportunity"
    _description = "Merge Opportunities"

    @api.model
    def default_get(self, fields):
        record_ids = self.env.context.get("active_ids")
        result = super().default_get(fields)

        if record_ids:
            if "opportunity_ids" in fields:
                opp_ids = (
                    self.env["crm.lead"]
                    .browse(record_ids)
                    .filtered(lambda opp: opp.won_status != "won")
                    .ids
                )
                result["opportunity_ids"] = [(6, 0, opp_ids)]

        return result

    opportunity_ids = fields.Many2many(
        "crm.lead",
        "merge_opportunity_rel",
        "merge_id",
        "opportunity_id",
        string="Leads/Opportunities",
        context={"active_test": False},
    )
    user_id = fields.Many2one(
        "res.users", "Salesperson", domain="[('share', '=', False)]"
    )
    team_id = fields.Many2one(
        "crm.team", "Sales Team", compute="_compute_team_id", readonly=False, store=True
    )

    def action_merge(self):
        self.check_singleton()
        merge_opportunity = self.opportunity_ids.merge_opportunity(
            self.user_id.id, self.team_id.id
        )
        return merge_opportunity.redirect_lead_opportunity_view()

    @api.depends("user_id")
    def _compute_team_id(self):
        Team = self.env["crm.team"]
        for wizard in self:
            if wizard.user_id:
                wizard.team_id = Team._get_team_for_user(wizard.user_id, wizard.team_id)
