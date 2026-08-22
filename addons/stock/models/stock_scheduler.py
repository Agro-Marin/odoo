import logging
from itertools import batched

from odoo import api, fields, models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class StockScheduler(models.AbstractModel):
    _name = "stock.scheduler"
    _description = "Stock Scheduler"

    @api.model
    def run(self, use_new_cursor=False, company_id=False):
        try:
            self._run_tasks(use_new_cursor=use_new_cursor, company_id=company_id)
        except Exception:
            _logger.exception("Error during stock scheduler")
            raise

    @api.model
    def _get_tasks(self):
        return ["_refresh_orderpoints", "_replenish", "_run_quant_tasks"]

    @api.model
    def _get_tasks_to_do(self):
        return len(self._get_tasks())

    @api.model
    def _run_tasks(self, use_new_cursor=False, company_id=False):
        Cron = self.env["ir.cron"]
        if use_new_cursor:
            Cron._commit_progress(remaining=self._get_tasks_to_do())
        for task in self._get_tasks():
            getattr(self, task)(
                use_new_cursor=use_new_cursor,
                company_id=company_id,
            )
            if use_new_cursor:
                Cron._commit_progress(1)

    @api.model
    def _refresh_orderpoints(self, use_new_cursor=False, company_id=False):
        self.env["stock.warehouse.orderpoint"].search(
            self._get_orderpoint_domain(company_id=company_id, only_automatic=False),
        ).sudo()._refresh_stored_values()

    @api.model
    def _replenish(self, use_new_cursor=False, company_id=False):
        orderpoints = self.env["stock.warehouse.orderpoint"].search(
            self._get_orderpoint_domain(company_id=company_id),
        )
        orderpoints.sudo()._procure_orderpoint_confirm(
            use_new_cursor=use_new_cursor,
            company_id=company_id,
            raise_user_error=False,
        )
        self._reserve_due_moves(use_new_cursor=use_new_cursor, company_id=company_id)

    @api.model
    def _reserve_due_moves(self, use_new_cursor=False, company_id=False):
        moves_to_assign = self.env["stock.move"].search(
            self._get_moves_to_assign_domain(company_id),
            order="date_reservation, priority desc, date asc, id asc",
        )
        for moves_chunk in batched(moves_to_assign.ids, 1000, strict=False):
            self.env["stock.move"].browse(moves_chunk).sudo()._action_assign()
            if not use_new_cursor:
                continue
            remaining_time = self.env["ir.cron"]._commit_progress()
            _logger.info(
                "A batch of %d moves are assigned and committed",
                len(moves_chunk),
            )
            if not remaining_time:
                _logger.info(
                    "Stock scheduler ran out of time with moves left to assign;"
                    " the next run resumes from them.",
                )
                break

    @api.model
    def _run_quant_tasks(self, use_new_cursor=False, company_id=False):
        self.env["stock.quant"]._quant_tasks()

    @api.model
    def _get_orderpoint_domain(self, company_id=False, only_automatic=True):
        domain = Domain("product_id.active", "=", True)
        if only_automatic:
            domain &= Domain("trigger", "=", "auto")
        if company_id:
            domain &= Domain("company_id", "=", company_id)
        return domain

    @api.model
    def _get_moves_to_assign_domain(self, company_id):
        return Domain(
            [
                ("company_id", "=?", company_id),
                ("state", "in", ["confirmed", "partially_available"]),
                ("product_uom_qty", "!=", 0.0),
                "|",
                ("date_reservation", "<=", fields.Date.today()),
                ("picking_type_id.reservation_method", "=", "at_confirm"),
            ],
        )
