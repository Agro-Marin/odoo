from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRebatchingExcludesTheBatchesItIsHanded(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.picking_type = cls.env.ref("stock.picking_type_out")
        cls.picking_type.write({"auto_batch": True, "batch_group_by_partner": True})
        cls.partner = cls.env["res.partner"].create({"name": "Rebatch partner"})
        cls.product = cls.env["product.product"].create(
            {"name": "Rebatch product", "is_storable": True}
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 100
        )

    def _picking(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type.id,
                "partner_id": self.partner.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 1.0,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _batch_and_loose_picking(self):
        batch = self._picking().batch_id
        self.assertTrue(batch)
        loose = self._picking()
        self.assertEqual(loose.batch_id, batch)
        loose.batch_id = False
        return batch, loose

    def test_an_excluded_batch_is_not_joined(self):
        batch, loose = self._batch_and_loose_picking()

        loose._resolve_auto_batch(excluded_batches=batch)

        self.assertTrue(loose.batch_id)
        self.assertNotEqual(loose.batch_id, batch)

    def test_a_context_key_no_longer_excludes_a_batch(self):
        batch, loose = self._batch_and_loose_picking()

        loose.with_context(batches_to_validate=batch.ids)._resolve_auto_batch()

        self.assertEqual(loose.batch_id, batch)

    def test_rebatching_after_validation_passes_the_exclusion_on(self):
        batch, loose = self._batch_and_loose_picking()

        loose._rebatch_after_validation(excluded_batches=batch)

        self.assertNotEqual(loose.batch_id, batch)
