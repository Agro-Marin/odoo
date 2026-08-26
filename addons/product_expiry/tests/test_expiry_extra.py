import datetime

from odoo import fields
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.stock.tools.quantity import QuantityFilters


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
        wizard = self.env["expiry.picking.confirmation"].create(
            {"lot_ids": [Command.set(self.lot_1.ids)]}
        )
        self.assertFalse(wizard.show_lots)
        self.assertIn("EXP-1", wizard.description)

    def test_description_lists_multiple_lots(self):
        wizard = self.env["expiry.picking.confirmation"].create(
            {"lot_ids": [Command.set([self.lot_1.id, self.lot_2.id])]}
        )
        self.assertTrue(wizard.show_lots)
        self.assertIn("expired lots", wizard.description)


@tagged("post_install", "-at_install")
class TestExpirySettings(TransactionCase):
    def test_disabling_module_clears_delivery_slip_group(self):
        settings = self.env["res.config.settings"].new(
            {
                "module_product_expiry": False,
                "group_expiry_date_on_delivery_slip": True,
            }
        )
        settings._onchange_module_product_expiry()
        self.assertFalse(settings.group_expiry_date_on_delivery_slip)

    def test_disabling_lot_slip_clears_expiry_slip(self):
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
        self.assertGreaterEqual(self.env["stock.scheduler"]._get_tasks_to_do(), 1)


@tagged("post_install", "-at_install")
class TestExpiryQuantityScope(TransactionCase):
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
        product = self.env["product.product"].create(
            {
                "name": "Scope Expiry Tracked",
                "is_storable": True,
                "type": "consu",
                "tracking": "lot",
                "use_expiration_date": True,
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


@tagged("post_install", "-at_install")
class TestExpiryCategoryDefault(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.categ_expiry = cls.env["product.category"].create(
            {"name": "Perishable", "use_expiration_date": True}
        )
        cls.categ_plain = cls.env["product.category"].create(
            {"name": "Hardware", "use_expiration_date": False}
        )

    def _create_product(self, categ):
        return self.env["product.product"].create(
            {
                "name": "Batch",
                "is_storable": True,
                "tracking": "lot",
                "categ_id": categ.id,
            }
        )

    def test_category_seeds_the_product_flag(self):
        self.assertTrue(self._create_product(self.categ_expiry).use_expiration_date)
        self.assertFalse(self._create_product(self.categ_plain).use_expiration_date)

    def test_changing_category_repoints_the_product_flag(self):
        product = self._create_product(self.categ_plain)
        product.categ_id = self.categ_expiry
        self.assertTrue(product.use_expiration_date)
        product.categ_id = self.categ_plain
        self.assertFalse(product.use_expiration_date)

    def test_the_product_may_override_its_category(self):
        product = self._create_product(self.categ_plain)
        product.use_expiration_date = True
        self.assertTrue(product.use_expiration_date)
        product.invalidate_recordset()
        self.assertTrue(product.use_expiration_date)

    def test_an_untracked_product_ignores_its_category(self):
        product = self.env["product.product"].create(
            {"name": "Bolt", "is_storable": True, "tracking": "none"}
        )
        product.categ_id = self.categ_expiry
        self.assertFalse(product.use_expiration_date)

    def test_an_override_survives_a_storability_write(self):
        product = self._create_product(self.categ_plain)
        product.use_expiration_date = True
        product.is_storable = True
        self.assertTrue(product.use_expiration_date)
        product.name = "renamed"
        self.assertTrue(product.use_expiration_date)

    def test_an_explicit_value_wins_over_the_category_at_creation(self):
        product = self.env["product.product"].create(
            {
                "name": "Batch",
                "is_storable": True,
                "tracking": "lot",
                "categ_id": self.categ_expiry.id,
                "use_expiration_date": False,
            }
        )
        self.assertFalse(product.use_expiration_date)
