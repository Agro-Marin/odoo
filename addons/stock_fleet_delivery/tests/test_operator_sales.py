from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestOperatorSales(TransactionCase):
    """A salesperson's trip is built from the orders he sold."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Fertilizer", "is_storable": True}
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.warehouse.lot_stock_id, 100
        )
        cls.customer = cls.env["res.partner"].create({"name": "Rancho El Sabino"})
        cls.salesperson = new_test_user(
            cls.env, login="fleet_seller", groups="sale.group_sale_salesman"
        )
        cls.colleague = new_test_user(
            cls.env, login="fleet_colleague", groups="sale.group_sale_salesman"
        )
        cls.seller_employee = cls.env["hr.employee"].create(
            {"name": "Seller", "user_id": cls.salesperson.id}
        )
        service = cls.env["product.product"].create(
            {"name": "Freight", "type": "service"}
        )
        cls.parcel = cls.env["delivery.carrier"].create(
            {
                "name": "Parcel",
                "delivery_type": "fixed",
                "product_id": service.id,
                "dispatch_mode": "third_party",
            }
        )

    def _sell(self, salesperson):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "user_id": salesperson.id,
                "warehouse_id": self.warehouse.id,
                "line_ids": [
                    Command.create({"product_id": self.product.id, "product_qty": 1})
                ],
            }
        )
        order.action_confirm()
        delivery = order.picking_ids
        self.assertEqual(delivery.state, "assigned")
        return delivery

    def _trip(self, operator):
        return self.env["stock.picking.batch"].create(
            {
                "operator_id": operator.id,
                "picking_type_id": self.warehouse.out_type_id.id,
            }
        )

    def test_the_trip_takes_the_ready_deliveries_its_operator_sold(self):
        his = self._sell(self.salesperson)
        other = self._sell(self.colleague)
        by_parcel = self._sell(self.salesperson)
        by_parcel.carrier_id = self.parcel

        trip = self._trip(self.seller_employee)
        trip.action_load_operator_sales()

        self.assertEqual(trip.picking_ids, his)
        self.assertFalse(other.batch_id, "a colleague's sale stays for his own trip")
        self.assertFalse(by_parcel.batch_id, "a parcel leaves with its carrier")

    def test_a_partly_reserved_delivery_stays_out(self):
        scarce = self.env["product.product"].create(
            {"name": "Scarce seed", "is_storable": True}
        )
        self.env["stock.quant"]._update_available_quantity(
            scarce, self.warehouse.lot_stock_id, 1
        )
        order = self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "user_id": self.salesperson.id,
                "warehouse_id": self.warehouse.id,
                "line_ids": [
                    Command.create({"product_id": scarce.id, "product_qty": 3})
                ],
            }
        )
        order.action_confirm()
        partial = order.picking_ids
        self.assertEqual(partial.move_ids.state, "partially_available")

        self._trip(self.seller_employee).action_load_operator_sales()

        self.assertFalse(partial.batch_id)

    def test_nothing_to_load_is_said_not_raised(self):
        action = self._trip(self.seller_employee).action_load_operator_sales()
        self.assertEqual(action["params"]["type"], "warning")

    def test_an_operator_without_user_has_no_sales_to_load(self):
        driver = self.env["hr.employee"].create({"name": "Driver"})
        with self.assertRaisesRegex(UserError, "operator with a user"):
            self._trip(driver).action_load_operator_sales()
