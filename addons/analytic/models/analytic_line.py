from dateutil.relativedelta import relativedelta

from odoo import fields, models


class AccountAnalyticLine(models.Model):
    _name = "account.analytic.line"
    _inherit = ["mixin.analytic.plan.fields"]
    _description = "Analytic Line"
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        "Description",
        required=True,
    )
    date = fields.Date(
        "Date",
        required=True,
        index=True,
        default=fields.Date.context_today,
    )
    amount = fields.Monetary(
        "Amount",
        required=True,
        default=0.0,
    )
    unit_amount = fields.Float(
        "Quantity",
        default=0.0,
    )
    product_uom_id = fields.Many2one(
        "uom.uom",
        string="Unit",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        check_company=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="User",
        default=lambda self: self.env.context.get("user_id", self.env.user.id),
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        readonly=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Currency",
        readonly=True,
        store=True,
        compute_sudo=True,
    )
    category = fields.Selection(
        [("other", "Other")],
        default="other",
    )
    from_last_fiscal_year = fields.Boolean(
        search="_search_from_last_fiscal_year",
        store=False,
        exportable=False,
        export_string_translation=False,
    )
    analytic_distribution = fields.Json(
        "Analytic Distribution",
        compute="_compute_analytic_distribution",
        inverse="_inverse_analytic_distribution",
    )
    analytic_precision = fields.Integer(
        store=False,
        default=lambda self: self.env["decimal.precision"].get_precision(
            "Percentage Analytic"
        ),
    )

    def _compute_analytic_distribution(self):
        for line in self:
            line.analytic_distribution = {line._get_distribution_key(): 100}

    def _inverse_analytic_distribution(self):
        empty_account = dict.fromkeys(self._get_plan_fnames(), False)
        to_create_vals = []
        for line in self:
            final_distribution = self.env["mixin.analytic"]._merge_distribution(
                {line._get_distribution_key(): 100},
                line.analytic_distribution or {},
            )
            if not final_distribution:
                continue
            amount_fname = line._split_amount_fname()
            vals_list = [
                {amount_fname: line[amount_fname] * percent / 100}
                | empty_account
                | {
                    account.plan_id._column_name(): account.id
                    for account in self.env["account.analytic.account"].browse(
                        int(aid) for aid in account_ids.split(",")
                    )
                }
                for account_ids, percent in final_distribution.items()
            ]

            line.write(vals_list[0])
            to_create_vals += [line.copy_data(vals)[0] for vals in vals_list[1:]]
        if to_create_vals:
            self.create(to_create_vals)
            self.env.user._bus_send(
                "simple_notification",
                {
                    "type": "success",
                    "message": self.env._(
                        "%s analytic lines created", len(to_create_vals)
                    ),
                },
            )

    def _split_amount_fname(self):
        return "amount"

    def _search_from_last_fiscal_year(self, operator, value):
        fiscalyear_date_range = self.env.company.compute_fiscalyear_dates(
            fields.Date.today()
        )
        return [
            ("date", ">=", fiscalyear_date_range["date_from"] - relativedelta(years=1))
        ]
