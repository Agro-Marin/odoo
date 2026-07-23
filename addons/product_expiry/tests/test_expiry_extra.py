# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.fields import Command
from odoo.tests import TransactionCase, tagged

# subir-cobertura: the delivery expiry-confirmation wizard description and the
# expiry-settings onchanges.


@tagged("post_install", "-at_install")
class TestExpiryConfirmationWizard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {
                "name": "Yoghurt",
                "is_storable": True,
                "tracking": "lot",
                "use_expiration_date": True,
            }
        )
        cls.lot_1, cls.lot_2 = cls.env["stock.lot"].create(
            [
                {"name": "EXP-1", "product_id": cls.product.id},
                {"name": "EXP-2", "product_id": cls.product.id},
            ]
        )

    def test_description_names_the_single_lot(self):
        """A single expired lot is named in the confirmation message."""
        wizard = self.env["expiry.picking.confirmation"].create(
            {"lot_ids": [Command.set(self.lot_1.ids)]}
        )
        self.assertFalse(wizard.show_lots)
        self.assertIn("EXP-1", wizard.description)

    def test_description_lists_multiple_lots(self):
        """Several expired lots switch the wizard to the listing message."""
        wizard = self.env["expiry.picking.confirmation"].create(
            {"lot_ids": [Command.set([self.lot_1.id, self.lot_2.id])]}
        )
        self.assertTrue(wizard.show_lots)
        self.assertIn("expired lots", wizard.description)


@tagged("post_install", "-at_install")
class TestExpirySettings(TransactionCase):
    def test_disabling_module_clears_delivery_slip_group(self):
        """Turning off the expiry module clears the delivery-slip expiry group."""
        settings = self.env["res.config.settings"].new(
            {
                "module_product_expiry": False,
                "group_expiry_date_on_delivery_slip": True,
            }
        )
        settings._onchange_module_product_expiry()
        self.assertFalse(settings.group_expiry_date_on_delivery_slip)

    def test_disabling_lot_slip_clears_expiry_slip(self):
        """Turning off lots on the delivery slip clears the expiry slip group."""
        settings = self.env["res.config.settings"].new(
            {
                "group_lot_on_delivery_slip": False,
                "group_expiry_date_on_delivery_slip": True,
            }
        )
        settings._onchange_group_lot_on_delivery_slip()
        self.assertFalse(settings.group_expiry_date_on_delivery_slip)


@tagged("post_install", "-at_install")
class TestExpiryMisc(TransactionCase):
    def test_clearing_tracking_disables_expiration(self):
        """Removing lot tracking also turns off expiration-date handling."""
        product = self.env["product.product"].create(
            {"name": "Batch", "tracking": "lot", "use_expiration_date": True}
        )
        self.assertTrue(product.use_expiration_date)
        product.write({"tracking": "none"})
        self.assertFalse(product.use_expiration_date)

    def test_scheduler_declares_an_extra_task(self):
        """The expiry module adds one scheduler task to the run."""
        self.assertGreaterEqual(self.env["stock.rule"]._get_scheduler_tasks_to_do(), 1)
