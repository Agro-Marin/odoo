from odoo import models


class GamificationBadge(models.Model):
    _name = "gamification.badge"
    _inherit = ["gamification.badge", "mixin.website.published"]
