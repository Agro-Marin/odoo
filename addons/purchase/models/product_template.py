from odoo import _, api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    purchased_product_qty = fields.Float(
        string="Purchased",
        digits="Product Unit",
        compute="_compute_purchased_product_qty",
    )
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
    purchase_line_warn_msg = fields.Text(string="Message for Purchase Order Line")

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

    def _compute_purchased_product_qty(self):
        for template in self.with_context(active_test=False):
            template.purchased_product_qty = template.uom_id.round(
                sum(p.purchased_product_qty for p in template.product_variant_ids)
            )

    def action_view_po(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "purchase.action_purchase_history"
        )
        action["domain"] = [
            "&",
            ("state", "=", "purchase"),
            (
                "product_id",
                "in",
                self.with_context(active_test=False).product_variant_ids.ids,
            ),
        ]
        action["display_name"] = _("Purchase History for %s", self.display_name)
        return action

    def _get_backend_root_menu_ids(self):
        return super()._get_backend_root_menu_ids() + [
            self.env.ref("purchase.menu_purchase_root").id
        ]

    @api.model
    def get_import_templates(self):
        res = super(ProductTemplate, self).get_import_templates()
        if self.env.context.get("purchase_product_template"):
            return [
                {
                    "label": _("Import Template for Products"),
                    "template": "/purchase/static/xls/product_purchase.xls",
                },
            ]
        return res
