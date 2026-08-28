from collections import defaultdict

from odoo import Command, _, fields, models


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    extra_cost = fields.Float(copy=False, string="Extra Unit Cost")
    wip_move_ids = fields.Many2many(
        "account.move",
        "wip_move_production_rel",
        "production_id",
        "move_id",
        copy=False,
    )
    wip_move_count = fields.Count("wip_move_ids", "WIP Journal Entry Count")

    def write(self, vals):
        res = super().write(vals)
        if not vals.get("name"):
            return res
        for production in self.sudo():
            production.move_raw_ids.analytic_account_line_ids.ref = (
                production.display_name
            )
            for workorder in production.workorder_ids:
                # Every set of analytic lines, not just the project one: naming
                # a single field left the work centre's own lines carrying the
                # order's old name for good.
                analytic_lines = workorder._get_analytic_lines()
                analytic_lines.ref = production.display_name
                analytic_lines.name = _("[WC] %s", workorder.display_name)
        return res

    def action_view_move_wip(self):
        self.ensure_one()
        action = {
            "res_model": "account.move",
            "type": "ir.actions.act_window",
        }
        if len(self.wip_move_ids) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": self.wip_move_ids.id,
                }
            )
        else:
            action.update(
                {
                    "name": _("WIP Entries of %s", self.name),
                    "domain": [("id", "in", self.wip_move_ids.ids)],
                    "view_mode": "list,form",
                    "views": [(self.env.ref("account.view_move_tree").id, "list")],
                }
            )
        return action

    def _cal_price(self, consumed_moves):
        """Price the finished move and every byproduct that carries a cost share.

        `_get_value_from_production` values a production move at
        ``quantity * price_unit`` and nothing else, so a move this method leaves
        unpriced enters stock at zero. Every move with a share is therefore
        priced here, in both cost methods.
        """
        super()._cal_price(consumed_moves)

        finished_move = self.move_finished_ids.filtered(
            lambda x: (
                x.product_id == self.product_id
                and x.state not in ("done", "cancel")
                and x.quantity > 0
            )
        )
        if not finished_move:
            return True

        quantity = sum(
            move.product_uom_id._compute_quantity(move.quantity, move.product_id.uom_id)
            for move in finished_move
        )
        total_cost = (
            sum(move.value for move in consumed_moves)
            + self.workorder_ids._get_cost()
            + self.extra_cost * quantity
        )

        byproduct_moves = self.move_byproduct_ids.filtered(
            lambda m: (
                m.state not in ("done", "cancel") and m.quantity > 0 and m.cost_share
            )
        )
        priced_byproducts = byproduct_moves.filtered(
            lambda m: m.product_id.cost_method in ("fifo", "average")
        )
        currency = self.company_id.currency_id
        # A byproduct valued at standard enters stock at its own price whatever
        # the order cost, so its share is a variance rather than a slice of
        # `total_cost` -- and only the moves priced *from* the total have to add
        # back up to it.
        standard_byproducts = byproduct_moves - priced_byproducts
        for byproduct in standard_byproducts:
            byproduct.price_unit = byproduct.product_id.standard_price
        unpriced_share = sum(standard_byproducts.mapped("cost_share"))
        shared_value = currency.round(total_cost * (1 - unpriced_share / 100))
        for byproduct in priced_byproducts:
            value = currency.round(total_cost * byproduct.cost_share / 100)
            shared_value -= value
            byproduct.price_unit = value / byproduct.product_uom_id._compute_quantity(
                byproduct.quantity, byproduct.product_id.uom_id
            )

        if self.product_id.cost_method not in ("fifo", "average"):
            finished_move.price_unit = self.product_id.standard_price
            return True
        finished_move.ensure_one()
        # Derived by subtraction, not from its own share: rounding each unit
        # price on its own left a cent in the production account per order.
        finished_move.price_unit = shared_value / quantity
        return True

    def _get_backorder_mo_vals(self):
        res = super()._get_backorder_mo_vals()
        res["extra_cost"] = self.extra_cost
        return res

    def _get_labour_amounts_per_account(self, product_accounts):
        """Labour to charge per expense account, and the work orders behind each.

        The per-account amounts are rounded so their sum is exactly
        ``currency.round(total labour)`` -- the same figure `_cal_price`
        capitalises into the finished move. Rounding each account on its own
        leaves a residual that never clears out of the production account.
        """
        self.ensure_one()
        currency = self.company_id.currency_id
        raw_amounts = defaultdict(float)
        workorders = defaultdict(self.env["mrp.workorder"].browse)
        for workorder in self.workorder_ids:
            account = (
                workorder.workcenter_id.expense_account_id
                or product_accounts["expense"]
            )
            raw_amounts[account] += workorder._get_cost()
            workorders[account] |= workorder

        total = currency.round(sum(raw_amounts.values()))
        amounts = {
            account: currency.round(amount) for account, amount in raw_amounts.items()
        }
        residual = total - sum(amounts.values())
        if amounts and not currency.is_zero(residual):
            heaviest = max(amounts, key=lambda account: abs(amounts[account]))
            amounts[heaviest] = currency.round(amounts[heaviest] + residual)
        return total, amounts, workorders

    def _post_labour(self):
        for mo in self:
            mo = mo.with_company(mo.company_id)
            production_location = mo.product_id.property_stock_production
            if (
                mo.product_id.valuation != "real_time"
                or not production_location.valuation_account_id
            ):
                continue

            if mo.workorder_ids.time_ids.account_move_line_id:
                continue

            product_accounts = mo.product_id.product_tmpl_id._get_product_accounts()
            workcenter_cost, labour_amounts, workorders = (
                mo._get_labour_amounts_per_account(product_accounts)
            )
            if mo.company_id.currency_id.is_zero(workcenter_cost):
                continue

            desc = _("%s - Labour", mo.name)
            charged = list(labour_amounts.items())
            account_move = (
                mo.env["account.move"]
                .sudo()
                .create(
                    {
                        "journal_id": product_accounts["stock_journal"].id,
                        "date": fields.Date.context_today(mo),
                        "ref": desc,
                        "move_type": "entry",
                        "line_ids": [
                            Command.create(
                                {
                                    "name": desc,
                                    "ref": desc,
                                    "balance": -amount,
                                    "account_id": account.id,
                                }
                            )
                            for account, amount in charged
                        ]
                        + [
                            Command.create(
                                {
                                    "name": desc,
                                    "ref": desc,
                                    "balance": workcenter_cost,
                                    "account_id": production_location.valuation_account_id.id,
                                }
                            )
                        ],
                    }
                )
            )
            # The expense line for a work centre whose account *is* the
            # production account is indistinguishable from the balancing line by
            # account, so the two are paired positionally -- by creation order,
            # which is the order `line_ids` was built in above.
            expense_lines = account_move.line_ids.sorted("id")[: len(charged)]
            for line, (account, _amount) in zip(expense_lines, charged, strict=True):
                workorders[account].time_ids.write({"account_move_line_id": line.id})
            account_move._post()

    def _post_inventory(self, cancel_backorder=False):
        res = super()._post_inventory(cancel_backorder=cancel_backorder)
        self.filtered(lambda mo: mo.state == "done")._post_labour()
        return res
