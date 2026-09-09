from odoo import models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _can_bypass_rights_on_media_dialog(self, **attachment_data):
        forbidden = (
            "url" in attachment_data
            and attachment_data.get("type", "binary") == "binary"
        )
        if forbidden and attachment_data["url"].startswith("/unsplash/"):
            return True
        return super()._can_bypass_rights_on_media_dialog(**attachment_data)
