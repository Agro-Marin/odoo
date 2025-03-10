from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class ProductDocument(models.Model):
    _name = "product.document"
    _inherits = {
        "ir.attachment": "ir_attachment_id",
    }
    _description = "Product Document"
    _order = "sequence, name"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    ir_attachment_id = fields.Many2one(
        comodel_name="ir.attachment",
        string="Related attachment",
        required=True,
        ondelete="cascade",
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        return super(
            ProductDocument,
            self.with_context(disable_product_documents_creation=True),
        ).create(vals_list)

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        ir_default = default
        if ir_default:
            ir_fields = list(self.env["ir.attachment"]._fields)
            ir_default = {
                field: default[field] for field in default if field in ir_fields
            }
        for document, vals in zip(self, vals_list):
            vals["ir_attachment_id"] = (
                document.ir_attachment_id.with_context(
                    no_document=True,
                    disable_product_documents_creation=True,
                )
                .copy(ir_default)
                .id
            )
        return vals_list

    def unlink(self):
        attachments = self.ir_attachment_id
        res = super().unlink()
        return res and attachments.unlink()

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    @api.onchange("url")
    def _onchange_url(self):
        for attachment in self:
            if (
                attachment.type == "url"
                and attachment.url
                and not attachment.url.startswith(("https://", "http://", "ftp://"))
            ):
                raise ValidationError(
                    _(
                        "Please enter a valid URL.\nExample: https://www.odoo.com\n\nInvalid URL: %s",
                        attachment.url,
                    )
                )
