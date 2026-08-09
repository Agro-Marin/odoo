# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Contracts the point of sale relies on but never stated.

Each test here pins one defect that was latent rather than user-visible: a
method that mutated its caller's dict, a fallback that could only ever raise, a
divisor with no guard, a loop that returned out of itself. They cost nothing to
keep and they are what makes the next refactor safe.

Authored red-green: every test below failed against the pre-fix code.
"""

import json
import logging

from odoo import fields
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestPosRobustness(CommonPosTest):
    def setUp(self):
        super().setUp()
        self.pos_config_usd.open_ui()
        self.session = self.pos_config_usd.current_session_id
        self.product = self.env["product.product"].search(
            [("available_in_pos", "=", True)], limit=1
        )

    def _order(self, **vals):
        return self.env["pos.order"].create(
            {
                "session_id": self.session.id,
                "amount_tax": 0,
                "amount_total": 0,
                "amount_paid": 0,
                "amount_return": 0,
                **vals,
            }
        )

    # ------------------------------------------------------------------
    # write()/create() must not rewrite the dict the caller handed them.
    # ------------------------------------------------------------------
    def test_config_write_leaves_the_caller_dict_alone(self):
        vals = {"is_order_printer": False}
        self.pos_config_usd.write(vals)
        self.assertEqual(vals, {"is_order_printer": False})

    def test_config_write_does_not_leak_between_records(self):
        """The concrete harm: one dict reused for two shops."""
        printer = self.env["pos.printer"].create(
            {"name": "Kitchen", "proxy_ip": "10.0.0.1"}
        )
        for config in (self.pos_config_usd, self.pos_config_eur):
            config.write(
                {"is_order_printer": True, "printer_ids": [Command.link(printer.id)]}
            )
        vals = {"iface_big_scrollbars": True}
        self.pos_config_usd.write(vals)
        self.pos_config_eur.write(vals)
        self.assertIn(printer, self.pos_config_eur.printer_ids)

    def test_order_create_leaves_the_caller_dict_alone(self):
        vals = {
            "session_id": self.session.id,
            "amount_tax": 0,
            "amount_total": 0,
            "amount_paid": 0,
            "amount_return": 0,
        }
        expected = dict(vals)
        self.env["pos.order"].create(vals)
        self.assertEqual(vals, expected)

    # ------------------------------------------------------------------
    # An order belongs to a session. Say so, do not raise KeyError.
    # ------------------------------------------------------------------
    def test_order_without_a_session_is_refused_by_name(self):
        with self.assertRaises(UserError):
            self.env["pos.order"].create({"amount_tax": 0, "amount_total": 0})

    # ------------------------------------------------------------------
    # The four per-config counters must be distinguishable.
    # ------------------------------------------------------------------
    def test_config_sequences_have_distinct_codes(self):
        config = self.pos_config_usd
        codes = [
            config.order_seq_id.code,
            config.order_backend_seq_id.code,
            config.order_line_seq_id.code,
            config.device_seq_id.code,
        ]
        self.assertEqual(len(set(codes)), 4, codes)

    def test_order_line_without_a_sequence_names_the_problem(self):
        """The fallback used to reach for a sequence code nothing creates, so
        `name` came back False for a required Char and the insert died on a
        NOT NULL violation naming only the column."""
        order = self._order()
        self.pos_config_usd.sudo().order_line_seq_id = False
        with self.assertRaises(UserError):
            self.env["pos.order.line"].create(
                {
                    "order_id": order.id,
                    "product_id": self.product.id,
                    "qty": 1,
                    "price_unit": 0,
                    "price_subtotal": 0,
                    "price_subtotal_incl": 0,
                }
            )

    # ------------------------------------------------------------------
    # `filter_local_data` is a public RPC over a caller-chosen model list.
    # ------------------------------------------------------------------
    def test_filter_local_data_on_a_model_without_active(self):
        order = self._order()
        self.assertNotIn("active", self.env["pos.order"]._fields)
        result = self.session.filter_local_data({"pos.order": [order.id]})
        self.assertEqual(result["pos.order"], [])

    def test_filter_local_data_reports_deleted_records(self):
        order = self._order()
        order_id = order.id
        order.unlink()
        result = self.session.filter_local_data({"pos.order": [order_id]})
        self.assertEqual(result["pos.order"], [order_id])

    def test_filter_local_data_reports_archived_records(self):
        """Control: the `active` path must keep working."""
        template = self.env["product.template"].create(
            {"name": "Archived probe", "available_in_pos": True}
        )
        template.active = False
        result = self.session.filter_local_data({"product.template": [template.id]})
        self.assertEqual(result["product.template"], [template.id])

    # ------------------------------------------------------------------
    # A zero-quantity line is legal, so it must not be a divisor.
    # ------------------------------------------------------------------
    def test_total_cost_survives_a_zero_quantity_refunded_line(self):
        order = self._order(shipping_date=fields.Date.today())
        zero_line = self.env["pos.order.line"].create(
            {
                "order_id": order.id,
                "product_id": self.product.id,
                "qty": 0,
                "price_unit": 0,
                "price_subtotal": 0,
                "price_subtotal_incl": 0,
                "total_cost": 0,
            }
        )
        refund_line = self.env["pos.order.line"].create(
            {
                "order_id": order.id,
                "product_id": self.product.id,
                "qty": -1,
                "price_unit": 0,
                "price_subtotal": 0,
                "price_subtotal_incl": 0,
                "refunded_orderline_id": zero_line.id,
            }
        )
        # Must not raise ZeroDivisionError whatever the moves look like.
        refund_line._compute_total_cost(self.env["stock.move"])
        self.assertTrue(refund_line.is_total_cost_computed)

    # ------------------------------------------------------------------
    # A printed order's payments are settled: refuse before writing.
    # ------------------------------------------------------------------
    def test_printed_order_refuses_a_new_payment(self):
        cash_pm = self.session.payment_method_ids.filtered("is_cash_count")[:1]
        order = self._order(state="paid", nb_print=1)
        with self.assertRaises(UserError):
            order.write(
                {
                    "payment_ids": [
                        Command.create(
                            {
                                "payment_method_id": cash_pm.id,
                                "amount": 5,
                                "payment_status": "done",
                            }
                        )
                    ]
                }
            )
        self.assertFalse(order.payment_ids)

    # ------------------------------------------------------------------
    # The preparation-change merge is single-record and says so.
    # ------------------------------------------------------------------
    def test_preparation_change_is_single_record(self):
        first = self._order()
        second = self._order()
        with self.assertRaises(ValueError):
            (first | second)._keep_newest_preparation_change({})

    def test_preparation_change_keeps_the_newer_payload(self):
        order = self._order()
        order.last_order_preparation_change = json.dumps(
            {"metadata": {"serverDate": "2030-01-01 00:00:00"}}
        )
        vals = {
            "last_order_preparation_change": json.dumps(
                {"metadata": {"serverDate": "2020-01-01 00:00:00"}}
            )
        }
        order._keep_newest_preparation_change(vals)
        self.assertEqual(
            json.loads(vals["last_order_preparation_change"])["metadata"]["serverDate"],
            "2030-01-01 00:00:00",
        )

    # ------------------------------------------------------------------
    # Edit tracking writes one message per order, not one per line.
    # ------------------------------------------------------------------
    def test_deleting_lines_posts_one_message(self):
        self.pos_config_usd.order_edit_tracking = True
        order = self._order()
        for _i in range(3):
            self.env["pos.order.line"].create(
                {
                    "order_id": order.id,
                    "product_id": self.product.id,
                    "qty": 1,
                    "price_unit": 0,
                    "price_subtotal": 0,
                    "price_subtotal_incl": 0,
                }
            )
        before = len(order.message_ids)
        order.lines.unlink()
        self.assertEqual(len(order.message_ids) - before, 1)
        self.assertTrue(order.has_deleted_line)

    # ------------------------------------------------------------------
    # `read_pos_data` answers the same shape with or without a config.
    # ------------------------------------------------------------------
    def test_read_pos_data_without_a_config(self):
        order = self._order()
        with_config = order.read_pos_data([], self.pos_config_usd)
        without_config = order.read_pos_data([], False)
        self.assertEqual(set(with_config), set(without_config))
        self.assertTrue(all(value == [] for value in without_config.values()))

    # ------------------------------------------------------------------
    # `_IS_VAT` follows the config's company.
    # ------------------------------------------------------------------
    def test_is_vat_follows_the_config_company(self):
        config = self.pos_config_usd
        config.company_id.country_id = self.env.ref("base.be")
        payload = config._load_pos_data_read(config, config)
        self.assertTrue(payload[0]["_IS_VAT"])
        config.company_id.country_id = self.env.ref("base.us")
        payload = config._load_pos_data_read(config, config)
        self.assertFalse(payload[0]["_IS_VAT"])
