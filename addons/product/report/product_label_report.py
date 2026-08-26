from collections import defaultdict

from odoo import api, models
from odoo.exceptions import UserError


class MixinProductLabelReport(models.AbstractModel):

    _name = "mixin.product.label.report"
    _description = "Product Label Report"

    def _get_report_values(self, docids, data):
        data = data or {}
        layout = self.env["product.label.layout"].browse(
            self._get_label_id(data.get("layout_wizard"))
        )

        if data.get("studio") and docids and not data.get("active_model"):
            return self._get_studio_report_values(docids, layout)

        Product = self._get_label_product_model(data.get("active_model"))
        if not layout:
            raise UserError(
                self.env._(
                    "This label layout is no longer available. Please reopen the"
                    " print dialog and try again."
                )
            )

        quantity_by_product, total = self._get_label_quantities(data, Product)
        return {
            "quantity": quantity_by_product,
            "page_numbers": self._get_label_page_count(total, layout),
            "price_included": data.get("price_included"),
            "extra_html": layout.extra_html,
            "pricelist": layout.pricelist_id,
        }

    def _get_studio_report_values(self, docids, layout):
        products = (
            self.env["product.template"]
            .with_context(display_default_code=False)
            .browse(docids)
        )
        quantity_by_product = defaultdict(list)
        for product in products:
            quantity_by_product[product].append((product.barcode, 1))
        return {
            "quantity": quantity_by_product,
            "page_numbers": 1,
            "pricelist": layout.pricelist_id,
        }

    @api.model
    def _get_label_product_model(self, active_model):
        if active_model not in ("product.template", "product.product"):
            raise UserError(
                self.env._(
                    "Product model not defined, Please contact your administrator."
                )
            )
        return self.env[active_model].with_context(display_default_code=False)

    @api.model
    def _get_label_id(self, value):
        try:
            return int(value)
        except TypeError, ValueError:
            return 0

    def _get_label_quantities(self, data, Product):
        quantity_by_product = defaultdict(list)
        total = 0

        requested = {
            self._get_label_id(product_id): self._get_label_quantity(quantity)
            for product_id, quantity in (data.get("quantity_by_product") or {}).items()
        }
        for product in Product.search(
            [("id", "in", list(requested))], order="name desc"
        ):
            quantity = requested[product.id]
            quantity_by_product[product].append((product.barcode, quantity))
            total += quantity

        for product_id, barcodes in (data.get("custom_barcodes") or {}).items():
            product = Product.browse(self._get_label_id(product_id)).exists()
            if not product:
                continue
            pairs = [
                (barcode, self._get_label_quantity(quantity))
                for barcode, quantity in barcodes
            ]
            quantity_by_product[product] += pairs
            total += sum(quantity for _, quantity in pairs)

        return quantity_by_product, total

    @api.model
    def _get_label_quantity(self, value):
        try:
            quantity = int(value)
        except TypeError, ValueError:
            raise UserError(
                self.env._("%s is not a number of labels.", value)
            ) from None
        if quantity < 0:
            raise UserError(self.env._("A number of labels cannot be negative."))
        return quantity

    @api.model
    def _get_label_page_count(self, total, layout):
        per_page = layout.rows * layout.columns
        if not total or per_page <= 0:
            raise UserError(
                self.env._("There is nothing to print with this label layout.")
            )
        return (total - 1) // per_page + 1


class ReportProductReport_Producttemplatelabel2x7(models.AbstractModel):
    _name = "report.product.report_producttemplatelabel2x7"
    _inherit = ["mixin.product.label.report"]
    _description = "Product Label Report 2x7"


class ReportProductReport_Producttemplatelabel4x7(models.AbstractModel):
    _name = "report.product.report_producttemplatelabel4x7"
    _inherit = ["mixin.product.label.report"]
    _description = "Product Label Report 4x7"


class ReportProductReport_Producttemplatelabel4x12(models.AbstractModel):
    _name = "report.product.report_producttemplatelabel4x12"
    _inherit = ["mixin.product.label.report"]
    _description = "Product Label Report 4x12"


class ReportProductReport_Producttemplatelabel4x12noprice(models.AbstractModel):
    _name = "report.product.report_producttemplatelabel4x12noprice"
    _inherit = ["mixin.product.label.report"]
    _description = "Product Label Report 4x12 No Price"


class ReportProductReport_Producttemplatelabel_Dymo(models.AbstractModel):
    _name = "report.product.report_producttemplatelabel_dymo"
    _inherit = ["mixin.product.label.report"]
    _description = "Product Label Report Dymo"
