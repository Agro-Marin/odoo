# Part of Odoo. See LICENSE file for full copyright and licensing details.

import datetime

from odoo import fields
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.stock.tools.quantity import QuantityFilters

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
            {
                "name": "Batch",
                "is_storable": True,
                "tracking": "lot",
                "use_expiration_date": True,
            }
        )
        self.assertTrue(product.use_expiration_date)
        product.write({"tracking": "none"})
        self.assertFalse(product.use_expiration_date)

    def test_scheduler_declares_an_extra_task(self):
        """The expiry module adds one scheduler task to the run."""
        self.assertGreaterEqual(self.env["stock.scheduler"]._get_tasks_to_do(), 1)


@tagged("post_install", "-at_install")
class TestExpiryQuantityScope(TransactionCase):
    """The expired-stock narrowing, beside the module that owns `removal_date`.

    Lived in stock's `test_product_quantity_scope` while stock built the domain.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {"name": "Scope Expiry Product", "is_storable": True, "type": "consu"},
        )

    def test_the_scope_narrows_on_removal_date(self):
        param_date = fields.Datetime.now() + datetime.timedelta(days=30)
        scope = self.product.with_context(
            with_expiration=datetime.date.today(),
            fresh_qty_forecast=True,
            to_date="2020-01-01 00:00:00",
        )._prepare_quantities_scope(QuantityFilters(to_date=param_date))
        self.assertIsNotNone(scope.expired_quant)
        rendered = repr(scope.expired_quant)
        self.assertIn("removal_date", rendered)
        self.assertNotIn(
            "2020-01-01",
            rendered,
            "the cutoff must follow the parameter, not the context",
        )

    def test_removal_date_invalidates_the_quantity_fields(self):
        """`stock_quant_ids.removal_date` is declared here, so it must work here."""
        product = self.env["product.product"].create(
            {
                "name": "Scope Expiry Tracked",
                "is_storable": True,
                "type": "consu",
                "tracking": "lot",
                "use_expiration_date": True,
                # `removal_date` is the expiration date *minus* `removal_time`, so
                # a lot needs an expiration far enough out to be fresh at all. With
                # both left at zero it is born already past removal and the first
                # read below would be 0 for the wrong reason.
                "expiration_time": 60,
                "removal_time": 10,
            },
        )
        location = self.env["stock.warehouse"].search([], limit=1).lot_stock_id
        lot = self.env["stock.lot"].create(
            {"name": "SCOPE-EXP-1", "product_id": product.id},
        )
        quant = self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "location_id": location.id,
                "quantity": 6.0,
                "lot_id": lot.id,
            },
        )
        self.env.flush_all()
        scoped = product.with_context(with_expiration=fields.Datetime.now())
        self.assertEqual(scoped.qty_free, 6.0)

        lot.removal_date = fields.Datetime.now() - datetime.timedelta(days=1)
        self.assertEqual(
            quant.removal_date,
            lot.removal_date,
            "the quant's related column must have followed the lot",
        )
        self.assertEqual(
            scoped.qty_free,
            0.0,
            "stock past its removal date must leave qty_free without an "
            "explicit invalidation",
        )
