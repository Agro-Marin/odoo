from odoo import models


class GamificationKarmaTracking(models.Model):
    _inherit = "gamification.karma.tracking"

    def _selection_origin_models(self):
        return super()._selection_origin_models() + [
            ("forum.post", self.env["ir.model"]._get("forum.post").display_name)
        ]
