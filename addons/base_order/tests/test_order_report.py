from odoo import Command
from odoo.tests import TransactionCase, tagged

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

    def test_reports_inherit_the_mixin(self):
        for report in ("sale.report", "purchase.report"):
            with self.subTest(report=report):
                bases = {
                    getattr(cls, "_name", None) for cls in type(self.env[report]).mro()
                }
                self.assertIn("mixin.order.report", bases)

    def test_hoisted_fields_exist(self):
        for report in ("sale.report", "purchase.report"):
            with self.subTest(report=report):
                missing = [
                    f for f in HOISTED_FIELDS if f not in self.env[report]._fields
                ]
                self.assertFalse(missing, f"{report} lost hoisted fields: {missing}")

    def test_shared_line_filter(self):
        for report in ("sale.report", "purchase.report"):
            with self.subTest(report=report):
                self.assertEqual(
                    self.env[report]._get_where_conditions(),
                    ["l.display_type IS NULL"],
                )

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

    def test_state_selection_stays_per_module(self):
        sale_states = dict(self.env["sale.report"]._fields["state"].selection)
        purchase_states = dict(self.env["purchase.report"]._fields["state"].selection)
        self.assertEqual(sale_states["done"], "Sales Order")
        self.assertEqual(purchase_states["done"], "Purchase Order")
        self.assertNotEqual(sale_states, purchase_states)
