from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

BASE_PICKING = "odoo.addons.stock_picking_batch.models.stock_picking.StockPicking"
BASE_BATCH = (
    "odoo.addons.stock_picking_batch.models.stock_picking_batch.StockPickingBatch"
)


@tagged("post_install", "-at_install")
class TestCarrierBatchRules(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.picking_type = cls.env["stock.picking.type"].create(
            {
                "name": "DSPB batch out",
                "code": "outgoing",
                "sequence_code": "DSPB",
                "batch_group_by_carrier": True,
                "batch_max_weight": 10,
            }
        )
        cls.carrier = cls.env["delivery.carrier"].create(
            {
                "name": "DSPB carrier",
                "delivery_type": "fixed",
                "product_id": cls.env["product.product"]
                .create({"name": "DSPB ship cost", "type": "service"})
                .id,
            }
        )
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.customer_location = cls.env.ref("stock.stock_location_customers")

    def _picking(self, weight=0.0, carrier=None):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "carrier_id": carrier.id if carrier else False,
            }
        )
        if weight:
            picking.weight  # force the queued compute to run
            picking.flush_recordset(["weight"])
            self.env.cr.execute(
                "UPDATE stock_picking SET weight = %s WHERE id = %s",
                (weight, picking.id),
            )
            picking.invalidate_recordset(["weight"])
        return picking

    def test_pickings_domain_filters_by_carrier_when_grouping(self):
        """With carrier grouping on, candidate pickings filter by carrier."""
        picking = self._picking(carrier=self.carrier)
        self.assertIn("carrier_id", str(picking._get_possible_pickings_domain()))
        self.picking_type.batch_group_by_carrier = False
        self.assertNotIn("carrier_id", str(picking._get_possible_pickings_domain()))

    def test_auto_batch_description_appends_carrier(self):
        """The auto-batch description carries the carrier name."""
        picking = self._picking(carrier=self.carrier)
        self.assertIn(self.carrier.name, picking._get_auto_batch_description())

    def test_weight_limit_blocks_heavy_pairs(self):
        """Two pickings exceeding batch_max_weight cannot be batched."""
        heavy_1 = self._picking(weight=6.0, carrier=self.carrier)
        heavy_2 = self._picking(weight=6.0, carrier=self.carrier)  # 12 > 10
        light = self._picking(weight=3.0, carrier=self.carrier)  # 9 <= 10
        with patch(f"{BASE_PICKING}._is_auto_batchable", return_value=True):
            self.assertFalse(heavy_1._is_auto_batchable(heavy_2))
            self.assertTrue(heavy_1._is_auto_batchable(light))

    def test_no_weight_limit_always_batchable(self):
        """A zero max weight disables the weight guard (boundary)."""
        self.picking_type.batch_max_weight = 0
        heavy_1 = self._picking(weight=6.0, carrier=self.carrier)
        heavy_2 = self._picking(weight=6.0, carrier=self.carrier)
        with patch(f"{BASE_PICKING}._is_auto_batchable", return_value=True):
            self.assertTrue(heavy_1._is_auto_batchable(heavy_2))

    def test_batch_merge_respects_accumulated_weight(self):
        """A batch rejects pickings that push it over the weight limit."""
        first = self._picking(weight=6.0, carrier=self.carrier)
        batch = self.env["stock.picking.batch"].create(
            {
                "picking_type_id": self.picking_type.id,
                "picking_ids": [(6, 0, first.ids)],
            }
        )
        heavy = self._picking(weight=6.0, carrier=self.carrier)  # 12 > 10
        light = self._picking(weight=3.0, carrier=self.carrier)  # 9 <= 10
        with patch(f"{BASE_BATCH}._is_auto_mergeable", return_value=True):
            self.assertFalse(
                batch._is_auto_mergeable(**heavy._get_auto_merge_amounts())
            )
            self.assertTrue(batch._is_auto_mergeable(**light._get_auto_merge_amounts()))

    def test_the_carrier_key_reaches_the_wave_paths_too(self):
        """batch_group_by_carrier is a grouping criterion, not a batch-only flag."""
        criteria = self.picking_type._get_grouping_criteria()
        self.assertIn("batch_group_by_carrier", criteria)
        criterion = criteria["batch_group_by_carrier"]
        self.assertEqual(criterion.picking_path, "carrier_id")
        self.assertEqual(criterion.batch_path, "picking_ids.carrier_id")
        self.assertEqual(criterion.line_path, "picking_id.carrier_id")

    def test_a_negative_weight_limit_is_refused(self):
        """The limit bounds a loop, so it may not be negative."""
        with self.assertRaises(ValidationError):
            self.picking_type.batch_max_weight = -1
