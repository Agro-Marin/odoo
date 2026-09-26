from odoo import models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _get_agreement_line(self):
        self.check_singleton()
        matched = self.env["sale.agreement.line"]
        for agreement_line in self.order_id.agreement_id.line_ids:
            if agreement_line.product_id != self.product_id:
                continue
            matched = agreement_line
            if agreement_line.product_uom_id == self.product_uom_id:
                break
        return matched

    def _get_agreed_price(self):
        self.check_singleton()
        agreement_line = self._get_agreement_line()
        if not agreement_line:
            return None
        order = self.order_id
        price = agreement_line.product_uom_id._get_price_in_unit(
            agreement_line.price_unit, self.product_uom_id or self.product_id.uom_id
        )
        return agreement_line.agreement_id.currency_id._convert(
            price,
            order.currency_id,
            order.company_id,
            self._get_date_order(),
            round=False,
        )

    def _get_pricelist_price(self):
        agreed = self._get_agreed_price()
        return super()._get_pricelist_price() if agreed is None else agreed

    def _get_pricelist_price_before_discount(self):
        agreed = self._get_agreed_price()
        if agreed is None:
            return super()._get_pricelist_price_before_discount()
        return agreed
