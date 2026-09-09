from odoo import _, fields, models
from odoo.exceptions import UserError


class DocumentsDocument(models.Model):
    _inherit = "document.document"

    is_gelato = fields.Boolean(readonly=True)

    def _gelato_prepare_file_payload(self):
        if not self.datas:
            raise UserError(
                _("Print images must be set on products before they can be ordered.")
            )

        query_string = f"access_token={self.attachment_id.generate_access_token()[0]}"
        url = f"{self.get_base_url()}{self.attachment_id.image_src}?{query_string}"
        return {
            "type": self.name.lower(),
            "url": url,
        }
