from odoo import api, fields, models
from odoo.tools.float_utils import float_round
from odoo.tools.translate import _

from odoo.addons.base.models.res_partner import WARNING_MESSAGE, WARNING_HELP


class ProductTemplate(models.Model):
    """Inherit ProductTemplate"""

    _inherit = "product.template"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    # purchase_method
    bill_policy = fields.Selection(
        selection=[
            ("purchase", "On ordered quantities"),
            ("receive", "On received quantities"),
        ],
        string="Control Policy",
        compute="_compute_bill_policy",
        store=True,
        precompute=True,
        readonly=False,
        help="On ordered quantities: Control bills based on ordered quantities.\n"
        "On received quantities: Control bills based on received quantities.",
    )
    purchase_line_warn = fields.Selection(
        WARNING_MESSAGE,
        string="Purchase Order Line Warning",
        required=True,
        default="no-message",
        help=WARNING_HELP,
    )
    purchase_line_warn_msg = fields.Text(
        string="Message for Purchase Order Line",
    )
    qty_purchased = fields.Float(
        string="Purchased",
        digits="Product Unit",
        compute="_compute_qty_purchased",
    )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    def _compute_qty_purchased(self):
        for template in self.with_context(active_test=False):
            template.qty_purchased = float_round(
                sum(p.qty_purchased for p in template.product_variant_ids),
                precision_rounding=template.uom_id.rounding,
            )

    @api.depends("type")
    def _compute_bill_policy(self):
        default_bill_policy = (
            self.env["product.template"]
            .default_get(["bill_policy"])
            .get("bill_policy", "receive")
        )
        for product in self:
            if product.type == "service":
                product.bill_policy = "purchase"
            else:
                product.bill_policy = default_bill_policy

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    def action_view_po(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "purchase.action_purchase_history"
        )
        action["domain"] = [
            ("state", "=", "purchase"),
            ("product_id", "in", self.with_context(active_test=False).product_variant_ids.ids),
        ]
        action["display_name"] = _("Purchase History for %s", self.display_name)
        return action

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _get_backend_root_menu_ids(self):
        return super()._get_backend_root_menu_ids() + [
            self.env.ref("purchase.menu_purchase_root").id
        ]

    @api.model
    def get_import_templates(self):
        res = super().get_import_templates()
        if self.env.context.get("purchase_product_template"):
            return [
                {
                    "label": _("Import Template for Products"),
                    "template": "/purchase/static/xls/product_purchase.xls",
                }
            ]
        return res
