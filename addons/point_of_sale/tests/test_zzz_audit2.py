import logging

import odoo

from odoo.addons.point_of_sale.tests.common import TestPoSCommon

_logger = logging.getLogger(__name__)


@odoo.tests.tagged("post_install", "-at_install")
class TestAuditVerification2(TestPoSCommon):
    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.product = self.create_product("AuditProd2", self.categ_basic, 100, 50)

    # ---- R1 [MED] sale-details grand total dropped value-identical product rows ----
    def test_R1_sale_details_grand_total_no_dedup(self):
        report = self.env["report.point_of_sale.report_saledetails"]
        # Two DISTINCT sale rows that happen to carry identical dict values
        # (same product, price, discount, qty, totals). The old code keyed the
        # grand total on tuple(sorted(product.items())) and collapsed them.
        row = {
            "product_id": 1,
            "product_name": "Widget",
            "barcode": False,
            "quantity": 3.0,
            "price_unit": 10.0,
            "discount": 0.0,
            "uom": "Units",
            "total_paid": 30.0,
            "base_amount": 30.0,
            "combo_products_label": False,
        }
        categories = [
            {"name": "Cat A", "products": [dict(row)]},
            {"name": "Cat B", "products": [dict(row)]},
        ]
        _, totals = report._get_total_and_qty_per_category(categories)
        _logger.info("R1 grand totals: %r", totals)
        self.assertEqual(
            totals["qty"], 6.0,
            "BUG CONFIRMED: grand total qty deduplicated identical rows "
            "(got %s, expected 6.0)" % totals["qty"],
        )
        self.assertEqual(
            totals["total"], 60.0,
            "BUG CONFIRMED: grand total amount deduplicated identical rows "
            "(got %s, expected 60.0)" % totals["total"],
        )

    # ---- R2 [LOW] pos.preset slot usage used defaultdict(int) while storing lists ----
    def test_R2_preset_slot_usage_lists(self):
        preset = self.env["pos.preset"].create({"name": "AuditPreset2"})
        usage = preset._compute_slots_usage()
        _logger.info("R2 empty usage: %r", usage)
        # With no orders it is empty; a missing key must default to a list, not 0.
        self.assertEqual(usage["2099-01-01 12:00:00"], [])
        self.assertIsInstance(usage["2099-01-01 12:00:00"], list)

    # ---- R3 [MED] pos.order.write leaked per-order derivations through shared vals ----
    def test_R3_batch_write_per_record_has_deleted_line(self):
        self._start_pos_session(self.cash_pm1, 0)
        orders_map = self._create_orders([
            {
                "pos_order_lines_ui_args": [(self.product, 1)],
                "payments": [(self.cash_pm1, 100)],
                "uuid": "audit-r3-a",
            },
            {
                "pos_order_lines_ui_args": [(self.product, 1)],
                "payments": [(self.cash_pm1, 100)],
                "uuid": "audit-r3-b",
            },
        ])
        order_a = orders_map["audit-r3-a"]
        order_b = orders_map["audit-r3-b"]
        order_a.has_deleted_line = False
        order_b.has_deleted_line = True
        # Batch write True to both. Old code: order_b's iteration did
        # `del vals["has_deleted_line"]` on the shared dict, so order_a never
        # received the write and stayed False.
        (order_a | order_b).write({"has_deleted_line": True})
        _logger.info(
            "R3 has_deleted_line a=%s b=%s",
            order_a.has_deleted_line, order_b.has_deleted_line,
        )
        self.assertTrue(
            order_a.has_deleted_line,
            "BUG CONFIRMED: batch write dropped has_deleted_line for order A "
            "because a sibling order mutated the shared vals dict",
        )
        self.assertTrue(order_b.has_deleted_line)

    # ---- R4 [MED] a tax used only by a non-posted POS order blocked deletion ----
    def test_R4_tax_deletable_when_only_open_pos_order(self):
        # The removed pos `_hook_compute_is_used` override marked a tax "used"
        # whenever ANY pos.order.line referenced it, including orders in an open
        # (not-yet-posted) session — wrongly blocking tax deletion. Finalized
        # accounting is still protected by the base account.move.line check
        # (exercised by test_tax_is_used_when_in_transactions, which closes the
        # session).
        self._start_pos_session(self.cash_pm1, 0)
        tax = self.env["account.tax"].create({
            "name": "AuditTaxR4",
            "amount": 10.0,
            "amount_type": "percent",
            "type_tax_use": "sale",
        })
        product = self.create_product(
            "AuditTaxProdR4", self.categ_basic, 100, 50, tax_ids=tax.ids
        )
        self._create_orders([
            {
                "pos_order_lines_ui_args": [(product, 1)],
                "payments": [(self.cash_pm1, 110)],
                "uuid": "audit-r4-0001",
            },
        ])
        tax.invalidate_model(fnames=["is_used"])
        self.assertFalse(
            tax.is_used,
            "BUG CONFIRMED: a tax referenced only by an open-session (non-posted) "
            "POS order was marked used, blocking its deletion",
        )
        # And it must actually be deletable (was raising ValidationError).
        tax.unlink()
        self.assertFalse(tax.exists())
