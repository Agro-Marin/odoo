from odoo import Command
from odoo.tests import TransactionCase


class TestRepairCreateComputes(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {"name": "Returned mower", "is_storable": True}
        )
        stock = cls.env.ref("stock.stock_location_stock")
        customers = cls.env.ref("stock.stock_location_customers")
        cls.picking = cls.env["stock.picking"].create(
            {
                "picking_type_id": cls.env.ref("stock.picking_type_out").id,
                "location_id": stock.id,
                "location_dest_id": customers.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": cls.product.id,
                            "product_uom_qty": 3.0,
                            "quantity": 3.0,
                            "location_id": stock.id,
                            "location_dest_id": customers.id,
                        }
                    )
                ],
            }
        )

    def test_a_repair_created_from_a_picking_repairs_the_picked_quantity(self):
        repair = self.env["repair.order"].create(
            {"product_id": self.product.id, "picking_id": self.picking.id}
        )

        self.assertEqual(repair.product_qty, 3.0)

    def test_a_repair_without_a_picking_repairs_one_unit(self):
        repair = self.env["repair.order"].create({"product_id": self.product.id})

        self.assertEqual(repair.product_qty, 1.0)

    def test_an_explicit_quantity_wins_over_the_picking(self):
        repair = self.env["repair.order"].create(
            {
                "product_id": self.product.id,
                "picking_id": self.picking.id,
                "product_qty": 2.0,
            }
        )

        self.assertEqual(repair.product_qty, 2.0)

    def test_a_repair_for_another_allowed_company_uses_that_companys_operation_type(
        self,
    ):
        company_b = self.env["res.company"].create({"name": "Repair shop B"})
        self.env.user.company_ids |= company_b
        repairs = self.env["repair.order"].with_context(
            allowed_company_ids=[self.env.company.id, company_b.id]
        )

        repair = repairs.create(
            {"product_id": self.product.id, "company_id": company_b.id}
        )

        self.assertEqual(repair.picking_type_id.company_id, company_b)
        self.assertEqual(repair.picking_type_id.code, "repair_operation")
