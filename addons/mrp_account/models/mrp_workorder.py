from odoo import _, fields, models


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    wc_analytic_account_line_ids = fields.Many2many(
        "account.analytic.line", "mrp_workorder_wc_analytic_rel", copy=False
    )

    def _analytic_line_fields(self):
        """Fields holding this work order's analytic lines.

        A module that adds a second set -- `project_mrp_account` adds the
        project's -- extends this instead of the teardown, the rename and the
        distribution guard separately.
        """
        return ["wc_analytic_account_line_ids"]

    def _get_analytic_lines(self):
        lines = self.env["account.analytic.line"]
        for field_name in self._analytic_line_fields():
            lines |= self[field_name]
        return lines

    def _compute_duration(self):
        res = super()._compute_duration()
        self._create_or_update_analytic_entry()
        return res

    def _inverse_duration(self):
        res = super()._inverse_duration()
        self._create_or_update_analytic_entry()
        return res

    def _unlink_analytic_entries(self):
        self.sudo()._get_analytic_lines().unlink()

    def action_cancel(self):
        self._unlink_analytic_entries()
        return super().action_cancel()

    def _prepare_analytic_line_values(self, account_field_values, amount, unit_amount):
        self.check_singleton()
        return {
            "name": _("[WC] %s", self.display_name),
            "amount": amount,
            **account_field_values,
            "unit_amount": unit_amount,
            "product_id": self.product_id.id,
            "product_uom_id": self.env.ref("uom.product_uom_hour").id,
            "company_id": self.company_id.id,
            "ref": self.production_id.name,
            "category": "manufacturing_order",
        }

    def _create_or_update_analytic_entry(self):
        """Charge each work order's machine cost to its analytic accounts.

        The hours and the rate are the ones `_get_cost` bills, not the work
        centre's current ones: a finished work order keeps the rate it ran at,
        and one costed as estimated is billed its expected duration. Reading
        `workcenter_id.costs_hour` and the raw `duration` instead let the
        analytic lines and the journal entry disagree -- re-rating a work centre
        after the fact restated the analytic side and left the accounting side
        alone.
        """
        for wo in self.sudo():
            if not wo.id:
                continue
            if wo._should_estimate_cost():
                hours = wo.duration_expected / 60.0
            else:
                hours = wo.duration / 60.0
            value = -hours * wo._get_costs_hour()
            wo._create_or_update_analytic_entry_for_record(value, hours)

    def _create_or_update_analytic_entry_for_record(self, value, hours):
        self.check_singleton()
        if self.workcenter_id.analytic_distribution or self._get_analytic_lines():
            wc_analytic_line_vals = self.env[
                "account.analytic.account"
            ]._perform_analytic_distribution(
                self.workcenter_id.analytic_distribution,
                value,
                hours,
                self.wc_analytic_account_line_ids,
                self,
            )
            if wc_analytic_line_vals:
                self.sudo().wc_analytic_account_line_ids += (
                    self.env["account.analytic.line"]
                    .sudo()
                    .create(wc_analytic_line_vals)
                )

    def unlink(self):
        self._unlink_analytic_entries()
        return super().unlink()
