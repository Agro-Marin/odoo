from odoo import fields, models


class WebsiteEventMenu(models.Model):
    _inherit = "website.event.menu"

    menu_type = fields.Selection(
        selection_add=[
            ("track", "Event Tracks Menus"),
            ("track_proposal", "Event Proposals Menus"),
        ],
        ondelete={"track": "cascade", "track_proposal": "cascade"},
    )
