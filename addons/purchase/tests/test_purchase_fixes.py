"""Regression tests for fork-specific correctness fixes.

Covers two previously-untested areas that broke during the order-state
simplification (draft/done/cancel) and the base_order migration:

* the portal RFQ list/counter state domain (was filtering the dead ``sent``
  state, leaving ``/my/rfq`` and ``rfq_count`` permanently empty);
* the mass-cancel wizard, which bypassed the ``_can_cancel`` guards and could
  silently cancel locked orders or orders with posted vendor bills.
"""

from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.purchase.controllers.portal import CustomerPortal


@tagged("-at_install", "post_install")
class TestPurchasePortalRfqDomain(AccountTestInvoicingCommon):
    """The portal RFQ page must select unconfirmed orders (state == draft)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rfq = cls.env["purchase.order"].create(
            {
                "partner_id": cls.partner_a.id,
                "line_ids": [
                    Command.create(
                        {"product_id": cls.product_a.id, "product_qty": 1.0},
                    ),
                ],
            },
        )
        cls.confirmed = cls.env["purchase.order"].create(
            {
                "partner_id": cls.partner_a.id,
                "line_ids": [
                    Command.create(
                        {"product_id": cls.product_a.id, "product_qty": 1.0},
                    ),
                ],
            },
        )
        cls.confirmed.action_confirm()

    def test_rfq_state_domain_is_draft(self):
        """The domain must target ``draft`` (RFQ), never the removed ``sent``."""
        domain = CustomerPortal()._purchase_get_page_state_domain("rfq")
        self.assertEqual(domain, [("state", "=", "draft")])

    def test_rfq_domain_matches_unconfirmed_orders(self):
        """A draft PO is an RFQ; a confirmed PO is not — the domain must agree.

        This guards the regression where the domain filtered ``state == 'sent'``
        (a state that no longer exists), so ``/my/rfq`` returned nothing.
        """
        domain = CustomerPortal()._purchase_get_page_state_domain("rfq")
        matched = self.env["purchase.order"].search(
            domain + [("id", "in", (self.rfq | self.confirmed).ids)],
        )
        self.assertIn(self.rfq, matched, "Draft RFQ should show on /my/rfq")
        self.assertNotIn(
            self.confirmed, matched, "Confirmed PO should not show on /my/rfq",
        )

    def test_rfq_report_ref_uses_quotation_for_draft(self):
        """RFQs (draft) render the quotation report; confirmed POs the order."""
        self.assertEqual(
            CustomerPortal._purchase_detail_report_ref(self.rfq),
            "purchase.report_purchase_quotation",
        )
        self.assertEqual(
            CustomerPortal._purchase_detail_report_ref(self.confirmed),
            "purchase.action_report_purchase_order",
        )


@tagged("-at_install", "post_install")
class TestPurchaseMassCancel(AccountTestInvoicingCommon):
    """The mass-cancel wizard must honour the same guards as action_cancel."""

    def _make_po(self, confirm=False):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {"product_id": self.product_a.id, "product_qty": 1.0},
                    ),
                ],
            },
        )
        if confirm:
            po.action_confirm()
        return po

    def _wizard(self, orders):
        return self.env["purchase.mass.cancel.orders"].create(
            {"purchase_order_ids": [Command.set(orders.ids)]},
        )

    def test_mass_cancel_drafts(self):
        """Plain draft RFQs cancel cleanly."""
        pos = self._make_po() | self._make_po()
        self._wizard(pos).action_mass_cancel()
        self.assertEqual(set(pos.mapped("state")), {"cancel"})

    def test_mass_cancel_blocks_locked_order(self):
        """A locked PO in the selection must not be silently cancelled."""
        locked = self._make_po(confirm=True)
        locked.action_lock()
        with self.assertRaises(UserError):
            self._wizard(locked).action_mass_cancel()
        self.assertEqual(locked.state, "done", "Locked PO must survive mass-cancel")

    def test_mass_cancel_blocks_posted_bill(self):
        """A PO with a posted vendor bill must not be silently cancelled."""
        po = self._make_po(confirm=True)
        bill = po.create_invoice()
        bill.invoice_date = bill.invoice_date or po.date_order.date()
        bill.action_post()
        self.assertEqual(bill.state, "posted")
        with self.assertRaises(UserError):
            self._wizard(po).action_mass_cancel()
        self.assertEqual(po.state, "done", "Invoiced PO must survive mass-cancel")

    def test_mass_cancel_skips_already_cancelled(self):
        """A mixed selection cancels the live orders and skips cancelled ones."""
        live = self._make_po()
        already = self._make_po()
        already.action_cancel()
        self._wizard(live | already).action_mass_cancel()
        self.assertEqual(live.state, "cancel")
        self.assertEqual(already.state, "cancel")


@tagged("-at_install", "post_install")
class TestPurchaseMergeConsolidation(AccountTestInvoicingCommon):
    """RFQ merge line consolidation is date-sensitive (order.merge.mixin).

    Guards the behaviour after removing purchase's parallel merge pipeline in
    favour of the base_order mixin: same-product lines consolidate only when
    their expected dates match within the 24h threshold.
    """

    def _rfq_with_date(self, date_planned):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {"product_id": self.product_a.id, "product_qty": 3.0},
                    ),
                ],
            },
        )
        po.line_ids.date_planned = date_planned
        return po

    def test_same_date_lines_consolidate(self):
        po1 = self._rfq_with_date("2026-07-20 12:00:00")
        po2 = self._rfq_with_date("2026-07-20 12:00:00")
        (po1 | po2).action_merge()
        target = po1 if po1.state != "cancel" else po2
        product_lines = target.line_ids.filtered(lambda l: not l.display_type)
        self.assertEqual(len(product_lines), 1, "matching dates should merge")
        self.assertEqual(product_lines.product_qty, 6.0, "quantities summed")

    def test_mismatched_date_lines_stay_separate(self):
        po1 = self._rfq_with_date("2026-07-20 12:00:00")
        po2 = self._rfq_with_date("2026-07-25 12:00:00")  # > 24h apart
        (po1 | po2).action_merge()
        target = po1 if po1.state != "cancel" else po2
        product_lines = target.line_ids.filtered(lambda l: not l.display_type)
        self.assertEqual(
            len(product_lines), 2, "dates > 24h apart must not consolidate",
        )


@tagged("-at_install", "post_install")
class TestPurchaseSellerCache(AccountTestInvoicingCommon):
    """Guard the seller-lookup cache in ``_compute_selected_seller_id``.

    Lines sharing ``(product, partner, order, uom, qty)`` must trigger a single
    ``_select_seller`` resolution, not one per line — the benchmark docs rely on
    this but nothing asserted it, so a broken cache key would pass every test.
    """

    def test_seller_lookup_cached_across_identical_lines(self):
        pol_model = self.env["purchase.order.line"]
        model_cls = type(pol_model)
        original = model_cls._get_select_sellers_params
        misses = []

        def counting(line_self):
            # One call per cache miss (unique key), inside _compute_selected_seller_id.
            misses.append(line_self.product_id.id)
            return original(line_self)

        with patch.object(model_cls, "_get_select_sellers_params", counting):
            self.env["purchase.order"].create(
                {
                    "partner_id": self.partner_a.id,
                    "line_ids": [
                        Command.create(
                            {"product_id": self.product_a.id, "product_qty": 2.0},
                        )
                        for _ in range(5)
                    ],
                },
            )

        self.assertEqual(
            len(misses),
            1,
            "Five identical-key lines should resolve the seller only once "
            f"(got {len(misses)} lookups)",
        )


@tagged("-at_install", "post_install")
class TestSrmTag(AccountTestInvoicingCommon):
    """Coverage for the fork's SRM tag model (previously untested).

    ``srm.tag`` builds on ``tag.mixin`` (hierarchical, colored tags) and adds a
    many2many to ``purchase.order``.
    """

    def test_hierarchical_display_name(self):
        parent = self.env["srm.tag"].create({"name": "Strategic"})
        child = self.env["srm.tag"].create(
            {"name": "Key Vendor", "parent_id": parent.id},
        )
        self.assertEqual(child.display_name, "Strategic / Key Vendor")
        self.assertEqual(parent.display_name, "Strategic")

    def test_recursion_is_rejected(self):
        a = self.env["srm.tag"].create({"name": "A"})
        b = self.env["srm.tag"].create({"name": "B", "parent_id": a.id})
        # _parent_store raises UserError ("Recursion Detected."); the tag.mixin
        # _check_parent_id constraint raises ValidationError (a UserError
        # subclass) — either way it must be rejected.
        with self.assertRaises(UserError):
            a.parent_id = b
            a.flush_recordset()

    def test_order_tag_relation_is_bidirectional(self):
        tag = self.env["srm.tag"].create({"name": "Preferred"})
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "tag_ids": [Command.link(tag.id)],
                "line_ids": [
                    Command.create(
                        {"product_id": self.product_a.id, "product_qty": 1.0},
                    ),
                ],
            },
        )
        self.assertIn(po, tag.order_ids)
        self.assertIn(tag, po.tag_ids)

    def test_parent_delete_cascades_to_children(self):
        """Deleting a parent tag removes its children (matches crm.tag)."""
        parent = self.env["srm.tag"].create({"name": "Root"})
        child = self.env["srm.tag"].create(
            {"name": "Leaf", "parent_id": parent.id},
        )
        parent.unlink()
        self.assertFalse(child.exists())


@tagged("-at_install", "post_install")
class TestBillPoLinkTracking(AccountTestInvoicingCommon):
    """account.move.write posts a chatter note when a PO link is added, and the
    diff work is skipped for writes that can't change purchase links.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.po = cls.env["purchase.order"].create(
            {
                "partner_id": cls.partner_a.id,
                "line_ids": [
                    Command.create(
                        {"product_id": cls.product_a.id, "product_qty": 1.0},
                    ),
                ],
            },
        )
        cls.po.action_confirm()

    def _new_bill(self):
        return self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-01-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "price_unit": 100,
                        },
                    ),
                ],
            },
        )

    def _has_modified_note(self, move):
        return any(
            "modified from" in (m.body or "") for m in move.message_ids
        )

    def test_linking_po_via_write_posts_note(self):
        bill = self._new_bill()
        self.assertFalse(self._has_modified_note(bill))
        bill.write(
            {
                "invoice_line_ids": [
                    Command.update(
                        bill.invoice_line_ids.id,
                        {"purchase_line_ids": [Command.link(self.po.line_ids.id)]},
                    ),
                ],
            },
        )
        self.assertTrue(
            self._has_modified_note(bill),
            "linking a PO via invoice_line_ids write should post the note",
        )

    def test_non_line_write_does_not_post_note(self):
        bill = self._new_bill()
        bill.write({"ref": "SOME-REF"})
        self.assertFalse(
            self._has_modified_note(bill),
            "a ref-only write must not post a PO-modified note",
        )


@tagged("-at_install", "post_install")
class TestPurchaseOverInvoiceState(AccountTestInvoicingCommon):
    """Over-billed lines: 'over done' on 'ordered' products, 'to do' on
    'transferred' products (return/credit note). Mirrors sale, keyed on
    bill_policy — previously 'over done' was unreachable in purchase.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.svc_ordered = cls.env["product.product"].create(
            {
                "name": "Svc ordered",
                "type": "service",
                "bill_policy": "ordered",
                "purchase_ok": True,
                "standard_price": 100.0,
            },
        )
        cls.svc_transferred = cls.env["product.product"].create(
            {
                "name": "Svc transferred",
                "type": "service",
                "bill_policy": "transferred",
                "purchase_ok": True,
                "standard_price": 100.0,
            },
        )

    def _confirmed_po(self, product, qty):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {"product_id": product.id, "product_qty": qty, "price_unit": 100},
                    ),
                ],
            },
        )
        po.action_confirm()
        return po

    def _post_bill(self, po, product, qty):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-01-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "quantity": qty,
                            "price_unit": 100,
                            "purchase_line_ids": [Command.set(po.line_ids.ids)],
                        },
                    ),
                ],
            },
        )
        bill.action_post()
        return bill

    def test_ordered_over_billed_is_over_done(self):
        po = self._confirmed_po(self.svc_ordered, 1)
        self._post_bill(po, self.svc_ordered, 2)  # billed 2 > ordered 1
        self.assertEqual(po.line_ids.invoice_state, "over done")
        self.assertEqual(po.invoice_state, "over done")

    def test_transferred_over_billed_is_to_do(self):
        po = self._confirmed_po(self.svc_transferred, 5)
        po.line_ids.qty_transferred = 1.0  # received 1
        self._post_bill(po, self.svc_transferred, 2)  # billed 2 > received 1
        self.assertEqual(po.line_ids.invoice_state, "to do")
        self.assertEqual(po.invoice_state, "to do")

    def test_reduce_qty_below_invoiced_is_over_done(self):
        """Mirror of sale's test_invoice_state_over_invoiced_ordered_policy:
        fully bill, then amend the ordered qty below what was billed.
        """
        po = self._confirmed_po(self.svc_ordered, 5)
        line = po.line_ids
        self._post_bill(po, self.svc_ordered, 5)  # fully bill the ordered qty
        self.assertEqual(line.qty_invoiced, 5.0)
        self.assertEqual(line.invoice_state, "done")

        line.product_qty = 3  # ordered amended below invoiced -> over-invoiced
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(line.qty_to_invoice, -2.0)
        self.assertEqual(line.invoice_state, "over done")
        self.assertEqual(po.invoice_state, "over done")


@tagged("-at_install", "post_install")
class TestPurchaseAmountToInvoice(AccountTestInvoicingCommon):
    """Coverage-parity port of sale's amount_to_invoice tests (test_sale_to_invoice).

    Purchase had ZERO tests for amount_*_to_invoice / amount_*_invoiced, the
    shared invoice-amount compute (incl. the discount-adjustment path).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.svc_ordered = cls.env["product.product"].create(
            {
                "name": "Svc ordered notax",
                "type": "service",
                "bill_policy": "ordered",
                "purchase_ok": True,
                "standard_price": 100.0,
                "supplier_taxes_id": [Command.clear()],
            },
        )
        cls.svc_transferred = cls.env["product.product"].create(
            {
                "name": "Svc transferred notax",
                "type": "service",
                "bill_policy": "transferred",
                "purchase_ok": True,
                "standard_price": 100.0,
                "supplier_taxes_id": [Command.clear()],
            },
        )

    def test_amount_to_invoice_with_discount(self):
        """Port of sale.test_amount_to_invoice_with_discount."""
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.svc_ordered.id,
                            "product_qty": 5,
                            "price_unit": 100,
                            "discount": 10,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                ],
            },
        )
        po.action_confirm()
        self.assertEqual(po.amount_taxinc_to_invoice, 450.0)

        bill = po.create_invoice()
        bill.invoice_date = "2026-01-01"
        bill.invoice_line_ids.quantity = 3
        bill.action_post()
        self.assertEqual(po.amount_taxinc_to_invoice, 180.0)

    def test_amount_to_invoice_price_unit_change(self):
        """Port of sale.test_amount_to_invoice_price_unit_change.

        amount_to_invoice depends only on posted invoice *quantity*, not on
        price changes; draft invoices don't count.
        """
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.svc_transferred.id,
                            "product_qty": 5,
                            "price_unit": 100,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                ],
            },
        )
        po.action_confirm()
        line = po.line_ids
        line.qty_transferred = 5.0

        bill = po.create_invoice()
        # Draft bill: no effect on qty_invoiced / amounts.
        self.assertEqual(line.qty_invoiced, 0.0)
        self.assertEqual(line.amount_taxinc_to_invoice, line.price_total)
        self.assertEqual(line.amount_taxinc_invoiced, 0.0)

        bill.invoice_date = "2026-01-01"
        bill.invoice_line_ids.price_unit /= 2
        bill.action_post()
        # All qty billed -> nothing left to invoice, regardless of the price change.
        self.assertEqual(line.qty_invoiced, 5.0)
        self.assertEqual(line.amount_taxinc_to_invoice, 0.0)
        self.assertEqual(line.amount_taxinc_invoiced, line.price_total / 2)


@tagged("-at_install", "post_install")
class TestPurchaseInvoiceSections(AccountTestInvoicingCommon):
    """Coverage-parity port of sale's section-invoicing test, plus the
    fork-specific rule: a section is billed only when directly followed by a
    product line (purchase._prepare_invoice_line_commands).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.svc = cls.env["product.product"].create(
            {
                "name": "Svc ordered notax",
                "type": "service",
                "bill_policy": "ordered",
                "purchase_ok": True,
                "standard_price": 100.0,
                "supplier_taxes_id": [Command.clear()],
            },
        )

    def _po(self, line_cmds):
        po = self.env["purchase.order"].create(
            {"partner_id": self.partner_a.id, "line_ids": line_cmds},
        )
        po.action_confirm()
        return po

    def _product_cmd(self):
        return Command.create(
            {"product_id": self.svc.id, "product_qty": 5, "price_unit": 100,
             "tax_ids": [Command.clear()]},
        )

    def test_section_before_product_is_billed(self):
        po = self._po([
            Command.create({"display_type": "line_section", "name": "Sec A"}),
            self._product_cmd(),
        ])
        bill = po.create_invoice()
        sections = bill.invoice_line_ids.filtered(
            lambda l: l.display_type == "line_section",
        )
        self.assertEqual(sections.mapped("name"), ["Sec A"])

    def test_trailing_section_not_billed(self):
        po = self._po([
            self._product_cmd(),
            Command.create({"display_type": "line_section", "name": "Trailing"}),
        ])
        bill = po.create_invoice()
        names = bill.invoice_line_ids.filtered(
            lambda l: l.display_type == "line_section",
        ).mapped("name")
        self.assertNotIn("Trailing", names, "trailing section must not be billed")


@tagged("-at_install", "post_install")
class TestPurchaseQtyInvoicedParity(AccountTestInvoicingCommon):
    """Parity ports of sale's qty_invoiced (UoM rounding) and multi-order
    amount_to_invoice tests — untested in purchase.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.svc = cls.env["product.product"].create(
            {
                "name": "Svc ordered notax",
                "type": "service",
                "bill_policy": "ordered",
                "purchase_ok": True,
                "standard_price": 100.0,
                "supplier_taxes_id": [Command.clear()],
            },
        )
        cls.svc_tr = cls.env["product.product"].create(
            {
                "name": "Svc transferred notax",
                "type": "service",
                "bill_policy": "transferred",
                "purchase_ok": True,
                "standard_price": 100.0,
                "supplier_taxes_id": [Command.clear()],
            },
        )

    def _confirmed_po(self, product, qty):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {"product_id": product.id, "product_qty": qty,
                         "price_unit": 100, "tax_ids": [Command.clear()]},
                    ),
                ],
            },
        )
        po.action_confirm()
        return po

    def test_qty_invoiced_default_rounding(self):
        po = self._confirmed_po(self.svc, 5)
        bill = po.create_invoice()
        bill.invoice_date = "2026-01-01"
        self.assertEqual(po.line_ids.qty_invoiced, 0.0, "draft must not count")
        bill.invoice_line_ids.quantity = 5.13
        bill.action_post()
        self.assertEqual(po.line_ids.qty_invoiced, 5.13)

    def test_qty_invoiced_uom_ceil_rounding(self):
        """qty_invoiced rounds UP (ceil) to the product UoM, not floor/half-up.

        Faithful port of sale.test_qty_invoiced: qty_invoiced does not depend on
        uom.rounding, so change it after posting and force the recompute.
        """
        po = self._confirmed_po(self.svc, 5)
        bill = po.create_invoice()
        bill.invoice_date = "2026-01-01"
        bill.invoice_line_ids.quantity = 5.13
        bill.action_post()
        line = po.line_ids
        self.assertEqual(line.qty_invoiced, 5.13)  # rounding 0.01

        line.product_uom_id.rounding = 0.1
        line.product_uom_id.flush_recordset(["rounding"])
        line.env.add_to_compute(line._fields["qty_invoiced"], line)
        self.assertEqual(line.qty_invoiced, 5.2)  # ceil to 0.1

    def test_amount_to_invoice_multiple_po(self):
        """Port of sale.test_amount_to_invoice_multiple_so: per-order amounts
        stay correct when several POs are billed together.
        """
        po1 = self._confirmed_po(self.svc_tr, 10)
        po2 = self._confirmed_po(self.svc_tr, 20)
        po1.line_ids.qty_transferred = 10
        po2.line_ids.qty_transferred = 20
        bills = (po1 | po2).create_invoice()
        bills.invoice_date = "2026-01-01"
        bills.action_post()
        self.assertEqual(po1.amount_taxinc_to_invoice, 0.0)
        self.assertEqual(po2.amount_taxinc_to_invoice, 0.0)
