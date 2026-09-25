from odoo import Command
from odoo.tests import tagged

from odoo.addons.mrp_subcontracting.tests.common import TestMrpSubcontractingCommon


@tagged("post_install", "-at_install")
class TestSubcontractedBatchCancel(TestMrpSubcontractingCommon):
    def test_batch_cancel_cancels_work_orders_of_in_house_orders(self):
        workcenter = self.env["mrp.workcenter"].create({"name": "Press"})
        product, component = self.env["product.product"].create(
            [
                {"name": "In-house", "is_storable": True},
                {"name": "In-house part", "is_storable": True},
            ]
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                ],
                "operation_ids": [
                    Command.create({"name": "Press", "workcenter_id": workcenter.id})
                ],
            }
        )
        in_house, subcontracted = self.env["mrp.production"].create(
            [
                {"product_id": product.id, "bom_id": bom.id, "product_qty": 1}
                for _index in range(2)
            ]
        )
        (in_house | subcontracted).action_confirm()
        subcontracted.subcontractor_id = self.subcontractor_partner1
        self.assertEqual(in_house.workorder_ids.state, "ready")

        (in_house | subcontracted).action_cancel()

        self.assertEqual(in_house.state, "cancel")
        self.assertEqual(in_house.workorder_ids.state, "cancel")
