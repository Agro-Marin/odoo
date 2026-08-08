# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models
from odoo.libs.numbers import float_repr


class StockForecasted_Product_Product(models.AbstractModel):
    _inherit = "stock.forecasted_product_product"

    def _get_report_header(self, product_template_ids, product_ids, wh_location_ids):
        """Overrides to computes the valuations of the stock."""
        res = super()._get_report_header(
            product_template_ids, product_ids, wh_location_ids
        )
        if (
            not self.env.user.has_group("stock.group_stock_manager")
            or not wh_location_ids
        ):
            return res
        company = self.env["stock.location"].browse(wh_location_ids[0]).company_id
        domain_quants = [
            ("company_id", "=", company.id),
            ("location_id", "in", wh_location_ids),
        ]
        if product_template_ids:
            domain_quants += [
                ("product_id.product_tmpl_id", "in", product_template_ids)
            ]
        else:
            domain_quants += [("product_id", "in", product_ids)]
        quants = self.env["stock.quant"].search(domain_quants)

        # The warehouse's company, not `env.company`: these quants were filtered to
        # `company` above, and `quant.value` is expressed in the quant's own
        # company's currency (as `quant.currency_id` has always claimed). Labelling
        # that sum with the active company's symbol would put two currencies in one
        # figure whenever a user looks at another company's warehouse.
        currency = company.currency_id
        value = sum(quants.mapped("value"))
        value = float_repr(value, precision_digits=currency.decimal_places)
        if currency.position == "after":
            value = "%s %s" % (value, currency.symbol)
        else:
            value = "%s %s" % (currency.symbol, value)
        res["value"] = value
        return res
