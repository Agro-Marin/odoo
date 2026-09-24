from odoo.tests import common

from odoo.addons.stock.tests.common import DoneMoveCase


class TestStockLocationSearch(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.location = cls.env["stock.location"]
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.sublocation = cls.env["stock.location"].create(
            {
                "name": "Shelf 2",
                "barcode": 1201985,
                "location_id": cls.stock_location.id,
            }
        )
        cls.location_barcode_id = cls.sublocation.id
        cls.barcode = cls.sublocation.barcode
        cls.name = cls.sublocation.name

    def test_10_location_search_by_barcode(self):
        location_names = self.location.name_search(name=self.barcode)
        self.assertEqual(len(location_names), 1)
        location_id_found = location_names[0][0]
        self.assertEqual(self.location_barcode_id, location_id_found)

    def test_20_location_search_by_name(self):
        location_names = self.location.name_search(name=self.name)
        location_ids_found = [location_name[0] for location_name in location_names]
        self.assertTrue(self.location_barcode_id in location_ids_found)

    def test_30_location_search_wo_results(self):
        location_names = self.location.name_search(name="nonexistent")
        self.assertFalse(location_names)


class TestEmptyLocationSearch(DoneMoveCase):
    def test_is_empty_is_a_subquery_not_a_materialized_list(self):
        full = self.Location.create(
            {"name": "Occupied bin", "location_id": self.stock.id}
        )
        empty = self.Location.create(
            {"name": "Empty bin", "location_id": self.stock.id}
        )
        product = self.Product.create({"name": "Occupant", "is_storable": True})
        self.env["stock.quant"]._update_available_quantity(product, full, 1)
        self.env.flush_all()
        before = self.env.cr.sql_statement_count
        domain = self.Location._search_is_empty("in", [True])
        self.assertEqual(
            self.env.cr.sql_statement_count, before, "building the domain reads nothing"
        )
        self.assertNotIsInstance(domain[0][2], list)
        found = self.Location.search([("is_empty", "=", True)])
        self.assertIn(empty, found)
        self.assertNotIn(full, found)
