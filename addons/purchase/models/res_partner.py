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
        compute="_compute_user_purchase_id",
        precompute=True,
        readonly=False,
        store=True,
        # mail tracks the salesperson (``user_id``, sequence 4); the buyer is
        # the same kind of assignment and was the only half not logged. Bare
        # ``tracking=True`` on purpose: 1-5 is mail's curated block for the
        # core identity fields, and purchase does not belong inside it.
        tracking=True,
        help="The internal user in charge of purchases from this contact.",
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

    @api.depends("parent_id")
    def _compute_user_purchase_id(self):
        """Mirror ``res.partner._compute_user_id`` for the buyer.

        ``user_id`` ("Salesperson") is declared in ``base`` and has always
        cascaded from the parent company to its contacts. ``user_purchase_id``
        is purchase's own field — the name ``user_id`` was taken — and never
        gained the same rule, so a contact under a company showed no buyer.

        ``purchase.order`` papered over it by falling back to
        ``commercial_partner_id`` when defaulting the buyer, but
        ``purchase_stock``'s stock rules read the field raw: an RFQ generated
        for a child contact got no buyer at all, and its merge domain
        (``user_id = False``) would not match the buyer's existing draft.
        """
        for partner in self.filtered(
            lambda partner: (
                not partner.user_purchase_id
                and not partner.is_company
                and partner.parent_id.user_purchase_id
            )
        ):
            partner.user_purchase_id = partner.parent_id.user_purchase_id

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
