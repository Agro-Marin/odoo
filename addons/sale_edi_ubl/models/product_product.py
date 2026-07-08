# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _import_retrieve_product_from_variant_default_code(self, product_values):
        """Retrieve a product variant from its own ``default_code``.

        The UBL ``*ItemIdentification::ExtendedID`` elements identify a specific
        variant (as opposed to ``ID``, which identifies the template). See
        :meth:`_get_product_xpaths` in ``sale_edi_xml_ubl_bis3``.
        """
        if variant_default_code := product_values.get("variant_default_code"):
            return {
                "criteria": [{"domain": [("default_code", "=", variant_default_code)]}]
            }

    def _import_retrieve_product_from_variant_barcode(self, product_values):
        """Retrieve a product variant from its own ``barcode`` (UBL ExtendedID)."""
        if variant_barcode := product_values.get("variant_barcode"):
            return {"criteria": [{"domain": [("barcode", "=", variant_barcode)]}]}

    def _get_retrieval_product_search_plan(self):
        """Override of `account` to look up product variants by their own
        identifiers, tried after the template ``default_code`` but before the
        (fuzzy) name match.
        """
        return super()._get_retrieval_product_search_plan() + [
            (12, self._import_retrieve_product_from_variant_default_code),
            (14, self._import_retrieve_product_from_variant_barcode),
        ]
