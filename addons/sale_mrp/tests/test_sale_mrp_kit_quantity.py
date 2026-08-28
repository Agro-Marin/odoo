from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.base.tests.common import BaseCommon


@tagged("post_install", "-at_install")
class TestSaleMrpKitQuantity(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_unit = cls.quick_ref("uom.product_uom_unit")
        cls.uom_dozen = cls.quick_ref("uom.product_uom_dozen")
        cls.uom_gram = cls.quick_ref("uom.product_uom_gram")
        cls.uom_kg = cls.quick_ref("uom.product_uom_kgm")
        cls.categ = cls.env["product.category"].create(
            {
                "name": "Kit quantity",
                "property_cost_method": "fifo",
                "property_valuation": "real_time",
            }
        )
        cls.customer = cls.env["res.partner"].create({"name": "Kit customer"})

    @classmethod
    def _create_product(cls, name, standard_price=0.0):
        return cls.env["product.product"].create(
            {
                "name": name,
                "is_storable": True,
                "standard_price": standard_price,
                "categ_id": cls.categ.id,
            }
        )

    @classmethod
    def _create_kit(cls, name, components, product_qty=1.0):
        kit = cls._create_product(name)
        cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "product_qty": product_qty,
                "type": "phantom",
                "product_uom_id": cls.uom_unit.id,
                "bom_line_ids": [
                    Command.create(
                        {
                            "product_id": component.id,
                            "product_qty": qty,
                            **({"product_uom_id": uom.id} if uom else {}),
                        }
                    )
                    for component, qty, uom in components
                ],
            }
        )
        return kit

    def _sell(self, product, qty, uom=None):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_qty": qty,
                            **({"product_uom_id": uom.id} if uom else {}),
                        }
                    )
                ],
            }
        )
        order.action_confirm()
        return order

    def _deliver(self, order):
        for picking in order.picking_ids.filtered(
            lambda picking: picking.state not in ("done", "cancel")
        ):
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.button_validate()

    def test_accrual_date_cuts_the_kit_delivery(self):
        component = self._create_product("Accrual component", 10.0)
        kit = self._create_kit("Accrual kit", [(component, 2.0, None)])
        order = self._sell(kit, 5.0)
        self._deliver(order)
        line = order.line_ids

        yesterday = (fields.Date.today() - timedelta(days=1)).isoformat()
        as_of_yesterday = line.with_context(
            accrual_entry_date=yesterday
        )._prepare_qty_transferred()

        self.assertEqual(line.qty_transferred, 5.0)
        self.assertEqual(as_of_yesterday[line], 0.0)

    def test_prepare_and_compute_agree_on_a_late_bom(self):
        kit = self._create_product("Late kit")
        component = self._create_product("Late component", 10.0)
        order = self._sell(kit, 10.0)
        self._deliver(order)
        line = order.line_ids

        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "phantom",
                "product_uom_id": self.uom_unit.id,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 2.0})
                ],
            }
        )
        line.invalidate_recordset(["qty_transferred"])
        line._compute_qty_transferred()

        self.assertEqual(line._prepare_qty_transferred()[line], line.qty_transferred)

    def test_kit_delivered_in_batches_of_ten(self):
        component = self._create_product("Batch component", 1.0)
        kit = self._create_kit("Batch kit", [(component, 30.0, None)], product_qty=10.0)
        order = self._sell(kit, 20.0)
        line = order.line_ids

        self.assertEqual(line.move_ids.product_uom_qty, 60.0)

        self._deliver(order)

        self.assertEqual(line.qty_transferred, 20.0)

    def test_compute_uom_qty_scales_by_the_bom_batch(self):
        component = self._create_product("Scaled component")
        kit = self._create_kit(
            "Scaled kit", [(component, 30.0, None)], product_qty=10.0
        )
        order = self._sell(kit, 20.0)
        move = order.line_ids.move_ids

        self.assertEqual(order.line_ids.compute_uom_qty(3, move), 9.0)

    def test_compute_uom_qty_converts_the_bom_line_unit(self):
        component = self._create_product("Dozen component")
        kit = self._create_kit("Dozen kit", [(component, 2.0, self.uom_dozen)])
        order = self._sell(kit, 5.0)
        move = order.line_ids.move_ids

        self.assertEqual(move.product_uom_id, self.uom_unit)
        self.assertEqual(order.line_ids.compute_uom_qty(3, move), 72.0)

    def test_compute_uom_qty_reproduces_the_procurement_demand(self):
        cases = [
            ("batch of one", 1.0, 2.0, None, None, self.uom_unit, 4.0),
            ("batch of ten", 10.0, 30.0, None, None, self.uom_unit, 20.0),
            ("component in dozens", 1.0, 2.0, self.uom_dozen, None, self.uom_unit, 5.0),
            ("line in dozens", 1.0, 2.0, None, self.uom_dozen, self.uom_unit, 2.0),
            ("both", 10.0, 30.0, self.uom_dozen, None, self.uom_unit, 20.0),
            ("bom in dozens", 2.0, 3.0, None, None, self.uom_dozen, 4.0),
            ("component in grams", 1.0, 300.0, self.uom_gram, None, self.uom_unit, 7.0),
        ]

        for index, (
            label,
            bom_qty,
            component_qty,
            component_uom,
            line_uom,
            bom_uom,
            ordered,
        ) in enumerate(cases):
            with self.subTest(case=label):
                component = self._create_product(f"Shape component {index}")
                if component_uom == self.uom_gram:
                    component.uom_id = self.uom_kg
                kit = self._create_product(f"Shape kit {index}")
                self.env["mrp.bom"].create(
                    {
                        "product_tmpl_id": kit.product_tmpl_id.id,
                        "product_qty": bom_qty,
                        "type": "phantom",
                        "product_uom_id": bom_uom.id,
                        "bom_line_ids": [
                            Command.create(
                                {
                                    "product_id": component.id,
                                    "product_qty": component_qty,
                                    **(
                                        {"product_uom_id": component_uom.id}
                                        if component_uom
                                        else {}
                                    ),
                                }
                            )
                        ],
                    }
                )
                order = self._sell(kit, ordered, uom=line_uom)
                line = order.line_ids
                move = line.move_ids

                self.assertEqual(
                    line.compute_uom_qty(line.product_qty, move, False),
                    move.product_uom_qty,
                )

    def test_compute_uom_qty_without_a_bom_line_is_untouched(self):
        product = self._create_product("Plain product")
        order = self._sell(product, 7.0)
        move = order.line_ids.move_ids

        self.assertEqual(order.line_ids.compute_uom_qty(3, move), 3.0)

    def test_cogs_value_weighs_each_component_once(self):
        component_a = self._create_product("Cogs A", 10.0)
        component_b = self._create_product("Cogs B", 5.0)
        kit = self._create_kit(
            "Cogs kit", [(component_a, 2.0, None), (component_b, 3.0, None)]
        )
        order = self._sell(kit, 1.0)
        self._deliver(order)

        invoice = order._create_invoices()
        invoice_line = invoice.line_ids.filtered(
            lambda line: line.product_id == kit and line.display_type == "product"
        )

        self.assertEqual(invoice_line._get_cogs_value(), 35.0)

    def test_price_unit_answers_for_the_move_and_not_for_the_kit(self):
        """`_get_price_unit` is the moves' own product; the kit has its own hook.

        Asking the kit question through `_get_price_unit` is how a component
        came to be priced as a whole kit for `product._get_last_in()`,
        `_run_fifo` and every other valuation caller with no interest in kits.
        """
        for label, components in (
            ("two components", [(10.0, 2.0), (5.0, 3.0)]),
            ("one component", [(10.0, 2.0)]),
        ):
            with self.subTest(kit=label):
                products = [
                    self._create_product(f"{label} c{i}", price)
                    for i, (price, _qty) in enumerate(components)
                ]
                kit = self._create_kit(
                    f"Kit with {label}",
                    [
                        (p, qty, None)
                        for p, (_price, qty) in zip(products, components, strict=True)
                    ],
                )
                order = self._sell(kit, 1.0)
                self._deliver(order)
                done_moves = order.line_ids.move_ids.filtered(
                    lambda move: move.state == "done"
                )
                kit_cost = sum(price * qty for price, qty in components)

                for product, (price, _qty) in zip(products, components, strict=True):
                    self.assertEqual(
                        done_moves.filtered(
                            lambda move, product=product: move.product_id == product
                        )._get_price_unit(),
                        price,
                    )
                self.assertEqual(done_moves._get_sale_line_price_unit(), kit_cost)

    def test_undelivered_kit_bom_cannot_be_deleted(self):
        component = self._create_product("Advance component", 10.0)
        kit = self._create_kit("Advance kit", [(component, 2.0, None)])
        kit.invoice_policy = "ordered"
        order = self._sell(kit, 10.0)
        order._create_invoices().action_post()
        order.line_ids.invalidate_recordset(["invoice_state", "transfer_state"])
        self.assertEqual(order.line_ids.invoice_state, "done")
        self.assertEqual(order.line_ids.transfer_state, "to do")

        bom = self.env["mrp.bom"].search(
            [("product_tmpl_id", "=", kit.product_tmpl_id.id)]
        )

        with self.assertRaises(UserError):
            bom.unlink()

    def test_partially_invoiced_kit_bom_cannot_be_deleted(self):
        component = self._create_product("Guarded component", 10.0)
        kit = self._create_kit("Guarded kit", [(component, 2.0, None)])
        order = self._sell(kit, 10.0)
        self._deliver(order)
        invoice = order._create_invoices()
        invoice.line_ids.filtered(
            lambda line: line.product_id == kit and line.display_type == "product"
        ).quantity = 5.0
        invoice.action_post()
        order.line_ids.invalidate_recordset(["invoice_state"])
        self.assertEqual(order.line_ids.invoice_state, "partial")

        bom = self.env["mrp.bom"].search(
            [("product_tmpl_id", "=", kit.product_tmpl_id.id)]
        )

        with self.assertRaises(UserError):
            bom.unlink()

    def test_fully_invoiced_kit_bom_can_be_deleted(self):
        component = self._create_product("Freed component", 10.0)
        kit = self._create_kit("Freed kit", [(component, 2.0, None)])
        order = self._sell(kit, 10.0)
        self._deliver(order)
        order._create_invoices().action_post()
        order.line_ids.invalidate_recordset(["invoice_state"])
        self.assertEqual(order.line_ids.invoice_state, "done")

        bom = self.env["mrp.bom"].search(
            [("product_tmpl_id", "=", kit.product_tmpl_id.id)]
        )

        self.assertTrue(bom.unlink())
