from odoo import models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _post_add_create(self, **kwargs):
        super()._post_add_create(**kwargs)
        if self.res_model == "mrp.bom":
            bom = self.env["mrp.bom"].browse(self.res_id)
            # Re-targeting the attachment at the product is what makes
            # `documents` create the document for it, so only the MRP flag is
            # left to set. Creating one here unconditionally would be a second
            # document on the same attachment and hit `_attachment_unique`.
            self.res_model = (
                bom.product_id._name if bom.product_id else bom.product_tmpl_id._name
            )
            self.res_id = (
                bom.product_id.id if bom.product_id else bom.product_tmpl_id.id
            )
            document = self.env["documents.document"].search(
                [("attachment_id", "=", self.id)]
            )
            if document:
                document.attached_on_mrp = "bom"
            else:
                self.env["documents.document"].create(
                    {"attachment_id": self.id, "attached_on_mrp": "bom"}
                )
