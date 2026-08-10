from odoo import api, fields, models
from odoo.tools.translate import _


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    user_purchase_id = fields.Many2one(
        comodel_name="res.users",
        string="Buyer",
    )
    property_purchase_currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Supplier Currency",
        company_dependent=True,
        help="This currency will be used for purchases from the current partner",
    )
    purchase_order_ids = fields.One2many(
        comodel_name="purchase.order",
        inverse_name="partner_id",
        string="Purchase Order",
    )
    purchase_order_count = fields.Integer(
        string="Purchase Order Count",
        compute="_compute_purchase_order_count",
        groups="purchase.group_purchase_user",
    )
    purchase_warn_msg = fields.Text(string="Message for Purchase Order")
    receipt_reminder_email = fields.Boolean(
        string="Receipt Reminder",
        company_dependent=True,
        help="Automatically send a confirmation email to the vendor X days before the expected receipt date, asking him to confirm the exact date.",
    )
    reminder_date_before_receipt = fields.Integer(
        string="Days Before Receipt",
        company_dependent=True,
        help="Number of days to send reminder email before the promised receipt date",
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_purchase_order_count(self):
        self._compute_order_count(
            "purchase.order",
            "purchase_order_count",
            "purchase.group_purchase_user",
            domain=self._get_purchase_order_domain_count(),
        )

    def _compute_application_statistics_hook(self):
        data_list = super()._compute_application_statistics_hook()
        return self._add_order_statistics(
            data_list,
            "purchase_order_count",
            "purchase.group_purchase_user",
            "fa-solid fa-credit-card",
            _("Purchases"),
            "o_tag_color_5",
        )

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    @api.model
    def _get_purchase_order_domain_count(self):
        return []
