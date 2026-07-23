# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.fields import Command
from odoo.tests import TransactionCase, tagged

# subir-cobertura for the manufacturing expiry-confirmation flow: the expired-lot
# check, its context builder, and the confirmation wizard description.


@tagged("post_install", "-at_install")
class TestMrpExpiryConfirmation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {
                "name": "Perishable",
                "is_storable": True,
                "tracking": "lot",
                "use_expiration_date": True,
            }
        )
        cls.lot_1, cls.lot_2 = cls.env["stock.lot"].create(
            [
                {"name": "LOT-1", "product_id": cls.product.id},
                {"name": "LOT-2", "product_id": cls.product.id},
            ]
        )
        cls.production = cls.env["mrp.production"].create(
            {"product_id": cls.product.id, "product_qty": 1.0}
        )

    def test_check_expired_lots_skipped_by_context(self):
        """The expired-lot check is bypassed once the user confirmed."""
        self.assertFalse(
            self.production.with_context(skip_expired=True)._check_expired_lots()
        )

    def test_expired_context_targets_production_and_lots(self):
        """The expiry wizard context carries the production and lot defaults."""
        ctx = self.production._get_expired_context([self.lot_1.id, self.lot_2.id])
        self.assertEqual(ctx["default_production_ids"], self.production.ids)
        self.assertEqual(
            ctx["default_lot_ids"], [(6, 0, [self.lot_1.id, self.lot_2.id])]
        )

    def test_wizard_description_lists_multiple_lots(self):
        """With several expired lots the wizard shows the list and generic text."""
        wizard = self.env["expiry.picking.confirmation"].create(
            {
                "production_ids": [Command.set(self.production.ids)],
                "lot_ids": [Command.set([self.lot_1.id, self.lot_2.id])],
            }
        )
        self.assertTrue(wizard.show_lots)
        self.assertIn("expired components", wizard.description)

    def test_wizard_description_names_single_lot(self):
        """With a single expired lot the wizard names that lot in the message."""
        wizard = self.env["expiry.picking.confirmation"].create(
            {
                "production_ids": [Command.set(self.production.ids)],
                "lot_ids": [Command.set(self.lot_1.ids)],
            }
        )
        self.assertFalse(wizard.show_lots)
        self.assertIn("LOT-1", wizard.description)
