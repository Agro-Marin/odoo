from odoo import models


class PurchaseEdiXmlUbl_Bis3(models.AbstractModel):
    _name = "purchase.edi.xml.ubl_bis3"
    _inherit = ["trade.edi.xml.ubl_bis3"]
    _description = "Purchase UBL BIS Ordering 3.5"

    _order_type_code = "105"
    _order_reference_field = "partner_ref"
    _order_reference_node = "cac:QuotationDocumentReference"
    _order_origin_node = "OriginatorDocumentReference"
    _order_delivery_field = "dest_address_id"

    def _setup_base_lines(self, vals):
        super()._setup_base_lines(vals)

        for base_line in vals["base_lines"]:
            product = base_line["product_id"]
            partner = base_line["partner_id"]
            base_line["supplier_info"] = self._get_supplier_info(product, partner)

    def _get_supplier_info(self, product, partner):
        return product.variant_seller_ids.filtered(
            lambda s: (
                s.partner_id == partner
                and (
                    s.product_id == product
                    or (
                        not s.product_id
                        and s.product_tmpl_id == product.product_tmpl_id
                    )
                )
                and (s.product_code or s.product_name)
            ),
        )[:1]

    def _ubl_add_line_item_name_description_nodes(self, vals):
        super()._ubl_add_line_item_name_description_nodes(vals)

        item_node = vals["item_node"]
        base_line = vals["line_vals"]["base_line"]
        supplier_info = base_line["supplier_info"]
        if supplier_info.product_name:
            item_node["cbc:Name"]["_text"] = supplier_info.product_name

    def _ubl_add_line_item_identification_nodes(self, vals):
        super()._ubl_add_line_item_identification_nodes(vals)

        item_node = vals["item_node"]
        base_line = vals["line_vals"]["base_line"]
        supplier_info = base_line["supplier_info"]
        if supplier_info.product_code:
            item_node["cac:SellersItemIdentification"] = {
                "cbc:ID": {"_text": supplier_info.product_code},
            }
