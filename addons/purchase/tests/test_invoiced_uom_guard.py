# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("-at_install", "post_install")
class TestInvoicedUomGuard(AccountTestInvoicingCommon):
    """Posting-boundary guard for the leniently-computed invoiced qty.

    ``qty_invoiced`` converts bill lines into the order-line UoM through
    ``_compute_quantity_reconcile``, which degrades (returns the quantity
    unconverted) instead of raising, so a stored compute replayed over the
    whole table never aborts on one legacy row.  That degraded quantity must
    never silently size the next bill: billing again must fail loud.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        # A UoM in an unrelated category (Working Time), so it shares no common
        # reference with the product's Units UoM.
        cls.uom_incompatible = cls.env.ref("uom.product_uom_hour")
        cls.product = cls.env["product.product"].create(
            {
                "name": "Guarded billed product",
                "type": "service",
                "bill_policy": "ordered",
                "purchase_ok": True,
                "standard_price": 100.0,
                "uom_id": cls.uom_unit.id,
                "supplier_taxes_id": [Command.clear()],
            },
        )

    def _confirmed_po(self, qty=10):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": qty,
                            "price_unit": 100,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                ],
            },
        )
        po.action_confirm()
        return po

    def _post_partial_bill(self, po, qty):
        """Bill ``qty`` of ``po`` and post it, leaving a remainder to bill."""
        bill = po.create_invoice()
        bill.invoice_date = "2026-01-01"
        bill.invoice_line_ids.quantity = qty
        bill.action_post()
        return bill

    def _corrupt_bill_line_uom(self, bill):
        """Record a posted bill line in an inconvertible UoM.

        The ORM forbids editing a posted line, so write at the SQL level to
        reproduce data that predates the guard.
        """
        self.env.cr.execute(
            "UPDATE account_move_line SET product_uom_id = %s WHERE id = %s",
            (self.uom_incompatible.id, bill.invoice_line_ids.id),
        )
        self.env.invalidate_all()

    def _draft_bill(self, uom, qty=4):
        """A standalone draft bill line, not yet linked to any order line.

        ``_where_am_line`` only surfaces bill lines with no row in
        ``account_move_line_purchase_order_line_rel``, so this is what the
        matching screen offers for pairing.
        """
        return self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-01-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": qty,
                            "price_unit": 100,
                            "product_uom_id": uom.id,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                ],
            },
        )

    def _match_rows(self):
        """The matching-screen rows for the fixture partner and product.

        ``purchase.bill.line.match`` is an SQL view (``_auto=False``) over
        ``purchase_order_line`` and ``account_move_line``, so records still held
        in the ORM cache are invisible to it — flush before querying, or the
        search comes back empty and ``action_match_lines`` raises on its own
        "select at least one Purchase Order line" guard instead of ours.
        """
        self.env.flush_all()
        rows = self.env["purchase.bill.line.match"].search(
            [
                ("partner_id", "=", self.partner_a.id),
                ("product_id", "=", self.product.id),
            ],
        )
        # Precondition, not a behaviour assertion: without both sides the
        # action short-circuits before reaching the UoM guard, which would make
        # an `assertRaises(UserError)` pass for the wrong reason.
        self.assertTrue(rows.pol_id, "The order line must be offered for matching")
        self.assertTrue(rows.aml_id, "The bill line must be offered for matching")
        return rows

    def test_fixture_uoms_share_no_reference(self):
        """Sanity: the pair really is inconvertible, so the rest is meaningful."""
        self.assertFalse(self.uom_unit._has_common_reference(self.uom_incompatible))

    def test_incompatible_invoiced_uom_degrades_while_browsing(self):
        po = self._confirmed_po()
        bill = self._post_partial_bill(po, 4)
        self.assertEqual(po.line_ids.qty_invoiced, 4)

        self._corrupt_bill_line_uom(bill)
        po.line_ids.invalidate_recordset(["qty_invoiced"])
        self.assertEqual(
            po.line_ids.qty_invoiced,
            4,
            "Incompatible UoM must degrade (unconverted) while browsing, not raise",
        )

    def test_incompatible_invoiced_uom_blocks_further_billing(self):
        po = self._confirmed_po()
        bill = self._post_partial_bill(po, 4)
        self._corrupt_bill_line_uom(bill)

        with self.assertRaises(UserError):
            po.create_invoice()

    def test_incompatible_invoiced_uom_blocks_bill_matching(self):
        """The OCR/bill-matching path sizes lines from ``qty_to_invoice`` without
        going through ``_prepare_aml_vals_list``, so it guards explicitly."""
        po = self._confirmed_po()
        bill = self._post_partial_bill(po, 4)
        self._corrupt_bill_line_uom(bill)

        new_bill = self.env["account.move"].create(
            {"move_type": "in_invoice", "partner_id": self.partner_a.id},
        )
        with self.assertRaises(UserError):
            new_bill._add_purchase_order_lines(po.line_ids)

    def test_compatible_invoiced_uom_still_bills(self):
        """The guard is inert on convertible units: ordinary billing proceeds."""
        po = self._confirmed_po()
        self._post_partial_bill(po, 4)

        bill = po.create_invoice()
        self.assertTrue(bill)
        self.assertEqual(bill.invoice_line_ids.quantity, 6)

    def test_incompatible_uom_blocks_line_matching(self):
        """The Match button pairs an *existing* bill line with an *existing*
        order line through a bare ``Command.link``, so it never reaches the
        posting-boundary guard and validates the pair itself."""
        self._confirmed_po()
        bill = self._draft_bill(self.uom_incompatible)
        self.assertEqual(
            bill.invoice_line_ids.product_uom_id,
            self.uom_incompatible,
            "Fixture precondition: the draft line must carry the odd UoM",
        )

        with self.assertRaises(UserError) as caught:
            self._match_rows().action_match_lines()

        # Assert *which* error: `action_match_lines` raises for several
        # unrelated reasons, so a bare `assertRaises(UserError)` goes green
        # even when the guard never runs.  Both unit names appear only in the
        # guard's own message.
        message = caught.exception.args[0]
        self.assertIn(self.uom_incompatible.display_name, message)
        self.assertIn(self.uom_unit.display_name, message)

        self.assertFalse(
            bill.invoice_line_ids.purchase_line_ids,
            "The guard runs before the link, so no pairing may survive the raise",
        )

    def test_compatible_uom_matches_normally(self):
        """Negative control: the matching guard is inert on convertible units."""
        po = self._confirmed_po()
        bill = self._draft_bill(self.uom_unit)

        self._match_rows().action_match_lines()

        self.assertEqual(
            bill.invoice_line_ids.purchase_line_ids,
            po.line_ids,
            "A compatible pair must still be matched",
        )
