from odoo import models
from odoo.exceptions import UserError


class MixinOrderDocumentImport(models.AbstractModel):
    _name = "mixin.order.document.import"
    _inherit = ["mixin.account.document.import"]
    _description = "Order Creation From Uploaded Documents"

    def create_document_from_attachment(self, attachment_ids):
        attachments = self.env["ir.attachment"].browse(attachment_ids)
        if not attachments:
            raise UserError(self.env._("No attachment was provided."))

        orders = self.with_context(
            default_partner_id=self.env.user.partner_id.id,
        )._create_records_from_attachments(attachments)
        return orders._get_records_action(name=self.env._("Generated Orders"))
