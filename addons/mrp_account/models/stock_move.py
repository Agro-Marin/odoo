from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _get_value_from_production(self, quantity, at_date=None):
        # TODO: Maybe move _cal_price here
        self.ensure_one()
        if not self.production_id:
            return super()._get_value_from_production(quantity, at_date)
        value = quantity * self.price_unit
        return {
            "value": value,
            "quantity": quantity,
            "description": self.env._(
                "%(value)s for %(quantity)s %(unit)s from %(production)s",
                value=self.company_currency_id.format(value),
                quantity=quantity,
                unit=self.product_id.uom_id.name,
                production=self.production_id.display_name,
            ),
        }

    def _get_kit_price_unit(self, product, kit_bom, valuated_quantity):
        """Unit cost of one `product`, valued from the components of its kit BoM.

        `valuated_quantity` says whether there is anything to value at all; the
        price itself is per unit and does not otherwise depend on it.
        """
        if product.uom_id.is_zero(valuated_quantity):
            return 0
        component_qty, kit_qty = kit_bom._get_kit_component_qty(product)
        if product.uom_id.is_zero(kit_qty):
            return 0
        total_price = sum(
            super(StockMove, valuated_moves)._get_price_unit()
            * component_qty[component]
            for component, valuated_moves in self.grouped("product_id").items()
        )
        return total_price / kit_qty
