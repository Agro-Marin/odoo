from odoo.exceptions import UserError
from odoo.tests import TransactionCase


class TestScrapDiagnosesAnUnnamedLot(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Scrap = cls.env["stock.scrap"]
        cls.Quant = cls.env["stock.quant"]
        cls.stock = cls.env.ref("stock.stock_location_stock")
        cls.product = cls.env["product.product"].create(
            {
                "name": "Tracked scrap",
                "is_storable": True,
                "type": "consu",
                "tracking": "lot",
            }
        )
        cls.lot = cls.env["stock.lot"].create(
            {"name": "SCRAP-LOT-1", "product_id": cls.product.id}
        )

    def _scrap(self, **vals):
        return self.Scrap.create(
            dict(
                {
                    "product_id": self.product.id,
                    "scrap_qty": 2.0,
                    "location_id": self.stock.id,
                },
                **vals,
            )
        )

    def test_all_the_stock_is_under_lots_and_none_was_named(self):
        self.Quant._update_available_quantity(
            self.product, self.stock, 5.0, lot_id=self.lot
        )
        scrap = self._scrap()
        with self.assertRaises(UserError) as caught:
            scrap.action_validate()
        message = str(caught.exception)
        self.assertIn(self.lot.name, message)
        self.assertIn(self.product.display_name, message)

    def test_lot_less_stock_of_a_tracked_product_is_still_scrappable(self):
        self.Quant._update_available_quantity(self.product, self.stock, 3.0)
        scrap = self._scrap()
        self.assertTrue(scrap.check_available_qty())
        scrap.action_validate()
        self.env.flush_all()
        self.assertEqual(scrap.state, "done")

    def test_lot_less_stock_beside_lots_is_scrapped_from_the_lot_less_part(self):
        self.Quant._update_available_quantity(
            self.product, self.stock, 5.0, lot_id=self.lot
        )
        self.Quant._update_available_quantity(self.product, self.stock, 2.0)
        scrap = self._scrap()
        scrap.action_validate()
        self.env.flush_all()
        self.assertEqual(scrap.state, "done")
        self.assertEqual(
            sum(
                self.Quant.search(
                    [
                        ("product_id", "=", self.product.id),
                        ("location_id", "=", self.stock.id),
                        ("lot_id", "=", self.lot.id),
                    ]
                ).mapped("quantity")
            ),
            5.0,
            "the lot was not touched",
        )

    def test_naming_the_lot_scraps_from_it(self):
        self.Quant._update_available_quantity(
            self.product, self.stock, 5.0, lot_id=self.lot
        )
        scrap = self._scrap(lot_id=self.lot.id)
        scrap.action_validate()
        self.env.flush_all()
        self.assertEqual(scrap.state, "done")
        quants = self.Quant.search(
            [("product_id", "=", self.product.id), ("location_id", "=", self.stock.id)]
        )
        self.assertEqual(quants.lot_id, self.lot)
        self.assertEqual(sum(quants.mapped("quantity")), 3.0)

    def test_a_genuine_shortfall_still_reaches_the_wizard(self):
        self.Quant._update_available_quantity(self.product, self.stock, 1.0)
        scrap = self._scrap()
        action = scrap.action_validate()
        self.assertEqual(action["res_model"], "stock.warn.insufficient.qty.scrap")

    def test_an_untracked_product_is_unaffected(self):
        plain = self.env["product.product"].create(
            {"name": "Plain scrap", "is_storable": True, "type": "consu"}
        )
        self.Quant._update_available_quantity(plain, self.stock, 4.0)
        scrap = self.Scrap.create(
            {
                "product_id": plain.id,
                "scrap_qty": 1.0,
                "location_id": self.stock.id,
            }
        )
        scrap.action_validate()
        self.assertEqual(scrap.state, "done")


class TestScrapReferences(TransactionCase):
    def test_a_missing_sequence_is_named_rather_than_absorbed(self):
        self.env["ir.sequence"].search([("code", "=", "stock.scrap")]).unlink()
        product = self.env["product.product"].create(
            {"name": "Unsequenced", "is_storable": True, "type": "consu"}
        )
        stock = self.env.ref("stock.stock_location_stock")
        self.env["stock.quant"]._update_available_quantity(product, stock, 3.0)
        scrap = self.env["stock.scrap"].create(
            {"product_id": product.id, "scrap_qty": 1.0, "location_id": stock.id}
        )
        with self.assertRaises(UserError) as caught:
            scrap.do_scrap()
        self.assertIn(self.env.company.display_name, str(caught.exception))
        self.assertEqual(scrap.state, "draft")


class TestScrapBatchCost(TransactionCase):
    def _scrap_batch(self, size, tag):
        stock = self.env.ref("stock.stock_location_stock")
        products = self.env["product.product"].create(
            [
                {"name": "%s%d" % (tag, i), "is_storable": True, "type": "consu"}
                for i in range(size)
            ]
        )
        for product in products:
            self.env["stock.quant"]._update_available_quantity(product, stock, 50.0)
        self.env.flush_all()
        scraps = self.env["stock.scrap"].create(
            [
                {"product_id": product.id, "scrap_qty": 1.0, "location_id": stock.id}
                for product in products
            ]
        )
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        scraps.do_scrap()
        self.env.flush_all()
        return self.env.cr.sql_log_count - before

    def test_a_further_scrap_costs_less_than_a_first_one(self):
        small = self._scrap_batch(2, "sm")
        large = self._scrap_batch(20, "lg")
        marginal = (large - small) / 18
        self.assertLess(
            marginal,
            20,
            "each further scrap costs %.1f queries; the batch is being closed "
            "one record at a time again" % marginal,
        )
