from odoo import models


class StockReturnPicking(models.TransientModel):
    _inherit = "stock.return.picking"

    def _create_return(self):
        new_picking = super()._create_return()
        self._reset_carrier_id(new_picking)
        return new_picking

    def _reset_carrier_id(self, picking):
        picking.write(
            {
                "carrier_id": False,
                "carrier_price": 0.0,
            }
        )
