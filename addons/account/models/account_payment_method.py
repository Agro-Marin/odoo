from odoo import api, fields, models
from odoo.fields import Domain


class AccountPaymentMethod(models.Model):
    _name = "account.payment.method"
    _description = "Payment Methods"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    payment_type = fields.Selection(
        selection=[("inbound", "Inbound"), ("outbound", "Outbound")], required=True
    )

    _name_code_unique = models.Constraint(
        "unique (code, payment_type)",
        "The combination code/payment type already exists!",
    )

    @api.model_create_multi
    def create(self, vals_list):
        payment_methods = super().create(vals_list)
        methods_info = self._get_payment_method_information()
        return self._auto_link_payment_methods(payment_methods, methods_info)

    def _auto_link_payment_methods(self, payment_methods, methods_info):
        for method in payment_methods:
            information = methods_info.get(method.code, {})
            if information.get("mode") == "multi":
                method_domain = method._get_payment_method_domain(method.code)
                journals = self.env["account.journal"].search(method_domain)
                self.env["account.payment.method.line"].create(
                    [
                        {
                            "name": method.name,
                            "payment_method_id": method.id,
                            "journal_id": journal.id,
                        }
                        for journal in journals
                    ]
                )
        return payment_methods

    @api.model
    def _get_payment_method_domain(self, code, with_currency=True, with_country=True):
        if not code:
            return Domain.TRUE
        information = self._get_payment_method_information().get(code)
        journal_types = information.get("type", ("bank", "cash", "credit"))
        domain = Domain("type", "in", journal_types)

        if with_currency and (currency_ids := information.get("currency_ids")):
            domain &= (
                Domain("currency_id", "=", False)
                & Domain("company_id.currency_id", "in", currency_ids)
            ) | Domain("currency_id", "in", currency_ids)

        if with_country and (country_id := information.get("country_id")):
            domain &= Domain("company_id.account_fiscal_country_id", "=", country_id)

        return domain

    @api.model
    def _get_payment_method_information(self):
        return {
            "manual": {"mode": "multi", "type": ("bank", "cash", "credit")},
        }

    @api.model
    def _get_sdd_payment_method_code(self):
        return []

    def unlink(self):
        self.env["account.payment.method.line"].search(
            [("payment_method_id", "in", self.ids)]
        ).unlink()
        return super().unlink()


class AccountPaymentMethodLine(models.Model):
    _name = "account.payment.method.line"
    _description = "Payment Methods"
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
        self.journal_id._check_payment_method_line_ids_multiplicity()

    def unlink(self):
        unused_payment_method_lines = self
        for line in self:
            payment_count = (
                self.env["account.payment"]
                .sudo()
                .search_count([("payment_method_line_id", "=", line.id)])
            )
            if payment_count > 0:
                unused_payment_method_lines -= line

        (self - unused_payment_method_lines).write({"journal_id": False})

        return super(AccountPaymentMethodLine, unused_payment_method_lines).unlink()
