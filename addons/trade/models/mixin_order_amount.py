from odoo import api, fields, models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class MixinOrderAmount(models.AbstractModel):
    _name = "mixin.order.amount"
    _description = "Order Amount Computation"

    currency_id = fields.Many2one(comodel_name="res.currency")

    amount_untaxed = fields.Monetary(
        string="Untaxed Amount",
        compute="_compute_amounts",
        store=True,
        tracking=True,
    )
    amount_tax = fields.Monetary(
        string="Taxes",
        compute="_compute_amounts",
        store=True,
        tracking=True,
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amounts",
        store=True,
        tracking=True,
    )
    tax_totals = fields.Binary(
        compute="_compute_tax_totals",
        exportable=False,
    )

    def _prepare_tax_totals_data(self):
        self.check_singleton()
        AccountTax = self.env["account.tax"]
        order_lines = self.line_ids.filtered(lambda line: not line.display_type)
        base_lines = [
            line._prepare_base_line_for_taxes_computation() for line in order_lines
        ]
        base_lines += self._get_additional_base_lines()
        AccountTax._add_tax_details_in_base_lines(base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, self.company_id)
        _debug.perf.count(
            "tax_totals_data", order=self, lines=len(order_lines), base=len(base_lines)
        )
        return AccountTax._get_tax_totals_summary(
            base_lines=base_lines,
            currency=self.currency_id or self.company_id.currency_id,
            company=self.company_id,
        )

    def _get_additional_base_lines(self):
        return []

    @api.depends_context("lang")
    @api.depends(
        "company_id",
        "currency_id",
        "payment_term_id",
        "line_ids.price_subtotal",
    )
    def _compute_tax_totals(self):
        for order in self:
            order.tax_totals = order._prepare_tax_totals_data()

    @api.depends("tax_totals")
    def _compute_amounts(self):
        for order in self:
            tax_totals = order.tax_totals
            order.amount_untaxed = tax_totals["base_amount_currency"]
            order.amount_tax = tax_totals["tax_amount_currency"]
            order.amount_total = tax_totals["total_amount_currency"]
            _debug.logic(
                "order_amounts",
                order=order,
                untaxed=order.amount_untaxed,
                tax=order.amount_tax,
                total=order.amount_total,
            )
