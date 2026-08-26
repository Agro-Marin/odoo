from odoo import api, fields, models
from odoo.fields import Domain


class ResPartnerCategory(models.Model):
    _inherit = "res.partner.category"

    order_type = fields.Selection(
        selection=[
            ("sale", "Sale Orders"),
            ("purchase", "Purchase Orders"),
        ],
        string="Order Scope",
        help="Order type whose partner selection this category restricts. "
        "Leave empty to restrict every order type.",
    )
    group_ids = fields.Many2many(
        comodel_name="res.groups",
        string="Reserved For",
        help="Only users in one of these groups may pick a partner tagged with "
        "this category, or with one of its children, on an order of the scope "
        "above. Leave empty to place the category outside the restriction.",
    )

    @api.model
    def _get_domain_partner_allowed(self, order_type):
        reserved = self.sudo().search(
            Domain("group_ids", "!=", False)
            & Domain("order_type", "in", (False, order_type)),
        )
        if not reserved:
            return Domain.TRUE

        user_group_ids = set(self.env.user._effective_group_ids())
        allowed = reserved.filtered(
            lambda category: user_group_ids.intersection(category.group_ids.ids),
        )
        if not allowed:
            return Domain.FALSE
        return Domain("category_id", "child_of", allowed.ids)
