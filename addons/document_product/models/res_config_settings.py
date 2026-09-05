from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    documents_product_settings = fields.Boolean(
        related='company_id.documents_product_settings',
        readonly=False, string="Product")
    product_folder_id = fields.Many2one(
        'document.document', related='company_id.product_folder_id',
        readonly=False, string="product default folder")
    product_tag_ids = fields.Many2many(
        'document.tag', related='company_id.product_tag_ids',
        readonly=False, string="Product Tags")
