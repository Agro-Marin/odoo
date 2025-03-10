from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    """Inherit ResConfigSettings"""

    _inherit = "res.config.settings"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    company_currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Company Currency",
        readonly=True,
    )
    po_lock = fields.Selection(
        related="company_id.po_lock",
        string="Purchase Order Modification *",
        readonly=False,
    )
    po_lead = fields.Float(
        related="company_id.po_lead",
        readonly=False,
    )
    lock_confirmed_po = fields.Boolean(
        "Lock Confirmed Orders",
        default=lambda self: self.env.company.po_lock == "lock",
    )
    use_po_lead = fields.Boolean(
        string="Security Lead Time for Purchase",
        config_parameter="purchase.use_po_lead",
        help="Margin of error for vendor lead times. When the system generates Purchase Orders for "
        "reordering products, they will be scheduled that many days earlier to cope with "
        "unexpected vendor delays.",
    )
    po_approval = fields.Boolean(
        related="company_id.po_approval",
        readonly=False,
    )
    group_send_reminder = fields.Boolean(
        "Receipt Reminder",
        implied_group="purchase.group_send_reminder",
        default=True,
        help="Allow automatically send email to remind your vendor the receipt date",
    )
    group_warning_purchase = fields.Boolean(
        "Purchase Warnings", implied_group="purchase.group_warning_purchase"
    )
    module_account_3way_match = fields.Boolean(
        "3-way matching: purchases, receptions and bills"
    )
    module_purchase_product_matrix = fields.Boolean("Purchase Grid Entry")
    module_purchase_requisition = fields.Boolean("Purchase Agreements")

    @api.onchange("use_po_lead")
    def _onchange_use_po_lead(self):
        if not self.use_po_lead:
            self.po_lead = 0.0

    @api.onchange("group_product_variant")
    def _onchange_group_product_variant_purchase(self):
        """If the user disables the product variants -> disable the product configurator as well"""
        if self.module_purchase_product_matrix and not self.group_product_variant:
            self.module_purchase_product_matrix = False

    @api.onchange("module_purchase_product_matrix")
    def _onchange_module_purchase_product_matrix(self):
        """The product variant grid requires the product variants activated
        If the user enables the product configurator -> enable the product variants as well
        """
        if self.module_purchase_product_matrix and not self.group_product_variant:
            self.group_product_variant = True

    def set_values(self):
        super().set_values()
        po_lock = "lock" if self.lock_confirmed_po else "edit"
        if self.po_lock != po_lock:
            self.po_lock = po_lock
