from odoo import fields, models


class DocumentType(models.Model):
    _inherit = "document.type"

    product_categ_ids = fields.Many2many(
        comodel_name="product.category",
        relation="document_type_product_category_rel",
        column1="type_id",
        column2="categ_id",
        string="Product Categories",
        help="Product categories this document type is required of, subcategories "
        "included. Leave empty to require it of every product: a sanitary "
        "registration applies to pesticides, not to packaging.",
    )
