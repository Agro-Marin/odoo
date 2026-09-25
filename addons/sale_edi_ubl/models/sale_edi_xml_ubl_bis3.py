from odoo import models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class SaleEdiXmlUbl_Bis3(models.AbstractModel):
    _name = "sale.edi.xml.ubl_bis3"
    _inherit = ["trade.edi.xml.ubl_bis3"]
    _description = "Sale BIS Ordering 3.5"

    _order_type_code = "220"
    _order_reference_field = "client_order_ref"
    _order_reference_node = "cac:OriginatorDocumentReference"
    _order_origin_node = "QuotationDocumentReference"
    _order_delivery_field = "partner_shipping_id"

    def _add_order_header_nodes(self, document_node, vals):
        super()._add_order_header_nodes(document_node, vals)
        document_node["cac:ValidityPeriod"] = {
            "cbc:EndDate": {"_text": vals["order"].date_validity},
        }

    def _get_order_prepaid_amount(self, order):
        return order.amount_paid

    def _get_order_payable_amount(self, order, line_extension_amount, tax_amount):
        return order.amount_total - order.amount_paid

    def _prepare_order_vals(self, order, tree):
        order_vals, logs = super()._prepare_order_vals(order, tree)
        order_vals.pop("notes", False)
        for command in order_vals["line_ids"]:
            command[2].pop("discount", None)
        return order_vals, logs

    def _import_order_ubl(self, order, file_data, new):
        res = super()._import_order_ubl(order, file_data, new)
        _debug.pipeline("edi_prices_recomputed", order=order, lines=order.line_ids)
        order.line_ids.filtered("product_id").with_context(
            force_price_recomputation=True
        )._compute_price_and_discount()

        return res

    def _get_product_xpaths(self):
        return {
            **super()._get_product_xpaths(),
            "variant_barcode": "./cac:Item/cac:StandardItemIdentification/cbc:ExtendedID",
            "variant_default_code": "./cac:Item/cac:SellersItemIdentification/cbc:ExtendedID",
        }
