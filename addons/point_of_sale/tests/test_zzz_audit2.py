import logging

import odoo
from odoo.exceptions import ValidationError

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
            totals["qty"],
            6.0,
            "BUG CONFIRMED: grand total qty deduplicated identical rows "
            "(got %s, expected 6.0)" % totals["qty"],
        )
        self.assertEqual(
            totals["total"],
            60.0,
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
        orders_map = self._create_orders(
            [
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
            ]
        )
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
            order_a.has_deleted_line,
            order_b.has_deleted_line,
        )
        self.assertTrue(
            order_a.has_deleted_line,
            "BUG CONFIRMED: batch write dropped has_deleted_line for order A "
            "because a sibling order mutated the shared vals dict",
        )
        self.assertTrue(order_b.has_deleted_line)

    # ---- R4 a tax used by a non-posted POS order must NOT be deletable ----
    def test_R4_tax_not_deletable_when_open_pos_order_uses_it(self):
        # This test originally asserted the opposite (that such a tax stays
        # deletable), on the premise that `is_used` should reflect *finalized*
        # accounting only and that an open-session order "degrades gracefully"
        # when its tax disappears. That premise is wrong:
        #
        # - It does not degrade gracefully. The tax has already been collected
        #   from the customer at the till; deleting the record cascades the
        #   `account_tax_pos_order_line_rel` rows away, so the session-closing
        #   entry is computed without a tax that was actually charged — a silent
        #   fiscal under-declaration.
        # - It was internally inconsistent: `account.tax.write` (in this module)
        #   already refuses to *modify* a tax carried by a non-closed POS order.
        #   Deletion is strictly more destructive than modification, so allowing
        #   it while blocking modification is incoherent.
        # - Upstream 19.0 ships the `_hook_compute_is_used` override that makes
        #   this tax used, and deliberately settled the question in
        #   a2e47c4b0f1 ("block deletion of group of taxes in use"), which fixed
        #   the POS flow test to *archive* the tax instead of deleting it.
        #
        # So the guarded behaviour is the correct one, and this test now pins it:
        # the tax is `is_used`, `unlink()` raises, and archiving is the way out.
        self._start_pos_session(self.cash_pm1, 0)
        tax = self.env["account.tax"].create(
            {
                "name": "AuditTaxR4",
                "amount": 10.0,
                "amount_type": "percent",
                "type_tax_use": "sale",
            }
        )
        product = self.create_product(
            "AuditTaxProdR4", self.categ_basic, 100, 50, tax_ids=tax.ids
        )
        self._create_orders(
            [
                {
                    "pos_order_lines_ui_args": [(product, 1)],
                    "payments": [(self.cash_pm1, 110)],
                    "uuid": "audit-r4-0001",
                },
            ]
        )
        tax.invalidate_model(fnames=["is_used"])
        self.assertTrue(
            tax.is_used,
            "a tax carried by an open-session POS order must count as used, so "
            "that it cannot be deleted out from under the closing entry",
        )
        with self.assertRaises(ValidationError):
            tax.unlink()
        self.assertTrue(tax.exists())

        # Archiving is the supported escape hatch: it keeps the record (and the
        # closing entry's tax) intact while removing the tax from new orders.
        tax.active = False
        self.assertFalse(tax.active)
