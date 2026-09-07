from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import Form

from odoo.addons.sale.tests.common import SaleCommon


class TestSaleMargin(SaleCommon):
    def test_sale_margin(self):
        """Test the sale_margin module in Odoo."""
        self.product.standard_price = 700.0
        order = self.empty_order

        order.line_ids = [
            Command.create(
                {
                    "price_unit": 1000.0,
                    "product_qty": 10.0,
                    "product_id": self.product.id,
                }
            ),
        ]
        # Confirm the sales order.
        order.action_confirm()
        # Verify that margin field gets bind with the value.
        self.assertEqual(order.margin, 3000.00, "Sales order profit should be 6000.00")
        self.assertEqual(order.margin_percent, 0.3, "Sales order margin should be 30%")

    def test_negative_margin(self):
        """Test the margin when sales price is less then cost."""
        order = self.empty_order
        self.service_product.standard_price = 40.0

        order.line_ids = [
            Command.create(
                {
                    "price_unit": 20.0,
                    "product_qty": 1.0,
                    "state": "draft",
                    "product_id": self.service_product.id,
                }
            ),
            Command.create(
                {
                    "price_unit": -100.0,
                    "purchase_price": 0.0,
                    "product_qty": 1.0,
                    "state": "draft",
                    "product_id": self.product.id,
                }
            ),
        ]
        # Confirm the sales order.
        order.action_confirm()
        # Verify that margin field of Sale Order Lines gets bind with the value.
        self.assertEqual(
            order.line_ids[0].margin, -20.00, "Sales order profit should be -20.00"
        )
        self.assertEqual(
            order.line_ids[0].margin_percent,
            -1,
            "Sales order margin percentage should be -100%",
        )
        self.assertEqual(
            order.line_ids[1].margin, -100.00, "Sales order profit should be -100.00"
        )
        self.assertEqual(
            order.line_ids[1].margin_percent,
            1.00,
            "Sales order margin should be 100% when the cost is zero and price defined",
        )
        # Verify that margin field gets bind with the value.
        self.assertEqual(order.margin, -120.00, "Sales order margin should be -120.00")
        self.assertEqual(order.margin_percent, 1.5, "Sales order margin should be 150%")

    def test_margin_no_cost(self):
        """Test the margin when cost is 0 margin percentage should always be 100%."""
        order = self.empty_order
        order.line_ids = [
            Command.create(
                {
                    "product_id": self.product.id,
                    "price_unit": 70.0,
                    "product_qty": 1.0,
                }
            )
        ]

        # Verify that margin field of Sale Order Lines gets bind with the value.
        self.assertEqual(
            order.line_ids[0].margin, 70.00, "Sales order profit should be 70.00"
        )
        self.assertEqual(
            order.line_ids[0].margin_percent,
            1.0,
            "Sales order margin percentage should be 100.00",
        )
        # Verify that margin field gets bind with the value.
        self.assertEqual(order.margin, 70.00, "Sales order profit should be 70.00")
        self.assertEqual(
            order.margin_percent, 1.00, "Sales order margin percentage should be 100.00"
        )

    def test_margin_considering_product_qty(self):
        """Test the margin and margin percentage when product with multiple quantity"""
        order = self.empty_order
        self.service_product.standard_price = 50.0

        order.line_ids = [
            Command.create(
                {
                    "price_unit": 100.0,
                    "product_qty": 3.0,
                    "product_id": self.service_product.id,
                }
            ),
            Command.create(
                {
                    "price_unit": -50.0,
                    "product_qty": 1.0,
                    "product_id": self.product.id,
                }
            ),
        ]

        # Confirm the sales order.
        order.action_confirm()
        # Verify that margin field of Sale Order Lines gets bind with the value.
        self.assertEqual(
            order.line_ids[0].margin, 150.00, "Sales order profit should be 150.00"
        )
        self.assertEqual(
            order.line_ids[0].margin_percent, 0.5, "Sales order margin should be 100%"
        )
        self.assertEqual(
            order.line_ids[1].margin, -50.00, "Sales order profit should be -50.00"
        )
        self.assertEqual(
            order.line_ids[1].margin_percent, 1.0, "Sales order margin should be 100%"
        )
        # Verify that margin field gets bind with the value.
        self.assertEqual(order.margin, 100.00, "Sales order profit should be 100.00")
        self.assertEqual(order.margin_percent, 0.4, "Sales order margin should be 40%")

    def test_sale_margin_order_copy(self):
        """When we copy a sales order, its margins should be update to meet the current costs"""
        order = self.empty_order
        self.pricelist.currency_id = self.env.company.currency_id
        # We buy at a specific price today and our margins go according to that
        self.product.standard_price = 500.0
        order.line_ids = [
            Command.create(
                {
                    "price_unit": 1000.0,
                    "product_qty": 10.0,
                    "product_id": self.product.id,
                }
            ),
        ]
        self.assertAlmostEqual(500.0, order.line_ids.purchase_price)
        self.assertAlmostEqual(5000.0, order.line_ids.margin)
        self.assertAlmostEqual(0.5, order.line_ids.margin_percent)
        # Later on, the cost of our product changes and so will the following sale
        # margins do.
        self.product.standard_price = 750.0
        following_sale = order.copy()
        self.assertAlmostEqual(750.0, following_sale.line_ids.purchase_price)
        self.assertAlmostEqual(2500.0, following_sale.line_ids.margin)
        self.assertAlmostEqual(0.25, following_sale.line_ids.margin_percent)

    def test_combo_master_line_has_no_phantom_margin(self):
        """A combo master line prices at 0 by design; it must not pick up its
        own product's cost as a phantom, revenue-less margin."""
        order = self.empty_order

        combo_item_product = self._create_product(name="Combo Item", standard_price=5.0)
        combo = self.env["product.combo"].create(
            {
                "name": "Test Combo",
                "combo_item_ids": [
                    Command.create({"product_id": combo_item_product.id})
                ],
            }
        )
        combo_product = self._create_product(
            name="Combo Master Product",
            type="combo",
            standard_price=12.0,
            combo_ids=[Command.link(combo.id)],
        )

        combo_line = self.env["sale.order.line"].create(
            {
                "order_id": order.id,
                "product_id": combo_product.id,
                "product_qty": 1.0,
            }
        )
        item_line = self.env["sale.order.line"].create(
            {
                "order_id": order.id,
                "product_id": combo_item_product.id,
                "product_qty": 1.0,
                "combo_item_id": combo.combo_item_ids.id,
                "linked_line_id": combo_line.id,
            }
        )

        self.assertEqual(
            combo_line.purchase_price,
            0.0,
            "The combo master line must not cost itself off its own product",
        )
        self.assertEqual(
            combo_line.margin,
            0.0,
            "The combo master line has no revenue of its own, so no margin either",
        )
        self.assertEqual(
            item_line.purchase_price,
            5.0,
            "The combo item line still costs off its own product as usual",
        )


DISCOUNT = 50

# A line of one unit whose cost is 50: for each margin the salesperson types,
# the unit price the line must end up with, and the resulting margin percent.
NO_TAX_MARGINS = [
    {"margin": 16.67, "margin_percent": 0.25, "price_unit": 66.67},
    {"margin": 25.0, "margin_percent": 1 / 3, "price_unit": 75.0},
    {"margin": 50.0, "margin_percent": 0.5, "price_unit": 100.0},
    {"margin": 75.0, "margin_percent": 0.6, "price_unit": 125.0},
    {"margin": 150.0, "margin_percent": 0.75, "price_unit": 200.0},
]
# The margin is computed off the subtotal, so a discount leaves it untouched
# and only scales the unit price the target margin needs.
NO_TAX_MARGINS_DISCOUNTED = [
    {**values, "price_unit": values["price_unit"] / (1 - DISCOUNT / 100)}
    for values in NO_TAX_MARGINS
]

# Same line, but its 50% tax is included in the price: the unit price now has
# to carry the tax on top of the price that yields the margin.
TAX_INCL_MARGINS = [
    {"margin": -16.67, "margin_percent": -0.5, "price_unit": 50.0},
    {"margin": 16.67, "margin_percent": 0.25, "price_unit": 100.0},
    {"margin": 33.33, "margin_percent": 0.4, "price_unit": 125.0},
    {"margin": 50.0, "margin_percent": 0.5, "price_unit": 150.0},
    {"margin": 83.33, "margin_percent": 0.625, "price_unit": 200.0},
    {"margin": 283.33, "margin_percent": 0.85, "price_unit": 500.0},
]
TAX_INCL_MARGINS_DISCOUNTED = [
    {**values, "price_unit": values["price_unit"] / (1 - DISCOUNT / 100)}
    for values in TAX_INCL_MARGINS
]


class TestSaleMarginEditable(SaleCommon):
    """The salesperson types the margin they want and the unit price follows."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._enable_discounts()

        cls.product_50_margin = cls._create_product(
            list_price=100.0, standard_price=50.0, taxes_id=[Command.set([])]
        )
        tax_group = cls.env["account.tax.group"].create({"name": "Tax Group A"})
        cls.tax_included, cls.tax_excluded = cls.env["account.tax"].create(
            [
                {
                    "name": "Tax with price include",
                    "amount": 50,
                    "price_include_override": "tax_included",
                    "tax_group_id": tax_group.id,
                },
                {
                    "name": "Tax with price exclude",
                    "amount": 50,
                    "price_include_override": "tax_excluded",
                    "tax_group_id": tax_group.id,
                },
            ]
        )

        cls.so = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "line_ids": [Command.create({"product_id": cls.product_50_margin.id})],
            }
        )
        cls.sol = cls.so.line_ids

    def _assert_margin_drives_price(self, fname, vals_list):
        """Type `fname` in the line form and check where the whole line lands."""
        with Form(self.so) as so_form, so_form.line_ids.edit(0) as sol_form:
            for values in vals_list:
                sol_form[fname] = values[fname]
                for key, expected in values.items():
                    self.assertAlmostEqual(
                        sol_form[key],
                        expected,
                        msg=f"{key} doesn't match ({fname}: {values[fname]})",
                        delta=0.01 if key == "margin_percent" else 0.02,
                    )

    def test_margin_drives_price_without_tax(self):
        self.assertRecordValues(
            self.sol,
            [
                {
                    "price_unit": 100.0,
                    "purchase_price": 50.0,
                    "margin": 50.0,
                    "margin_percent": 0.5,
                    "tax_ids": [],
                }
            ],
        )
        self._assert_margin_drives_price("margin", NO_TAX_MARGINS)
        self._assert_margin_drives_price("margin_percent", NO_TAX_MARGINS)

        self.sol.discount = DISCOUNT
        self._assert_margin_drives_price("margin", NO_TAX_MARGINS_DISCOUNTED)
        self._assert_margin_drives_price("margin_percent", NO_TAX_MARGINS_DISCOUNTED)

    def test_margin_drives_price_with_excluded_tax(self):
        self.product_50_margin.taxes_id = [Command.link(self.tax_excluded.id)]
        self.so._recompute_taxes()
        self.assertRecordValues(
            self.sol,
            [
                {
                    "price_unit": 100.0,
                    "purchase_price": 50.0,
                    "margin": 50.0,
                    "margin_percent": 0.5,
                    "tax_ids": [self.tax_excluded.id],
                }
            ],
        )
        # A tax excluded from the price cannot move the unit price the margin needs.
        self._assert_margin_drives_price("margin", NO_TAX_MARGINS)
        self._assert_margin_drives_price("margin_percent", NO_TAX_MARGINS)

        self.sol.discount = DISCOUNT
        self._assert_margin_drives_price("margin", NO_TAX_MARGINS_DISCOUNTED)
        self._assert_margin_drives_price("margin_percent", NO_TAX_MARGINS_DISCOUNTED)

    def test_margin_drives_price_with_included_tax(self):
        self.product_50_margin.taxes_id = [Command.link(self.tax_included.id)]
        self.so._recompute_taxes()
        self.assertRecordValues(
            self.sol,
            [
                {
                    "price_unit": 100.0,
                    "purchase_price": 50.0,
                    "margin": 16.67,
                    "margin_percent": 0.25,
                    "price_tax": 33.33,
                    "tax_ids": [self.tax_included.id],
                }
            ],
        )
        self._assert_margin_drives_price("margin", TAX_INCL_MARGINS)
        self._assert_margin_drives_price("margin_percent", TAX_INCL_MARGINS)

        self.sol.discount = DISCOUNT
        self._assert_margin_drives_price("margin", TAX_INCL_MARGINS_DISCOUNTED)
        self._assert_margin_drives_price("margin_percent", TAX_INCL_MARGINS_DISCOUNTED)

    def test_margin_percent_of_100_needs_a_free_line(self):
        """A line that costs something cannot be sold at a 100% margin."""
        with Form(self.so) as so_form, so_form.line_ids.edit(0) as sol_form:
            with self.assertRaises(UserError):
                sol_form["margin_percent"] = 1.0

    def test_margin_on_a_fully_discounted_line_is_refused(self):
        """A 100% discount leaves no unit price that could yield a margin.

        Production carries 434 such lines, so this is the path a salesperson
        actually reaches -- upstream divides by `1 - discount / 100` here and
        raises `ZeroDivisionError`.
        """
        self.sol.discount = 100.0
        with Form(self.so) as so_form, so_form.line_ids.edit(0) as sol_form:
            with self.assertRaises(UserError):
                sol_form["margin"] = 50.0

    def test_margin_on_a_zero_quantity_line_is_refused(self):
        """Nothing sold, nothing delivered: no unit price yields a margin.

        Production carries 550 accountable lines with `product_qty = 0`, some
        with `qty_transferred = 0` too -- upstream divides by the quantity here
        and raises `ZeroDivisionError`.
        """
        self.sol.product_qty = 0.0
        with Form(self.so) as so_form, so_form.line_ids.edit(0) as sol_form:
            with self.assertRaises(UserError):
                sol_form["margin"] = 50.0
