from odoo.fields import Command
from odoo.tests import Form

from .test_expiry_audit_2026_08 import ExpiryAuditCommon


class TestTheBackorderDecisionSurvivesTheExpiryWizard(ExpiryAuditCommon):
    def _partial_delivery_of_an_expired_lot(self):
        lot = self._lot("AUDIT-CHAIN", -2)
        self.env.flush_all()
        lot.write({"removal_date": False})
        self.env["stock.quant"]._update_available_quantity(
            self.product, self.stock_location, 5.0, lot_id=lot
        )
        self.env.flush_all()
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 8.0,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.picked = True
        self.env.flush_all()
        self.assertEqual(picking.move_ids.quantity, 5.0)
        return picking

    def _confirm_expired(self, action):
        self.assertEqual(action["res_model"], "expiry.picking.confirmation")
        return Form.from_action(self.env, action).save().process()

    def test_a_backorder_asked_for_is_still_created(self):
        picking = self._partial_delivery_of_an_expired_lot()
        self.warehouse.out_type_id.create_backorder = "ask"

        action = Form.from_action(self.env, picking.button_validate()).save().process()
        self._confirm_expired(action)

        self.assertEqual(picking.state, "done")
        self.assertEqual(picking.backorder_ids.move_ids.product_uom_qty, 3.0)

    def test_a_backorder_declined_is_still_declined(self):
        picking = self._partial_delivery_of_an_expired_lot()
        self.warehouse.out_type_id.create_backorder = "ask"

        wizard = Form.from_action(self.env, picking.button_validate()).save()
        self._confirm_expired(wizard.action_cancel_backorder())

        self.assertEqual(picking.state, "done")
        self.assertFalse(picking.backorder_ids)
