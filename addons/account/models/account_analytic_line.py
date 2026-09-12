from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..tools import debug_log as dbg


class AccountAnalyticLine(models.Model):
    _inherit = "account.analytic.line"
    _description = "Analytic Line"

    product_id = fields.Many2one(
        "product.product",
        string="Product",
        check_company=True,
        index="btree_not_null",
    )
    product_category = fields.Many2one(
        related="product_id.categ_id",
    )
    general_account_id = fields.Many2one(
        "account.account",
        string="Financial Account",
        ondelete="restrict",
        check_company=True,
        compute="_compute_general_account_id",
        store=True,
        readonly=False,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Financial Journal",
        check_company=True,
        readonly=True,
        related="move_line_id.journal_id",
        store=True,
    )
    partner_id = fields.Many2one(
        readonly=False,
        compute="_compute_partner_id",
        store=True,
    )
    move_line_id = fields.Many2one(
        "account.move.line",
        string="Journal Item",
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    code = fields.Char(size=8)
    ref = fields.Char(string="Ref.")
    category = fields.Selection(
        selection_add=[("invoice", "Customer Invoice"), ("vendor_bill", "Vendor Bill")]
    )

    @api.constrains("move_line_id", "general_account_id")
    @dbg.timed
    def _check_general_account_id(self):
        for line in self:
            if (
                line.move_line_id
                and line.general_account_id != line.move_line_id.account_id
            ):
                raise ValidationError(
                    _("The journal item is not linked to the correct financial account")
                )

    @api.model_create_multi
    @dbg.timed
    def create(self, vals_list):
        dbg.lifecycle.debug(
            "create %s: %d vals, keys=%s",
            self._name,
            len(vals_list),
            dbg.vals_keys(vals_list),
        )
        analytic_lines = super().create(vals_list)
        analytic_lines.move_line_id._update_analytic_distribution()
        return analytic_lines

    @dbg.timed
    def write(self, vals):
        dbg.lifecycle.debug("write on %s: keys=%s", dbg.rec(self), dbg.keys(vals))
        affected_move_lines = self.move_line_id
        res = super().write(vals)
        if any(
            field in vals
            for field in ["amount", "move_line_id"] + self._get_plan_fnames()
        ):
            if "move_line_id" in vals:
                affected_move_lines |= self.move_line_id
            affected_move_lines._update_analytic_distribution()
        return res

    @dbg.timed
    def unlink(self):
        dbg.lifecycle.debug("unlink %s", dbg.rec(self))
        affected_move_lines = self.move_line_id
        res = super().unlink()
        affected_move_lines._update_analytic_distribution()
        return res

    @api.depends("move_line_id")
    def _compute_general_account_id(self):
        for line in self:
            line.general_account_id = line.move_line_id.account_id

    @api.depends("move_line_id.partner_id")
    def _compute_partner_id(self):
        for line in self:
            line.partner_id = line.move_line_id.partner_id or line.partner_id

    @api.onchange("product_id", "product_uom_id", "unit_amount", "currency_id")
    def on_change_unit_amount(self):
        if not self.product_id:
            return {}

        prod_accounts = self.product_id.product_tmpl_id.with_company(
            self.company_id
        )._get_product_accounts()
        unit = self.product_uom_id
        account = prod_accounts["expense"]
        if not unit:
            unit = self.product_id.uom_id

        amount_unit = self.product_id._compute_price("standard_price", uom=unit)[
            self.product_id.id
        ]
        amount = amount_unit * self.unit_amount or 0.0
        result = (
            self.currency_id.round(amount) if self.currency_id else round(amount, 2)
        ) * -1
        self.amount = result
        self.general_account_id = account
        self.product_uom_id = unit
        return None

    @api.model
    def view_header_get(self, view_id, view_type):
        if self.env.context.get("account_id"):
            return _(
                "Entries: %(account)s",
                account=self.env["account.analytic.account"]
                .browse(self.env.context["account_id"])
                .name,
            )
        return super().view_header_get(view_id, view_type)
