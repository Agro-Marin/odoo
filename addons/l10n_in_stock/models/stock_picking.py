from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _is_commercial_invoice_required(self):
        super()._is_commercial_invoice_required()
        return True

    def _get_l10n_in_dropship_dest_partner(self):
        """
        To be overriden by `l10n_in_purchase_stock` will be ideal to use it for `l10n_in_ewaybill_stock`
        returns destination partner from purchase_id
        """
        pass

    def _l10n_in_get_invoice_partner(self):
        """
        To be overriden by `l10n_in_sale_stock` will be ideal to use it for `l10n_in_ewaybill_stock`
        returns invoice partner from sale_id
        """
        pass

    def _l10n_in_get_fiscal_position(self):
        """
        To be inherited by `l10n_in_*_stock` will be ideal to use it for `l10n_in_ewaybill_stock`
        returns fiscal position from order
        """
        pass
