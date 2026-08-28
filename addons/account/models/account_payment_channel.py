from odoo import api, fields, models


class AccountPaymentChannel(models.Model):
    _name = "account.payment.channel"
    _description = "Payment Channel"
    _order = "sequence, id"
    _check_company_domain = models.check_company_domain_parent_of

    name = fields.Char(compute="_compute_name", readonly=False, store=True)
    sequence = fields.Integer(default=10)
    payment_method_id = fields.Many2one(
        string="Payment Method",
        comodel_name="account.payment.method",
        domain="[('payment_type', '=?', payment_type), ('id', 'in', available_payment_method_ids)]",
        required=True,
    )
    payment_account_id = fields.Many2one(
        comodel_name="account.account",
        check_company=True,
        copy=False,
        ondelete="restrict",
        domain="['|', ('account_type', 'in', ('asset_current', 'liability_current')), ('id', '=', default_account_id)]",
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        check_company=True,
        index="btree_not_null",
    )
    default_account_id = fields.Many2one(related="journal_id.default_account_id")

    code = fields.Char(related="payment_method_id.code")
    payment_type = fields.Selection(related="payment_method_id.payment_type")
    company_id = fields.Many2one(related="journal_id.company_id")
    available_payment_method_ids = fields.Many2many(
        related="journal_id.available_payment_method_ids"
    )

    @api.depends("journal_id")
    @api.depends_context("hide_payment_journal_id")
    def _compute_display_name(self):
        for method in self:
            if self.env.context.get("hide_payment_journal_id"):
                return super()._compute_display_name()
            method.display_name = f"{method.name} ({method.journal_id.name})"
        return None

    @api.depends("payment_method_id.name")
    def _compute_name(self):
        for method in self:
            if not method.name:
                method.name = method.payment_method_id.name

    @api.constrains("name")
    def _ensure_unique_name_for_journal(self):
        self.journal_id._check_payment_channel_ids_multiplicity()

    def unlink(self):
        unused_payment_channels = self
        for line in self:
            payment_count = (
                self.env["account.payment"]
                .sudo()
                .search_count([("payment_channel_id", "=", line.id)])
            )
            if payment_count > 0:
                unused_payment_channels -= line

        (self - unused_payment_channels).write({"journal_id": False})

        return super(AccountPaymentChannel, unused_payment_channels).unlink()
