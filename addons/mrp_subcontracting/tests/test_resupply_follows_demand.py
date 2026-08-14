"""The component supply of a subcontracting production must follow its demand."""

from odoo.tests import Form, tagged

from odoo.addons.mrp_subcontracting.tests.common import TestMrpSubcontractingCommon


@tagged("post_install", "-at_install")
class TestResupplyFollowsDemand(TestMrpSubcontractingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.resupply_route = cls.env["stock.route"].search(
            [("name", "ilike", "resupply subcontractor")], limit=1
        )
        (cls.comp1 | cls.comp2).write(
            {"route_ids": [(4, cls.resupply_route.id)]},
        )

    def _order(self, quantity):
        order_form = Form(self.env["purchase.order"])
        order_form.partner_id = self.subcontractor_partner1
        order_form.picking_type_id = self.warehouse.in_type_id
        with order_form.line_ids.new() as line:
            line.product_id = self.finished
            line.product_qty = quantity
            line.price_unit = 100
        order = order_form.save()
        order.action_confirm()
        return order

    def _production(self):
        return self.env["mrp.production"].search([("bom_id", "=", self.bom.id)])

    def _resupplied(self, production, component):
        raw = production.move_raw_ids.filtered(lambda m: m.product_id == component)
        return sum(
            origin.product_qty
            for origin in raw.move_orig_ids
            if origin.state != "cancel"
        )

    def test_resupply_follows_a_raised_demand(self):
        order = self._order(1)
        production = self._production()
        self.assertEqual(self._resupplied(production, self.comp1), 1)

        order.line_ids.write({"product_qty": 2})
        self.env.invalidate_all()

        self.assertEqual(production.product_qty, 2, "the production is scaled")
        self.assertEqual(
            self._resupplied(production, self.comp1),
            2,
            "the subcontractor must be sent components for what they now build",
        )

    def test_every_component_follows(self):
        order = self._order(1)
        production = self._production()

        order.line_ids.write({"product_qty": 3})
        self.env.invalidate_all()

        for component in (self.comp1, self.comp2):
            self.assertEqual(
                self._resupplied(production, component),
                3,
                f"{component.display_name} was left behind",
            )

    def test_raising_twice_does_not_over_supply(self):
        order = self._order(1)
        production = self._production()

        order.line_ids.write({"product_qty": 4})
        order.line_ids.write({"product_qty": 4})
        self.env.invalidate_all()

        self.assertEqual(self._resupplied(production, self.comp1), 4)

    def test_recording_down_then_back_up_does_not_resupply_twice(self):
        """The production shrinks and grows again; the components were sent once.

        This is what a delta against the *previous demand* cannot see: the climb back
        looks exactly like a fresh increase. Measured against what the upstream moves
        carry, there is nothing missing. Toggling repeatedly used to add the difference
        every single time -- 3, then 5, then 6.
        """
        order = self._order(3)
        production = self._production()
        receipt_move = order.picking_ids.move_ids.filtered(lambda m: m.is_subcontract)

        for recorded in (1, 3, 2, 3):
            receipt_move.move_line_ids.write({"quantity": recorded})
            self.env.invalidate_all()
            self.assertEqual(
                self._resupplied(production, self.comp1),
                3,
                f"resupply moved after recording {recorded}",
            )

    def test_recording_a_quantity_does_not_order_more(self):
        """The suppression this reuses exists for exactly this case.

        A subcontractor telling us what they actually produced rescales the production,
        but is not a reason to resupply them again.
        """
        order = self._order(3)
        production = self._production()
        self.assertEqual(self._resupplied(production, self.comp1), 3)

        receipt_move = order.picking_ids.move_ids.filtered(lambda m: m.is_subcontract)
        receipt_move.move_line_ids.write({"quantity": 1})
        self.env.invalidate_all()

        self.assertEqual(production.product_qty, 1, "the production follows the record")
        self.assertEqual(
            self._resupplied(production, self.comp1),
            3,
            "recording less must not change what was already ordered",
        )
