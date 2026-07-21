from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_round


class AccountCashRounding(models.Model):
    """Rounding rule applied to invoice totals to match the smallest circulating coinage."""

    # Some countries need a rounding line on an invoice only because the smallest
    # coinage has been removed from circulation. For example, Switzerland rounds
    # invoices to 0.05 CHF because coins of 0.01 CHF and 0.02 CHF aren't used anymore.
    # See https://en.wikipedia.org/wiki/Cash_rounding for more details.
    _name = "account.cash.rounding"
    _description = "Account Cash Rounding"
    _check_company_auto = True

    name = fields.Char(string="Name", translate=True, required=True)
    rounding = fields.Float(
        string="Rounding Precision",
        required=True,
        default=0.01,
        help="Represent the non-zero value smallest coinage (for example, 0.05).",
    )
    strategy = fields.Selection(
        [
            ("biggest_tax", "Modify tax amount"),
            ("add_invoice_line", "Add a rounding line"),
        ],
        string="Rounding Strategy",
        default="add_invoice_line",
        required=True,
        help="Specify which way will be used to round the invoice amount to the rounding precision",
    )
    profit_account_id = fields.Many2one(
        "account.account",
        string="Profit Account",
        company_dependent=True,
        check_company=True,
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]",
        ondelete="restrict",
    )
    loss_account_id = fields.Many2one(
        "account.account",
        string="Loss Account",
        company_dependent=True,
        check_company=True,
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]",
        ondelete="restrict",
    )
    rounding_method = fields.Selection(
        string="Rounding Method",
        required=True,
        selection=[("UP", "Up"), ("DOWN", "Down"), ("HALF-UP", "Nearest")],
        default="HALF-UP",
        help="The tie-breaking rule used for float rounding operations",
    )

    @api.constrains("rounding")
    def validate_rounding(self):
        for record in self:
            if record.rounding <= 0:
                raise ValidationError(
                    _("Please set a strictly positive rounding value.")
                )

    def round(self, amount):
        """Compute the rounding on the amount passed as parameter.

        :param amount: the amount to round
        :return: the rounded amount depending the rounding value and the rounding method
        """
        return float_round(
            amount,
            precision_rounding=self.rounding,
            rounding_method=self.rounding_method,
        )

    def compute_difference(self, currency, amount):
        """Compute the difference between the amount and its rounded value.

        :param currency: The currency.
        :param amount: The amount
        :return: round(difference)
        """
        amount = currency.round(amount)
        # e.g. amount=23.91 rounded to 24.00 yields a difference of 0.09.
        difference = self.round(amount) - amount
        return currency.round(difference)
