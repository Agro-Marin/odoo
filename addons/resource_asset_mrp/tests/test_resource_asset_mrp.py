from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResourceAssetMrp(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.machinery = cls.env.ref("resource_asset.kind_machinery")
        cls.press = cls.env["resource.asset"].create(
            {"name": "Press 1", "kind_id": cls.machinery.id}
        )

    def test_a_work_centre_created_on_a_machine_shares_its_resource(self):
        wc = self.env["mrp.workcenter"].create(
            {"name": "Pressing", "asset_id": self.press.id}
        )
        self.assertEqual(wc.resource_id, self.press.resource_id)
        self.assertEqual(self.press.workcenter_id, wc)
        self.assertEqual(wc.resource_calendar_id, self.press.resource_calendar_id)

    def test_attaching_later_swaps_the_resource_and_archives_the_orphan(self):
        wc = self.env["mrp.workcenter"].create({"name": "Pressing"})
        own = wc.resource_id
        wc.asset_id = self.press
        self.assertEqual(wc.resource_id, self.press.resource_id)
        self.assertFalse(own.active)
        wc.asset_id = False
        self.assertNotEqual(wc.resource_id, self.press.resource_id)
        self.assertTrue(wc.resource_id.active)

    def test_one_work_centre_per_machine(self):
        self.env["mrp.workcenter"].create(
            {"name": "Pressing", "asset_id": self.press.id}
        )
        with self.assertRaises(ValidationError):
            self.env["mrp.workcenter"].create(
                {"name": "Pressing 2", "asset_id": self.press.id}
            )

    def test_a_hard_booking_on_the_machine_moves_the_work_order(self):
        wc = self.env["mrp.workcenter"].create(
            {"name": "Pressing", "asset_id": self.press.id}
        )
        start = datetime(2026, 3, 2, 8, 0)
        self.env["resource.reservation"].create(
            {
                "name": "Machine down",
                "resource_id": self.press.resource_id.id,
                "date_start": start,
                "date_end": datetime(2026, 3, 2, 12, 0),
                "enforcement_mode": "hard",
            }
        )
        product = self.env["product.product"].create({"name": "Part"})
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "operation_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "press",
                            "workcenter_id": wc.id,
                            "time_cycle_manual": 60,
                        },
                    )
                ],
            }
        )
        mo = self.env["mrp.production"].create(
            {"product_id": product.id, "bom_id": bom.id, "date_start": start}
        )
        mo.action_confirm()
        mo.button_plan()
        self.assertGreaterEqual(
            mo.workorder_ids[0].date_start, datetime(2026, 3, 2, 12, 0)
        )
