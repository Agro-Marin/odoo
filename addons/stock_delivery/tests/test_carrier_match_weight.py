from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCarrierMatchWeightOnPicking(TransactionCase):
    """The carrier limits weigh a transfer in the product's reference unit."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {
                "name": "One kilo, one litre",
                "type": "consu",
                "weight": 1.0,
                "volume": 1.0,
                "uom_id": cls.env.ref("uom.product_uom_unit").id,
            }
        )
        service = cls.env["product.product"].create(
            {"name": "Freight", "type": "service"}
        )
        cls.carrier = cls.env["delivery.carrier"].create(
            {
                "name": "Ten kilos, ten litres",
                "delivery_type": "fixed",
                "product_id": service.id,
                "max_weight": 10.0,
                "max_volume": 10.0,
            }
        )
        picking_type = cls.env["stock.picking.type"].search(
            [("code", "=", "outgoing")], limit=1
        )
        cls.picking = cls.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": cls.env.ref("stock.stock_location_customers").id,
            }
        )
        cls.env["stock.move"].create(
            {
                "product_id": cls.product.id,
                "product_uom_qty": 2.0,
                "product_uom_id": cls.env.ref("uom.product_uom_dozen").id,
                "picking_id": cls.picking.id,
                "location_id": cls.picking.location_id.id,
                "location_dest_id": cls.picking.location_dest_id.id,
            }
        )

    def test_two_dozen_one_kilo_units_exceed_ten_kilos(self):
        # 2 Dozen of a 1 kg unit is 24 kg; weighing the move quantity said 2 kg.
        self.assertFalse(self.carrier._match_weight(self.picking))

    def test_two_dozen_one_litre_units_exceed_ten_litres(self):
        self.assertFalse(self.carrier._match_volume(self.picking))
