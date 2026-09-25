from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    barcodes_config_id = fields.Many2one(
        comodel_name="barcodes.config",
        compute="_compute_barcodes_config_id",
        search="_search_barcodes_config_id",
    )

    nomenclature_id = fields.Many2one(
        related="barcodes_config_id.nomenclature_id",
    )

    def _search_barcodes_config_id(self, operator, value):
        return self._search_config_link("barcodes.config", operator, value)

    def _compute_barcodes_config_id(self):
        self._compute_config_link("barcodes_config_id")
