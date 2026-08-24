from odoo import models


class EventTagCategory(models.Model):
    _name = "event.tag.category"
    _inherit = ["event.tag.category", "mixin.website.published.multi"]

    def _default_is_published(self):
        return True
