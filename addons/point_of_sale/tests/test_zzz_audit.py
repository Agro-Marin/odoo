# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Regression tests for the point_of_sale full-module audit. Each test pins a fixed
# defect (correctness, sequence leak, slot validation, and two N+1 computes) and
# was authored red-green: it failed against the pre-fix code and passes after the fix.
import logging
from unittest.mock import patch

import odoo
from odoo.exceptions import UserError, ValidationError

from odoo.addons.point_of_sale.tests.common import TestPoSCommon

_logger = logging.getLogger(__name__)


@odoo.tests.tagged("post_install", "-at_install")
class TestAuditVerification(TestPoSCommon):
    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.product = self.create_product("AuditProd", self.categ_basic, 100, 50)

    # ---- C1 [HIGH] _process_saved_order raises for a NON-invoiced order when no invoice journal ----
    def test_C1_invoice_journal_blocks_normal_cash_order(self):
        self.config.invoice_journal_id = False
        self._start_pos_session(self.cash_pm1, 0)
        raised = None
        try:
            self._create_orders(
                [
                    {
                        "pos_order_lines_ui_args": [(self.product, 1)],
                        "payments": [(self.cash_pm1, 100)],
                        "is_invoiced": False,
                        "uuid": "audit-c1-0001",
                    },
                ]
            )
        except UserError as e:
            raised = e
        _logger.info("C1 result: raised=%r", raised)
        self.assertIsNone(
            raised,
            "BUG CONFIRMED: a normal non-invoiced cash order was rejected because "
            "the config has no invoice journal: %s" % raised,
        )

    # control: with an invoice journal set, the same order must work (rules out setup noise)
    def test_C1b_invoice_journal_present_normal_order_ok(self):
        self._start_pos_session(self.cash_pm1, 0)
        orders = self._create_orders(
            [
                {
                    "pos_order_lines_ui_args": [(self.product, 1)],
                    "payments": [(self.cash_pm1, 100)],
                    "is_invoiced": False,
                    "uuid": "audit-c1b-0001",
                },
            ]
        )
        self.assertEqual(len(orders), 1)

    # ---- C21 [LOW] unlink leaks order_seq_id / order_backend_seq_id ----
    def test_C21_unlink_sequence_leak(self):
        cfg = self.env["pos.config"].create({"name": "AuditSeqCfg"})
        seq_ids = (
            cfg.order_seq_id
            | cfg.order_backend_seq_id
            | cfg.order_line_seq_id
            | cfg.device_seq_id
        )
        self.assertEqual(len(seq_ids), 4, "expected 4 sequences created")
        seq_ids_list = seq_ids.ids
        cfg.unlink()
        survivors = self.env["ir.sequence"].browse(seq_ids_list).exists()
        _logger.info(
            "C21 surviving sequences after unlink: %s", survivors.mapped("name")
        )
        self.assertFalse(
            survivors,
            "BUG CONFIRMED: %d per-config sequence(s) leaked on unlink: %s"
            % (len(survivors), survivors.mapped("name")),
        )

    # ---- C22 [LOW] _check_slots rejects a valid attendance ending at 24:00 ----
    def test_C22_preset_midnight_slot(self):
        calendar = self.env["resource.calendar"].create({"name": "AuditCal"})
        raised = None
        try:
            self.env["pos.preset"].create(
                {
                    "name": "AuditPreset",
                    "resource_calendar_id": calendar.id,
                    "attendance_ids": [
                        (
                            0,
                            0,
                            {
                                "name": "Mon eve",
                                "dayofweek": "0",
                                "hour_from": 20.0,
                                "hour_to": 24.0,
                            },
                        )
                    ],
                }
            )
        except ValidationError as e:
            raised = e
        _logger.info("C22 result: raised=%r", raised)
        self.assertIsNone(
            raised,
            "BUG CONFIRMED: a valid 20:00-24:00 attendance was rejected: %s" % raised,
        )

    def _make_configs_with_sessions(self, n):
        sessions = self.env["pos.session"]
        for i in range(n):
            journal = self.env["account.journal"].create(
                {
                    "name": "AuditCash%d" % i,
                    "code": "ACSH%d" % i,
                    "type": "cash",
                    "company_id": self.env.company.id,
                }
            )
            cash_pm = self.env["pos.payment.method"].create(
                {
                    "name": "AuditCashPM%d" % i,
                    "journal_id": journal.id,
                    "receivable_account_id": self.pos_receivable_cash.id,
                    "company_id": self.env.company.id,
                }
            )
            cfg = self.env["pos.config"].create(
                {
                    "name": "AuditCfg%d" % i,
                    "payment_method_ids": [(6, 0, cash_pm.ids)],
                }
            )
            sessions |= self.env["pos.session"].create(
                {
                    "config_id": cfg.id,
                    "user_id": self.env.uid,
                }
            )
        sessions.invalidate_recordset()
        return sessions

    # ---- P18a [MED] _compute_cash_balance issues one _read_group per session (N+1) ----
    def test_P18a_cash_balance_n_plus_1(self):
        sessions = self._make_configs_with_sessions(4)
        calls = {"n": 0}
        real = type(self.env["pos.payment"])._read_group

        def counting(self2, *a, **k):
            calls["n"] += 1
            return real(self2, *a, **k)

        with patch.object(type(self.env["pos.payment"]), "_read_group", counting):
            # touch a non-stored cash compute field on the whole recordset at once
            sessions.mapped("cash_register_balance_end")
        _logger.info(
            "P18a _read_group calls for %d sessions: %d", len(sessions), calls["n"]
        )
        self.assertLessEqual(
            calls["n"],
            1,
            "N+1 CONFIRMED: %d pos.payment._read_group calls for %d sessions "
            "(expected batched into <=1)" % (calls["n"], len(sessions)),
        )

    # ---- P18b [MED] _compute_picking_count issues 2 queries per session (N+1) ----
    def test_P18b_picking_count_n_plus_1(self):
        sessions = self._make_configs_with_sessions(4)
        calls = {"search": 0, "search_count": 0}
        Picking = type(self.env["stock.picking"])
        real_search = Picking.search
        real_count = Picking.search_count

        def c_search(self2, *a, **k):
            calls["search"] += 1
            return real_search(self2, *a, **k)

        def c_count(self2, *a, **k):
            calls["search_count"] += 1
            return real_count(self2, *a, **k)

        with (
            patch.object(Picking, "search", c_search),
            patch.object(Picking, "search_count", c_count),
        ):
            sessions.mapped("picking_count")
            sessions.mapped("failed_pickings")
        total = calls["search"] + calls["search_count"]
        _logger.info("P18b picking queries for %d sessions: %r", len(sessions), calls)
        self.assertLessEqual(
            total,
            2,
            "N+1 CONFIRMED: %d stock.picking search/search_count calls for %d sessions"
            % (total, len(sessions)),
        )
