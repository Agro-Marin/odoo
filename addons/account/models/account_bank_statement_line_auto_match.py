import logging

from odoo import api, fields, models, modules, service
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import SQL, float_compare

from ..tools import debug_log as dbg

_logger = logging.getLogger(__name__)

MAX_BARREN_CRON_ROUNDS = 3


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    @dbg.timed
    def _cron_try_auto_reconcile_statement_lines(
        self, batch_size=None, limit_time=0, company_id=None
    ):
        dbg.lifecycle.debug(
            "_cron_try_auto_reconcile_statement_lines on %s",
            dbg.rec(self),
        )
        if limit_time <= 0:
            # `limit_time_real_cron` DEFAULTS to -1, meaning "inherit
            # --limit-time-real" (itself 120), and reading the option directly
            # cannot see that: -1 fell through to the 180 default, so the cron
            # budgeted itself 50% longer than the server's own request limit.
            # The service helper resolves the inheritance.
            cron_limit_time = service.get_cron_real_time_budget() or -1
            limit_time = cron_limit_time if 0 < cron_limit_time < 180 else 180

        if limit_time and not batch_size:
            _logger.warning(
                "_cron_try_auto_reconcile_statement_lines called with "
                "limit_time=%r but batch_size=%r won't limit anything",
                limit_time,
                batch_size,
            )

        def compute_st_lines_to_reconcile(company_id=None):
            remaining_line_id = None
            limit = batch_size + 1 if batch_size else None
            domain = Domain(
                [
                    ("is_reconciled", "=", False),
                    ("cron_last_check", "=", False),
                ]
            )
            if company_id is not None:
                domain &= Domain(
                    self.env["account.reconcile.model"]._check_company_domain(
                        company_id
                    )
                )
            st_lines = self.search(domain, limit=limit, order="id")
            _logger.info(
                "_cron_try_auto_reconcile_statement_lines found %s statement lines",
                len(st_lines),
            )
            if batch_size and len(st_lines) > batch_size:
                remaining_line_id = st_lines[batch_size].id
                st_lines = st_lines[:batch_size]
            return st_lines, remaining_line_id

        def is_limit_time_exceeded():
            if batch_size and limit_time:
                return (
                    fields.Datetime.now().timestamp() - start_time.timestamp()
                    > limit_time
                )
            return False

        can_commit = not modules.module.current_test and not self.env.context.get(
            "import_file", False
        )
        remaining_line_id = None

        start_time = fields.Datetime.now()

        def rollback_and_retire(st_lines, exc):
            _logger.warning("Error while processing statement lines: %s", exc)
            retired = 0
            if not isinstance(exc, UserError) and can_commit:
                _logger.warning(
                    "_cron_try_auto_reconcile_statement_lines will rollback the cursor"
                )
                self.env.cr.rollback()
            for st_line in st_lines.exists():
                try:
                    with self.env.cr.savepoint():
                        st_line._try_auto_reconcile_statement_lines(
                            company_id=company_id
                        )
                except Exception as line_exc:
                    _logger.warning(
                        "_cron_try_auto_reconcile_statement_lines giving up on statement line %s: %s",
                        st_line.id,
                        line_exc,
                    )
                    st_line.cron_last_check = self.env.cr.now()
                    retired += 1
            return retired

        barren_rounds = 0

        while not is_limit_time_exceeded():
            st_lines = self.browse()
            try:
                st_lines, remaining_line_id = compute_st_lines_to_reconcile(
                    company_id=company_id
                )

                if not st_lines:
                    return

                with dbg.timer(self.env, "[automatch] cron batch x%d", len(st_lines)):
                    st_lines._try_auto_reconcile_statement_lines(company_id=company_id)
                barren_rounds = 0
            except Exception as e:
                if rollback_and_retire(st_lines, e):
                    barren_rounds = 0
                else:
                    barren_rounds += 1
                    if barren_rounds >= MAX_BARREN_CRON_ROUNDS:
                        _logger.error(
                            "_cron_try_auto_reconcile_statement_lines gave up after %s "
                            "rounds that retired no statement line; last error: %s",
                            barren_rounds,
                            e,
                        )
                        return

            if can_commit:
                self.env.cr.commit()

        if remaining_line_id:
            _logger.info(
                "_cron_try_auto_reconcile_statement_lines remaining line found (%s), the cron will be triggered again",
                remaining_line_id,
            )
            self.env.ref("account.auto_reconcile_bank_statement_line")._trigger()

    @api.model
    def _settles_residual(
        self, amount, residual, discounted, discount_date, date, tolerance
    ):
        if residual == amount:
            return True
        if discount_date and discounted == amount and date <= discount_date:
            return True
        return abs(amount - residual) <= tolerance * abs(residual)

    @dbg.timed
    def _invoice_matching_post_process(self, st_line, amls):
        candidate_amls = self.env["account.move.line"]
        tolerance = self._get_payment_tolerance()
        for aml in amls:
            readings = (
                (
                    aml.company_currency_id == st_line.currency_id,
                    aml.amount_residual,
                    aml.discount_balance,
                    st_line.amount,
                ),
                (
                    aml.currency_id == st_line.currency_id,
                    aml.amount_residual_currency,
                    aml.discount_amount_currency,
                    st_line.amount,
                ),
                (
                    aml.currency_id == st_line.foreign_currency_id,
                    aml.amount_residual_currency,
                    aml.discount_amount_currency,
                    st_line.amount_currency,
                ),
            )
            if any(
                applies
                and self._settles_residual(
                    amount,
                    residual,
                    discounted,
                    aml.discount_date,
                    st_line.date,
                    tolerance,
                )
                for applies, residual, discounted, amount in readings
            ):
                candidate_amls += aml

        prior_amls = candidate_amls.filtered(
            lambda aml: aml.invoice_date and aml.invoice_date <= st_line.date
        )
        dbg.logic.debug(
            "[automatch:%s] invoice matching: %d of %d settle within tolerance %s, %d dated before",
            st_line.id,
            len(candidate_amls),
            len(amls),
            tolerance,
            len(prior_amls),
        )
        if len(candidate_amls) == 1:
            return candidate_amls
        if len(prior_amls) == 1:
            return prior_amls
        return None

    @dbg.timed
    def _handle_reconciliation_matching_amount(
        self, st_move_ids, account_ids, remaining_st_line_ids, match_journal=False
    ):
        processed_st_line_ids = set()
        journal_clause = (
            SQL("AND aml.journal_id = st_line.journal_id") if match_journal else SQL("")
        )
        query = SQL(
            """
                SELECT st_line.id AS st_line_id,
                       ARRAY_AGG(aml.id ORDER BY aml.id ASC) AS all_aml_ids,
                       SUM(aml.amount_residual) AS total_residual
                  FROM account_bank_statement_line st_line
                  JOIN account_move_line aml
                    ON st_line.partner_id = aml.partner_id
                   AND aml.company_id = st_line.company_id
                   AND SIGN(st_line.amount) = SIGN(aml.balance)
                       %s
                  JOIN account_move move ON aml.move_id = move.id
                 WHERE st_line.partner_id IS NOT NULL
                   AND aml.move_id != ALL(%s)
                   AND aml.reconciled = false
                   AND aml.account_id = ANY(%s)
                   AND (aml.parent_state IN ('draft', 'posted'))
                   AND st_line.id = ANY(%s)
              GROUP BY st_line.id
        """,
            journal_clause,
            list(st_move_ids),
            list(account_ids),
            list(remaining_st_line_ids),
        )
        self.env.cr.execute(query)

        for st_line_id, all_aml_ids, total_residual in self.env.cr.fetchall():
            st_line = self.browse(st_line_id).with_prefetch(self._prefetch_ids)
            exact = (
                float_compare(
                    total_residual,
                    st_line.amount,
                    precision_rounding=st_line.currency_id.rounding,
                )
                == 0
            )
            dbg.logic.debug(
                "[automatch:%s] amount matching journal=%s: %d aml(s) residual=%s amount=%s exact=%s",
                st_line_id,
                match_journal,
                len(all_aml_ids or ()),
                total_residual,
                st_line.amount,
                exact,
            )
            if exact:
                st_line.set_line_bank_statement_line(all_aml_ids)
                _logger.info(
                    "try_auto_reconcile - match amount - st_line: %s set lines %s",
                    st_line.id,
                    all_aml_ids,
                )
            elif all_aml_ids:
                amls = self.env["account.move.line"].browse(all_aml_ids)
                candidate_amls = self._invoice_matching_post_process(st_line, amls)
                if candidate_amls:
                    st_line.set_line_bank_statement_line(candidate_amls.ids)
                    _logger.info(
                        "try_auto_reconcile - _invoice_matching_post_process - st_line: %s set lines %s",
                        st_line.id,
                        candidate_amls.ids,
                    )
            if st_line.currency_id.is_zero(st_line.amount_residual):
                processed_st_line_ids.add(st_line.id)
        return processed_st_line_ids

    @dbg.timed
    def _flush_before_matching_queries(self):
        self.env["account.account"].flush_model(["account_type", "active"])
        self.env["account.move"].flush_model(["date", "amount_total"])
        self.env["account.move.line"].flush_model(
            [
                "ref",
                "move_id",
                "move_name",
                "account_id",
                "partner_id",
                "company_id",
                "reconciled",
                "company_currency_id",
                "amount_residual",
                "currency_id",
                "amount_residual_currency",
                "discount_date",
                "discount_balance",
                "discount_amount_currency",
            ]
        )
        self.flush_recordset(
            [
                "move_id",
                "partner_id",
                "company_id",
                "currency_id",
                "amount",
                "foreign_currency_id",
                "amount_currency",
                "payment_ref",
            ]
        )
        self.env["account.payment"].flush_model(["move_id", "journal_id", "memo"])

    @dbg.timed
    def _try_auto_reconcile_statement_lines(self, company_id=None):
        st_move_ids = self.mapped("move_id").ids
        self.lock_for_update()

        try:
            domain = []
            if company_id is not None:
                domain = Domain(
                    self.env["account.reconcile.model"]._check_company_domain(
                        company_id
                    )
                )
            reco_models = self.env["account.reconcile.model"].search(domain)

            self._partner_mapping(reco_models)
            self._flush_before_matching_queries()

            account_ids = self._get_matchable_account_ids()
            dbg.pipeline.debug(
                "[automatch:%s] start: %d reco model(s), %d matchable account(s)",
                dbg.ids(self),
                len(reco_models),
                len(account_ids),
            )

            remaining_st_line_ids = set(self.ids) - self._end_to_end_uuid(
                st_move_ids, account_ids
            )
            dbg.pipeline.debug(
                "[automatch:%s] after end-to-end uuid: %d remaining",
                dbg.ids(self),
                len(remaining_st_line_ids),
            )
            if not remaining_st_line_ids:
                return

            outstanding_accounts = self._get_outstanding_payment_accounts()
            if outstanding_accounts:
                remaining_st_line_ids = self._match_outstanding_accounts(
                    st_move_ids, outstanding_accounts, remaining_st_line_ids
                )
                dbg.pipeline.debug(
                    "[automatch:%s] after outstanding accounts %s: %d remaining",
                    dbg.ids(self),
                    dbg.ids(outstanding_accounts),
                    len(remaining_st_line_ids),
                )

            account_ids = list(set(account_ids) - set(outstanding_accounts.ids))
            if not (remaining_st_line_ids and account_ids):
                return

            remaining_st_line_ids = self._match_payment_references(
                st_move_ids, account_ids, remaining_st_line_ids
            )
            dbg.pipeline.debug(
                "[automatch:%s] after payment references: %d remaining",
                dbg.ids(self),
                len(remaining_st_line_ids),
            )
            if not remaining_st_line_ids:
                return

            remaining_st_line_ids -= self._handle_reconciliation_matching_amount(
                st_move_ids, account_ids, remaining_st_line_ids
            )
            dbg.pipeline.debug(
                "[automatch:%s] after amount matching: %d remaining",
                dbg.ids(self),
                len(remaining_st_line_ids),
            )
            if not remaining_st_line_ids:
                return

            remaining_st_lines = self.browse(list(remaining_st_line_ids)).with_prefetch(
                self._prefetch_ids
            )
            reco_models._apply_reconcile_models(remaining_st_lines)
            _logger.info(
                "try_auto_reconcile - apply reco models - st_lines: %s - reco models %s",
                remaining_st_lines.ids,
                reco_models.ids,
            )
        finally:
            self.write({"cron_last_check": self.env.cr.now()})
