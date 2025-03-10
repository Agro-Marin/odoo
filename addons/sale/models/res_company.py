from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class ResCompany(models.Model):
    """Inherits the 'res.company' model to include sales-specific configurations.

    This model adds fields to manage company sales settings, including default quotation validity,
    prepayment percentage, default discount product, and portal confirmation options."""

    _inherit = "res.company"
    _check_company_auto = True

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    sale_discount_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Discount Product",
        check_company=True,
        domain=[
            ("type", "=", "service"),
            ("invoice_policy", "=", "order"),
        ],
        help="Default product used for discounts",
    )
    sale_onboarding_payment_method = fields.Selection(
        selection=[
            ("digital_signature", "Sign online"),
            ("paypal", "PayPal"),
            ("stripe", "Stripe"),
            ("other", "Pay with another payment provider"),
            ("manual", "Manual Payment"),
        ],
        string="Sale onboarding selected payment method",
    )
    quotation_validity_days = fields.Integer(
        string="Default Quotation Validity",
        default=30,
        help="Days between quotation proposal and expiration."
        " 0 days means automatic expiration is disabled",
    )
    prepayment_percent = fields.Float(
        string="Prepayment percentage",
        default=1.0,
        help="The percentage of the amount needed to be paid to confirm quotations.",
    )
    portal_confirmation_sign = fields.Boolean(string="Online Signature", default=True)
    portal_confirmation_pay = fields.Boolean(string="Online Payment")

    # -----------------------------------------------------------
    # CONSTRAINT METHODS
    # -----------------------------------------------------------

    _check_quotation_validity_days = models.Constraint(
        "CHECK(quotation_validity_days >= 0)",
        "You cannot set a negative number for the default quotation validity. Leave empty (or 0) to disable the automatic expiration of quotations.",
    )

    @api.constrains("prepayment_percent")
    def _check_prepayment_percent(self):
        for company in self:
            if company.portal_confirmation_pay and not (
                0 < company.prepayment_percent <= 1.0
            ):
                raise ValidationError(
                    _("Prepayment percentage must be a valid percentage.")
                )
