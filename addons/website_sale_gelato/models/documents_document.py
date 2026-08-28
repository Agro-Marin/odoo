from odoo import _, api, models
from odoo.exceptions import ValidationError


class DocumentsDocument(models.Model):
    _inherit = "documents.document"

    # === CONSTRAINT METHODS === #

    @api.constrains("datas")
    def _check_product_is_unpublished_before_removing_print_images(self):
        for print_image in self.filtered(lambda i: i.is_gelato):
            template = self.env["product.template"].browse(print_image.res_id)
            if template.is_published and not print_image.datas:
                raise ValidationError(
                    _(
                        "Products must be unpublished before print images can be removed."
                    )
                )
