from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.purchase import const


@tagged("-at_install", "post_install")
class TestPurchaseAuditFixes(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({"name": "Audit Vendor"})
        cls.consu = cls.env["product.product"].create(
            {
                "name": "Audit Consumable",
                "type": "consu",
                "purchase_ok": True,
                "standard_price": 100.0,
                "bill_policy": "ordered",
            },
        )

    @classmethod
    def default_env_context(cls):
        return {}

    def _confirmed_order(self, product, qty=10.0, discount=10.0, price=100.0):
        order = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_qty": qty,
                            "price_unit": price,
                            "discount": discount,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                ],
            },
        )
        order.action_confirm()
        return order

    def _post_move(self, move_type, product, qty, price, discount, order_line):
        move = self.env["account.move"].create(
            {
                "move_type": move_type,
                "partner_id": self.vendor.id,
                "invoice_date": fields.Date.today(),
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "quantity": qty,
                            "price_unit": price,
                            "discount": discount,
                            "tax_ids": [Command.clear()],
                            "purchase_line_ids": [Command.set(order_line.ids)],
                        },
                    ),
                ],
            },
        )
        move.action_post()
        return move

    def test_refund_is_subtracted_when_bill_discount_differs(self):
        """A credit note must lower the amount invoiced on both summing paths.

        `_sum_invoiced_with_discount_adjustment` used to omit `direction_sign`,
        so a refund was *added* to the amount already invoiced. The line then
        reported nothing left to invoice while its own `qty_to_invoice` still
        said four units.
        """
        order = self._confirmed_order(self.consu)
        line = order.line_ids

        # Vendor bills at 0% where the order agreed 10%, then credits 4 units.
        self._post_move("in_invoice", self.consu, 10.0, 100.0, 0.0, line)
        self._post_move("in_refund", self.consu, 4.0, 100.0, 0.0, line)
        line.invalidate_recordset()

        self.assertTrue(
            line._has_discount_differences(line._get_posted_invoice_lines()),
            "the bill's discount differs from the line's, so the adjusted "
            "summer is the one under test",
        )
        # 10 billed - 4 credited = 6 units, 1000.00 - 400.00 = 600.00 invoiced.
        self.assertAlmostEqual(line.qty_invoiced, 6.0, places=2)
        # Ordered value is 10 x 100 x 0.9 = 900.00, so 300.00 remains.
        self.assertAlmostEqual(line.amount_taxexc_to_invoice, 300.0, places=2)
        self.assertAlmostEqual(line.qty_to_invoice, 4.0, places=2)

    def test_refund_symmetric_across_both_summing_paths(self):
        """The two summers must agree about a refund's direction."""
        matching = self._confirmed_order(self.consu)
        self._post_move("in_invoice", self.consu, 10.0, 100.0, 10.0, matching.line_ids)
        self._post_move("in_refund", self.consu, 4.0, 100.0, 10.0, matching.line_ids)
        matching.line_ids.invalidate_recordset()

        differing = self._confirmed_order(self.consu)
        self._post_move("in_invoice", self.consu, 10.0, 100.0, 0.0, differing.line_ids)
        self._post_move("in_refund", self.consu, 4.0, 100.0, 0.0, differing.line_ids)
        differing.line_ids.invalidate_recordset()

        for line in (matching.line_ids, differing.line_ids):
            self.assertGreater(
                line.amount_taxexc_to_invoice,
                0.0,
                "four units are still to bill, so the amount cannot be zero",
            )

    def test_discount_difference_tolerates_float_noise(self):
        order = self._confirmed_order(self.consu, discount=10.0)
        line = order.line_ids
        self._post_move(
            "in_invoice",
            self.consu,
            10.0,
            100.0,
            10.0 + 1e-12,
            line,
        )
        line.invalidate_recordset()
        self.assertFalse(
            line._has_discount_differences(line._get_posted_invoice_lines()),
            "a float representation difference is not a discount difference",
        )

    def test_service_only_orders_are_never_reminded(self):
        """Two distinct service products used to defeat the service-only test.

        The old filter compared `mapped(...)` to the literal `["service"]`, so
        an order with two different service products produced
        `["service", "service"]` and was reminded.
        """
        vendor = self.env["res.partner"].create(
            {
                "name": "Reminder Vendor",
                "receipt_reminder_email": True,
                "reminder_date_before_receipt": 1,
            },
        )
        services = self.env["product.product"].create(
            [
                {"name": f"Audit Service {i}", "type": "service", "purchase_ok": True}
                for i in range(2)
            ],
        )
        tomorrow = fields.Datetime.now() + timedelta(days=1)

        def order_for(products):
            order = self.env["purchase.order"].create(
                {
                    "partner_id": vendor.id,
                    "line_ids": [
                        Command.create(
                            {
                                "product_id": product.id,
                                "product_qty": 1,
                                "price_unit": 5.0,
                                "date_commitment": tomorrow,
                            },
                        )
                        for product in products
                    ],
                },
            )
            order.action_confirm()
            return order

        one_service = order_for(services[0])
        two_services = order_for(services)
        same_service_twice = order_for(services[0] | services[0])
        mixed = order_for(services[0] | self.consu)

        to_remind = self.env["purchase.order"]._get_orders_to_remind()
        self.assertNotIn(one_service, to_remind)
        self.assertNotIn(two_services, to_remind)
        self.assertNotIn(same_service_twice, to_remind)
        self.assertIn(
            mixed,
            to_remind,
            "an order carrying a physical product still needs its receipt date",
        )

    def test_dashboard_average_respects_allowed_companies(self):
        """`days_to_order` used to be raw SQL over every company.

        The five counts beside it go through `_read_group`, so they were scoped
        while the average was not.
        """
        other_company = self.env["res.company"].create({"name": "Audit Other Co"})
        buyer = new_test_user(
            self.env,
            login="auditbuyer",
            groups="purchase.group_purchase_user_all",
            company_id=self.env.company.id,
            company_ids=[Command.set([self.env.company.id, other_company.id])],
        )

        def confirmed_in(company, days_to_confirm):
            order = (
                self.env["purchase.order"]
                .with_company(company)
                .create(
                    {
                        "partner_id": self.vendor.id,
                        "company_id": company.id,
                        "user_id": buyer.id,
                        "line_ids": [
                            Command.create(
                                {
                                    "product_id": self.consu.id,
                                    "product_qty": 1,
                                    "price_unit": 5.0,
                                },
                            ),
                        ],
                    },
                )
            )
            order.action_confirm()
            order.date_confirmed = order.create_date + timedelta(days=days_to_confirm)
            return order

        confirmed_in(self.env.company, 2)
        confirmed_in(other_company, 40)
        self.env.flush_all()

        scoped = (
            self.env["purchase.order"]
            .with_user(buyer)
            .with_context(allowed_company_ids=[self.env.company.id])
        )
        result = scoped.prepare_dashboard()

        readable = scoped.search(
            [("state", "=", "done"), ("date_confirmed", "!=", False)],
        )
        self.assertEqual(
            readable.company_id,
            self.env.company,
            "only the selected company's orders are readable here",
        )
        self.assertLess(
            result["global"]["days_to_order"],
            21.0,
            "averaging the unselected company would report (2 + 40) / 2",
        )

    def test_dashboard_counts_agree_with_searching_the_same_domains(self):
        """Every card count must equal what its own domain returns for that user.

        The five counts and the `days_to_order` average are produced by two
        different mechanisms; this pins the counts to the domains so that
        collapsing them into one loop cannot quietly change a bucket.
        """
        buyer = new_test_user(
            self.env,
            login="auditcounts",
            groups="purchase.group_purchase_user_all",
        )
        orders = self.env["purchase.order"].create(
            [
                {
                    "partner_id": self.vendor.id,
                    "user_id": buyer.id,
                    "line_ids": [
                        Command.create(
                            {
                                "product_id": self.consu.id,
                                "product_qty": 1,
                                "price_unit": 5.0,
                            },
                        ),
                    ],
                }
                for _index in range(3)
            ],
        )
        orders[0].action_confirm()
        self.env.flush_all()

        purchase_order = self.env["purchase.order"].with_user(buyer)
        result = purchase_order.prepare_dashboard()
        for key, domain in purchase_order._get_dashboard_count_domains().items():
            self.assertEqual(
                result["global"][key]["all"],
                purchase_order.search_count(domain),
                f"the {key!r} card disagrees with its own domain",
            )

    def test_date_commitment_not_updatable_once_cancelled_or_locked(self):
        """The portal route reaches this on a read-level token and a sudo record."""
        order = self._confirmed_order(self.consu)
        line = order.line_ids
        new_date = line._convert_to_middle_of_day(
            fields.Datetime.now() + timedelta(days=30),
        )

        self.assertTrue(order._is_date_commitment_updatable())
        order.action_lock()
        self.assertFalse(order._is_date_commitment_updatable())
        with self.assertRaises(UserError):
            order._update_order_lines_date_commitment([(line, new_date)])

        cancelled = self._confirmed_order(self.consu)
        cancelled.action_cancel()
        self.assertFalse(cancelled._is_date_commitment_updatable())
        with self.assertRaises(UserError):
            cancelled._update_order_lines_date_commitment(
                [(cancelled.line_ids, new_date)],
            )

    def test_date_commitment_updatable_while_still_a_draft_rfq(self):
        """Proposing an arrival date is part of negotiating an RFQ."""
        order = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create({"product_id": self.consu.id, "product_qty": 1}),
                ],
            },
        )
        self.assertEqual(order.state, "draft")
        self.assertTrue(order._is_date_commitment_updatable())

    def test_date_commitment_updatable_while_confirmed_and_unlocked(self):
        order = self._confirmed_order(self.consu)
        line = order.line_ids
        new_date = line._convert_to_middle_of_day(
            fields.Datetime.now() + timedelta(days=30),
        )
        order._update_order_lines_date_commitment([(line, new_date)])
        self.assertEqual(line.date_commitment, new_date)

    def test_procurement_line_keeps_the_product_lead_time(self):
        """`_prepare_purchase_order_line` is `@api.model`; `self.order_id` is empty.

        The `self.order_id.date_commitment or ...` prefix it carried could never
        be true, and substituting the order's own date would have promised a
        long-lead product on the shortest line's date.
        """
        fast, slow = self.env["product.product"].create(
            [
                {"name": "Audit Fast", "type": "consu", "purchase_ok": True},
                {"name": "Audit Slow", "type": "consu", "purchase_ok": True},
            ],
        )
        for product, delay in ((fast, 2), (slow, 30)):
            self.env["product.supplierinfo"].create(
                {
                    "partner_id": self.vendor.id,
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "price": 10.0,
                    "delay": delay,
                    "min_qty": 0,
                },
            )

        now = fields.Datetime.now()
        order = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "date_order": now,
                "line_ids": [
                    Command.create({"product_id": fast.id, "product_qty": 1}),
                ],
            },
        )
        self.env.flush_all()

        vals = self.env["purchase.order.line"]._prepare_purchase_order_line(
            slow,
            1.0,
            slow.uom_id,
            self.env.company,
            self.vendor,
            order,
        )
        self.assertEqual(
            vals["date_commitment"].date(),
            (now + timedelta(days=30)).date(),
            "the slow product keeps its own 30-day lead time",
        )

    def test_supplier_cap_is_not_exceeded(self):
        product = self.env["product.product"].create(
            {"name": "Audit Capped", "type": "consu", "purchase_ok": True},
        )
        partners = self.env["res.partner"].create(
            [
                {"name": f"Audit Seller {i}"}
                for i in range(const.MAX_SUPPLIERS_PER_PRODUCT)
            ],
        )
        self.env["product.supplierinfo"].create(
            [
                {
                    "partner_id": partner.id,
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "price": 1.0,
                }
                for partner in partners
            ],
        )
        product.invalidate_recordset()
        self.assertEqual(len(product.seller_ids), const.MAX_SUPPLIERS_PER_PRODUCT)

        newcomer = self.env["res.partner"].create({"name": "Audit Seller Extra"})
        order = self.env["purchase.order"].create(
            {
                "partner_id": newcomer.id,
                "line_ids": [
                    Command.create({"product_id": product.id, "product_qty": 1}),
                ],
            },
        )
        order.action_confirm()
        product.invalidate_recordset()
        self.assertEqual(
            len(product.seller_ids),
            const.MAX_SUPPLIERS_PER_PRODUCT,
            "the cap is a maximum, not the count at which one more is allowed",
        )
