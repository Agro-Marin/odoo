from odoo import fields, models
from odoo.fields import Domain
from odoo.libs.debug_log import DebugLog
from odoo.tools.misc import format_datetime

_debug = DebugLog(__name__)


class StockQuantityHistory(models.TransientModel):
    _name = "stock.quantity.history"
    _description = "Stock Quantity History"

    inventory_datetime = fields.Datetime(
        string="Inventory at Date",
        default=fields.Datetime.now,
        help="Choose a date to get the inventory at that date",
    )

    def action_view_products_at_date(self):
        tree_view_id = self.env.ref("stock.product_product_stock_tree").id
        form_view_id = self.env.ref("stock.product_form_view_procurement_button").id
        search_view_id = self.env.ref("stock.product_search_form_view_stock_report").id
        domain = Domain("is_storable", "=", True)
        product_id = self.env.context.get("product_id", False)
        product_tmpl_id = self.env.context.get("product_tmpl_id", False)
        if product_id:
            domain &= Domain("id", "=", product_id)
            scope = f"product {product_id}"
        elif product_tmpl_id:
            domain &= Domain("product_tmpl_id", "=", product_tmpl_id)
            scope = f"template {product_tmpl_id}"
        else:
            scope = "all storable products"
        _debug.logic("valuation_at_date", datetime=self.inventory_datetime, scope=scope)
        return {
            "type": "ir.actions.act_window",
            "views": [(tree_view_id, "list"), (form_view_id, "form")],
            "view_mode": "list,form",
            "name": self.env._("Products"),
            "res_model": "product.product",
            "domain": domain,
            "context": dict(self.env.context, to_date=self.inventory_datetime),
            "search_view_id": [search_view_id],
            "display_name": format_datetime(self.env, self.inventory_datetime),
        }
