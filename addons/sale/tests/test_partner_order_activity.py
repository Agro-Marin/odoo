from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestPartnerOrderActivity(TransactionCase):
    """Pins that sale.order actually reaches base_order's activity figures.

    ``recent_orders_count`` and ``days_since_last_order`` are declared in
    base_order, which cannot name sale.order; sale registers it through
    ``_get_order_activity_sources``. Nothing else asserts that the
    registration takes effect, so a silently-dropped override would leave both
    figures reading zero with every suite still green.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.write(
            {
                "order_cycle_interval_number": 3,
                "order_cycle_interval_type": "months",
            },
        )
        cls.partner = cls.env["res.partner"].create({"name": "Ordering customer"})
        cls.product = cls.env["product.product"].create(
            {"name": "Cycle product", "type": "consu", "list_price": 10.0},
        )

    def _make_sale_order(self, days_ago, state="done"):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [
                    (0, 0, {"product_id": self.product.id, "product_qty": 1}),
                ],
            },
        )
        order.write(
            {
                "state": state,
                "date_order": fields.Datetime.now() - timedelta(days=days_ago),
            },
        )
        return order

    def test_sale_is_registered_as_an_order_activity_source(self):
        sources = dict(self.partner._get_order_activity_sources())
        self.assertIn("sale.order", sources)
        self.assertEqual(sources["sale.order"], [("state", "=", "done")])

    def test_confirmed_sale_orders_reach_recent_orders_count(self):
        self._make_sale_order(days_ago=5)
        self._make_sale_order(days_ago=45)
        self._make_sale_order(days_ago=200)

        self.partner.invalidate_recordset(["recent_orders_count"])
        self.assertEqual(
            self.partner.recent_orders_count,
            2,
            "the 200-day-old order is outside a three-month cycle",
        )

    def test_draft_sale_orders_are_not_counted(self):
        self._make_sale_order(days_ago=5, state="draft")

        self.partner.invalidate_recordset(["recent_orders_count"])
        self.assertEqual(self.partner.recent_orders_count, 0)

    def test_confirmed_sale_orders_reach_days_since_last_order(self):
        self._make_sale_order(days_ago=200)
        self._make_sale_order(days_ago=7)

        self.partner.invalidate_recordset(["days_since_last_order"])
        self.assertEqual(self.partner.days_since_last_order, 7)

    def test_a_partner_with_no_sale_order_reports_the_sentinel(self):
        self.partner.invalidate_recordset(["days_since_last_order"])
        self.assertEqual(self.partner.days_since_last_order, 9999)

    def test_the_company_cycle_changes_what_is_counted(self):
        self._make_sale_order(days_ago=200)

        self.partner.invalidate_recordset(["recent_orders_count"])
        self.assertEqual(self.partner.recent_orders_count, 0)

        self.env.company.order_cycle_interval_number = 1
        self.env.company.order_cycle_interval_type = "years"
        self.partner.invalidate_recordset(["recent_orders_count"])
        self.assertEqual(self.partner.recent_orders_count, 1)

    def test_a_user_without_sale_access_gets_zero_instead_of_an_access_error(self):
        """res.partner is readable by every internal user; sale.order is not.

        Both figures live on res.partner and carry no ``groups=``, so before
        the readable-source filter an ungated ``_read_group`` turned any full
        read of a partner into an AccessError for an internal user outside the
        sales groups. Asserted on the source list rather than on the figures,
        because another installed module may register a source this user *can*
        read.
        """
        self._make_sale_order(days_ago=5)
        outsider = new_test_user(
            self.env,
            login="order_activity_outsider",
            groups="base.group_user",
        )
        self.assertFalse(self.env["sale.order"].with_user(outsider).has_access("read"))

        partner = self.partner.with_user(outsider)
        readable = dict(
            partner._get_readable_order_activity_sources(
                partner._get_order_activity_sources(),
            ),
        )
        self.assertNotIn("sale.order", readable)

        partner.invalidate_recordset(
            ["recent_orders_count", "days_since_last_order"],
        )
        self.assertEqual(
            partner.recent_orders_count,
            0,
            "the unreadable sale.order source contributes nothing "
            "instead of raising",
        )
        self.assertIsInstance(
            partner.days_since_last_order,
            int,
            "reading the sibling figure must not raise either",
        )

    def test_a_salesman_seeing_all_orders_reads_the_real_figures(self):
        self._make_sale_order(days_ago=5)
        salesman = new_test_user(
            self.env,
            login="order_activity_salesman",
            groups="base.group_user,sales_team.group_sale_salesman_all_leads",
        )

        partner = self.partner.with_user(salesman)
        partner.invalidate_recordset(
            ["recent_orders_count", "days_since_last_order"],
        )
        self.assertEqual(partner.recent_orders_count, 1)
        self.assertEqual(partner.days_since_last_order, 5)

    def test_the_figures_do_not_vary_with_who_reads_them(self):
        """The figure is a property of the customer, not of the reader.

        ``sale_order_personal_rule`` restricts a plain salesman to orders whose
        ``user_id`` is theirs. Read unsudoed, the same customer would report a
        different count to every salesperson, and would report to the merge
        cron whatever the cron user happens to see -- which decides whether the
        partner gets merged away.
        """
        self._make_sale_order(days_ago=5)
        restricted = new_test_user(
            self.env,
            login="order_activity_restricted",
            groups="base.group_user,sales_team.group_sale_salesman",
        )
        self.assertFalse(
            self.env["sale.order"]
            .with_user(restricted)
            .search([("partner_id", "=", self.partner.id)]),
            "the record rule really does hide the order from this user",
        )

        partner = self.partner.with_user(restricted)
        partner.invalidate_recordset(
            ["recent_orders_count", "days_since_last_order"],
        )
        self.assertEqual(partner.recent_orders_count, 1)
        self.assertEqual(partner.days_since_last_order, 5)

    def test_the_cache_is_partitioned_by_reader(self):
        """A value that varies with the reader must be keyed by the reader.

        The ACL gate makes these figures user-dependent, and the ORM caches a
        computed field once per ``cache_key``. Without ``uid`` in
        ``depends_context`` a restricted user reads back whatever the previous
        reader computed, with no invalidation in between.
        """
        self._make_sale_order(days_ago=5)
        outsider = new_test_user(
            self.env,
            login="order_activity_cache_outsider",
            groups="base.group_user",
        )

        self.assertEqual(self.partner.recent_orders_count, 1)
        self.assertEqual(
            self.partner.with_user(outsider).recent_orders_count,
            0,
            "read straight after the admin read, with no invalidation",
        )
        self.assertEqual(
            self.partner.recent_orders_count,
            1,
            "and the admin entry is still its own",
        )

    def test_orders_of_another_company_are_outside_the_cycle(self):
        """Sudo drops the multi-company rule, so the scope is restated.

        The cycle is read from ``env.company``; counting an order booked in a
        company whose cycle was never consulted would make the window and the
        population disagree.
        """
        other_company = self.env["res.company"].create({"name": "Second company"})
        order = self._make_sale_order(days_ago=5)
        order.sudo().company_id = other_company

        self.partner.invalidate_recordset(
            ["recent_orders_count", "days_since_last_order"],
        )
        self.assertEqual(self.partner.recent_orders_count, 0)
        self.assertEqual(self.partner.days_since_last_order, 9999)
