from odoo import models


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _get_import_criteria_from_variant_default_code(self, product_values):
        if variant_default_code := product_values.get("variant_default_code"):
            return {
                "criteria": [{"domain": [("default_code", "=", variant_default_code)]}]
            }
        return None

    def _get_import_criteria_from_variant_barcode(self, product_values):
        if variant_barcode := product_values.get("variant_barcode"):
            return {"criteria": [{"domain": [("barcode", "=", variant_barcode)]}]}
        return None

    def _get_import_product_search_plan(self):
        return super()._get_import_product_search_plan() + [
            (12, self._get_import_criteria_from_variant_default_code),
            (14, self._get_import_criteria_from_variant_barcode),
        ]
