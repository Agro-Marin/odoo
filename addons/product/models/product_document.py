from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductDocument(models.Model):
    _name = "product.document"
    _description = "Product Document"
    _inherits = {
        "ir.attachment": "ir_attachment_id",
    }
    _order = "sequence, name"

    ir_attachment_id = fields.Many2one(
        comodel_name="ir.attachment",
        string="Related attachment",
        required=True,
        ondelete="cascade",
    )

    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    @api.onchange("url")
    def _onchange_url(self):
        # Early UX feedback in the form; the real guarantee is the constraint.
        self._check_url_scheme()

    @api.constrains("url", "type")
    def _check_url_scheme(self):
        """Reject non-web URL schemes (javascript:, file:, ...).

        Documents of type ``url`` are surfaced as clickable links, potentially
        to portal users (e.g. on quotations), so the scheme must be enforced on
        every write path — not only in the form onchange.
        """
        for document in self:
            if (
                document.type == "url"
                and document.url
                and not document.url.startswith(("https://", "http://", "ftp://"))
            ):
                raise ValidationError(
                    _(
                        "Please enter a valid URL.\nExample: https://www.odoo.com\n\nInvalid URL: %s",
                        document.url,
                    )
                )

    # === CRUD METHODS ===#

    @api.model_create_multi
    def create(self, vals_list):
        documents = super(
            ProductDocument,
            self.with_context(disable_product_documents_creation=True),
        ).create(vals_list)
        # Delegated (`_inherits`) fields are written on the parent attachment
        # before this model's constraint validation runs, so the url check must
        # be called explicitly on create.
        documents._check_url_scheme()
        return documents

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
