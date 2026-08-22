from odoo import models


class IrBinary(models.AbstractModel):
    _inherit = "ir.binary"

    def _get_record(
        self,
        xmlid=None,
        res_model="ir.attachment",
        res_id=None,
        access_token=None,
        field_name=None,
    ):
        record = None
        if xmlid:
            website = self.env["website"].get_current_website()
            if website.theme_id:
                domain = [("key", "=", xmlid), ("website_id", "=", website.id)]
                Attachment = self.env["ir.attachment"]
                if self.env.user.share:
                    domain.append(("public", "=", True))
                    Attachment = Attachment.sudo()
                record = Attachment.search(domain, limit=1)

        if not record:
            record = super()._get_record(
                xmlid, res_model, res_id, access_token, field_name=field_name
            )

        return record
