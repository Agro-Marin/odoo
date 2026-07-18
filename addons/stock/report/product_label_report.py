from collections import defaultdict

from markupsafe import Markup

from odoo import _, models
from odoo.exceptions import UserError


class ReportStockLabel_Product_Product_View(models.AbstractModel):
    _name = "report.stock.label_product_product_view"
    _description = "Product Label Report"

    def _get_report_values(self, docids, data):
        if data.get("active_model") == "product.template":
            Product = self.env["product.template"]
        elif data.get("active_model") == "product.product":
            Product = self.env["product.product"]
        else:
            raise UserError(
                _("Product model not defined, Please contact your administrator.")
            )

        # The report data carries plain strings only. The ZPL templates in
        # `report/product_templates.xml` apply the `markup` helper below at the
        # point of output to bypass QWeb's HTML escaping (which would corrupt
        # the plain-text ZPL stream); an HTML template must never do that.
        quantity_by_product = defaultdict(list)
        for p, q in (data.get("quantity_by_product") or {}).items():
            product = Product.browse(int(p))
            default_code = product.default_code or ""
            product_info = {
                "barcode": product.barcode or "",
                "quantity": q,
                "display_name": product.display_name,
                "default_code": (default_code[:15], default_code[15:30]),
            }
            quantity_by_product[product].append(product_info)
        if data.get("custom_barcodes"):
            # we expect custom barcodes to be: {product: [(barcode, qty_of_barcode)]}
            for product, barcodes_qtys in data.get("custom_barcodes").items():
                product = Product.browse(int(product))
                default_code = product.default_code or ""
                for barcode_qty in barcodes_qtys:
                    quantity_by_product[product].append(
                        {
                            "barcode": barcode_qty[0],
                            "quantity": barcode_qty[1],
                            "display_name": product.display_name,
                            "default_code": (
                                default_code[:15],
                                default_code[15:30],
                            ),
                        }
                    )
        data["quantity"] = quantity_by_product
        layout_wizard = self.env["product.label.layout"].browse(
            data.get("layout_wizard")
        )
        data["pricelist"] = layout_wizard.pricelist_id
        data["markup"] = Markup

        return data


class ReportStockLabel_Lot_Template_View(models.AbstractModel):
    _name = "report.stock.label_lot_template_view"
    _description = "Lot Label Report"

    def _get_report_values(self, docids, data):
        # Same design as the product labels above: plain strings here, `markup`
        # applied by the ZPL template at the point of output.
        lots = self.env["stock.lot"].browse(docids)
        lot_list = [
            {
                "display_name": lot.product_id.display_name,
                # Deprecated alias, kept for product_expiry's inherited
                # template (label_lot_template_view_expiry); drop it once that
                # template reads `display_name`.
                "display_name_markup": lot.product_id.display_name,
                "name": lot.name,
                "lot_record": lot,
            }
            for lot in lots
        ]
        return {
            "docs": lot_list,
            "markup": Markup,
        }
