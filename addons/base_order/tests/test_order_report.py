# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command
from odoo.tests import TransactionCase, tagged

# Part 6 of base_order's by-parts coverage: order.report.mixin, the analytical
# report layer shared by sale.report and purchase.report.
#
# These are SQL-view models, so a field that exists on the Python class is not
# proof of anything — the SELECT registry has to name it too. The tests
# therefore read the hoisted fields back out of the built view rather than just
# asserting they are declared.

HOISTED_FIELDS = [
    "company_id",
    "nbr_lines",
    "date_order",
    "product_category_id",
    "product_uom_qty",
    "price_unit",
    "price_subtotal",
    "price_total",
    "weight",
    "volume",
]


@tagged("post_install", "-at_install")
class TestOrderReportMixin(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Report Mixin Partner"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Report Mixin Product",
                "type": "consu",
                "list_price": 50.0,
                "standard_price": 20.0,
                "weight": 2.0,
                "volume": 3.0,
            },
        )

    def _confirmed_order(self, model):
        order = self.env[model].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": 4.0,
                            "price_unit": 25.0,
                        },
                    ),
                ],
            },
        )
        order.action_confirm()
        self.env.flush_all()
        self.env.invalidate_all()
        return order

    def _report_rows(self, report, order):
        return self.env[report].search(
            [("order_reference", "=", f"{order._name},{order.id}")],
        )

    # --- both reports are built on the shared mixin ---

    def test_reports_inherit_the_mixin(self):
        # Walk the registry MRO rather than reading ``_inherit``: once another
        # module extends sale.report or purchase.report, ``_inherit`` holds that
        # extension's list, not the original mixin chain.
        for report in ("sale.report", "purchase.report"):
            with self.subTest(report=report):
                bases = {
                    getattr(cls, "_name", None) for cls in type(self.env[report]).mro()
                }
                self.assertIn("order.report.mixin", bases)

    def test_hoisted_fields_exist(self):
        for report in ("sale.report", "purchase.report"):
            with self.subTest(report=report):
                missing = [
                    f for f in HOISTED_FIELDS if f not in self.env[report]._fields
                ]
                self.assertFalse(missing, f"{report} lost hoisted fields: {missing}")

    def test_shared_line_filter(self):
        """_get_where_conditions is the mixin's, on both reports."""
        for report in ("sale.report", "purchase.report"):
            with self.subTest(report=report):
                self.assertEqual(
                    self.env[report]._get_where_conditions(),
                    ["l.display_type IS NULL"],
                )

    # --- and the hoisted fields survive into the built SQL view ---

    def test_hoisted_fields_are_selected(self):
        for model, report in (
            ("sale.order", "sale.report"),
            ("purchase.order", "purchase.report"),
        ):
            with self.subTest(report=report):
                order = self._confirmed_order(model)
                rows = self._report_rows(report, order).read(HOISTED_FIELDS)
                self.assertTrue(rows, f"{report}: no row for the confirmed order")
                row = rows[0]
                # company_id is declared only on the mixin now, so this also
                # pins that both reports still SELECT the column for it.
                self.assertEqual(row["company_id"][0], order.company_id.id)
                self.assertEqual(row["nbr_lines"], 1)
                self.assertEqual(row["product_uom_qty"], 4.0)
                self.assertEqual(row["price_unit"], 25.0)
                self.assertEqual(row["price_subtotal"], 100.0)
                self.assertEqual(row["weight"], 8.0)
                self.assertEqual(row["volume"], 12.0)

    def test_action_view_order_routes_to_its_own_model(self):
        for model, report in (
            ("sale.order", "sale.report"),
            ("purchase.order", "purchase.report"),
        ):
            with self.subTest(report=report):
                order = self._confirmed_order(model)
                line = self._report_rows(report, order)[:1]
                action = line.action_view_order()
                self.assertEqual(action["res_model"], model)
                self.assertEqual(action["res_id"], order.id)

    def test_weighted_average_aggregate(self):
        """price_average:avg is quantity-weighted, not a plain AVG of rows."""
        for model, report in (
            ("sale.order", "sale.report"),
            ("purchase.order", "purchase.report"),
        ):
            with self.subTest(report=report):
                order = self._confirmed_order(model)
                groups = self.env[report]._read_group(
                    [("order_reference", "=", f"{model},{order.id}")],
                    [],
                    ["price_average:avg"],
                )
                self.assertEqual(groups[0][0], 25.0)

    # --- what must NOT be hoisted ---

    def test_state_selection_stays_per_module(self):
        """``state`` is spelled identically in both reports but means different
        things, so it must stay in the concrete models. Hoisting it would give
        purchase sale's labels (or the reverse)."""
        sale_states = dict(self.env["sale.report"]._fields["state"].selection)
        purchase_states = dict(self.env["purchase.report"]._fields["state"].selection)
        self.assertEqual(sale_states["done"], "Sales Order")
        self.assertEqual(purchase_states["done"], "Purchase Order")
        self.assertNotEqual(sale_states, purchase_states)
