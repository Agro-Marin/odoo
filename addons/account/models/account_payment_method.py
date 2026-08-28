from odoo import api, fields, models
from odoo.fields import Domain


class AccountPaymentMethod(models.Model):
    _name = "account.payment.method"
    _description = "Payment Method"

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
                self.env["account.payment.channel"].create(
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
        self.env["account.payment.channel"].search(
            [("payment_method_id", "in", self.ids)]
        ).unlink()
        return super().unlink()
