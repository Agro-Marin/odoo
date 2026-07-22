"""Tests for carrier grouping and weight limits in auto-batching.

The weight-guard tests isolate this module's layer: the base
stock_picking_batch eligibility is patched to True and the computed
picking weight is pinned at SQL level, so only the delivery guard
decides.
"""

from unittest.mock import patch

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
            # weight is a stored compute fed by move lines; settle the pending
            # compute first (or it would overwrite the pin on next access),
            # then pin it at SQL level so only this module's guard is under test.
            picking.weight  # noqa: B018 — force the queued compute to run
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
        with patch(f"{BASE_BATCH}._is_picking_auto_mergeable", return_value=True):
            self.assertFalse(batch._is_picking_auto_mergeable(heavy))
            self.assertTrue(batch._is_picking_auto_mergeable(light))
