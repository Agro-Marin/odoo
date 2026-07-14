# Part of Odoo. See LICENSE file for full copyright and licensing details.

import math

from odoo import _, api, models
from odoo.exceptions import UserError


class ReportProductReport_Pricelist(models.AbstractModel):
    _name = "report.product.report_pricelist"
    _description = "Pricelist Report"

    MAX_QUANTITIES = 100

    def _get_report_values(self, docids, data):
        return self._get_report_data(data, "pdf")

    @api.readonly
    @api.model
    def get_html(self, data):
        render_values = self._get_report_data(data, "html")
        return self.env["ir.qweb"]._render(
            "product.report_pricelist_page", render_values
        )

    def _get_report_data(self, data, report_type="html"):
        # `data` may come straight from a client request (`get_html` and the
        # /product/export/pricelist/ route): validate it instead of crashing.
        quantities = self._parse_quantities(data.get("quantities"))
        try:
            data_pricelist_id = data.get("pricelist_id")
            pricelist_id = data_pricelist_id and int(data_pricelist_id)
        except ValueError, TypeError:
            pricelist_id = False
        pricelist = self.env["product.pricelist"].browse(pricelist_id).exists()
        if not pricelist:
            pricelist = self.env["product.pricelist"].search([], limit=1)

        active_model = data.get("active_model", "product.template")
        if active_model not in ("product.template", "product.product"):
            raise UserError(_("The pricelist report can only be printed for products."))
        try:
            active_ids = [int(id_) for id_ in data.get("active_ids") or []]
        except ValueError, TypeError:
            raise UserError(_("Invalid product ids.")) from None
        is_product_tmpl = active_model == "product.template"
        ProductClass = self.env[active_model]

        products = ProductClass.browse(active_ids).exists() if active_ids else []
        products_data = [
            self._get_product_data(is_product_tmpl, product, pricelist, quantities)
            for product in products
        ]

        return {
            "is_html_type": report_type == "html",
            "is_product_tmpl": is_product_tmpl,
            "display_pricelist_title": data.get("display_pricelist_title", False)
            and bool(data["display_pricelist_title"]),
            "pricelist": pricelist,
            "products": products_data,
            "quantities": quantities,
            "docs": pricelist,
        }

    def _parse_quantities(self, quantities):
        """Validate the client-provided quantity columns.

        :param quantities: raw `quantities` value from the request payload
        :returns: a non-empty, bounded list of positive numbers
        :raises UserError: on non-numeric or out-of-bound input
        """
        if not quantities:
            return [1]
        try:
            parsed = []
            for qty in quantities:
                value = float(qty)
                if not math.isfinite(value):
                    raise ValueError
                # Whole quantities are kept as ints so they display (and key
                # the price dicts) as `5`, not `5.0`.
                parsed.append(int(value) if value.is_integer() else value)
            quantities = parsed
        except ValueError, TypeError:
            raise UserError(_("Invalid quantities.")) from None
        if len(quantities) > self.MAX_QUANTITIES:
            raise UserError(
                _(
                    "At most %s quantity columns can be printed on the pricelist"
                    " report.",
                    self.MAX_QUANTITIES,
                )
            )
        if any(qty <= 0 for qty in quantities):
            raise UserError(_("Quantities must be positive."))
        return quantities

    def _get_product_data(self, is_product_tmpl, product, pricelist, quantities):
        data = {
            "id": product.id,
            "name": (is_product_tmpl and product.name) or product.display_name,
            "price": dict.fromkeys(quantities, 0.0),
            "uom": product.uom_id.name,
        }
        for qty in quantities:
            data["price"][qty] = pricelist._get_product_price(product, qty)

        if is_product_tmpl and product.product_variant_count > 1:
            data["variants"] = [
                self._get_product_data(False, variant, pricelist, quantities)
                for variant in product.product_variant_ids
            ]

        return data
