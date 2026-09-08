import datetime

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestForecastFreeStock(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.product = cls.env["product.product"].create(
            {
                "name": "Forecast Yoghurt",
                "is_storable": True,
                "tracking": "lot",
                "use_expiration_date": True,
                "expiration_time": 30,
                "removal_time": 5,
            }
        )
        cls.report = cls.env["stock.forecasted_product_product"]

    def _stock(self, name, expiration_offset_days, quantity):
        expiration_date = False
        if expiration_offset_days is not False:
            expiration_date = fields.Datetime.now() + datetime.timedelta(
                days=expiration_offset_days
            )
        lot = self.env["stock.lot"].create(
            {
                "name": name,
                "product_id": self.product.id,
                "expiration_date": expiration_date,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            self.product, self.stock_location, quantity, lot_id=lot
        )
        self.env.flush_all()
        return lot

    def _free_stock_rows(self):
        lines = self.report._get_report_data(product_ids=self.product.ids)["lines"]
        return [
            line
            for line in lines
            if line["replenishment_filled"]
            and not line["document_in"]
            and not line["document_out"]
            and not line["in_transit"]
        ]

    def test_the_dated_rows_alone_carry_the_whole_free_stock(self):
        self._stock("FFS-STALE", -10, 27.0)
        self._stock("FFS-FRESH", 30, 24.0)

        rows = self._free_stock_rows()
        expired = [row for row in rows if row.get("removal_date") == -1]
        fresh = [row for row in rows if row.get("removal_date") != -1]

        self.assertEqual([row["quantity"] for row in expired], [27.0])
        self.assertEqual([row["quantity"] for row in fresh], [24.0])
        self.assertEqual(
            sum(row["quantity"] for row in fresh),
            self.product.qty_free,
            "the rows the user reads must add up to the free stock in the header",
        )

    def test_no_row_reports_a_negative_quantity(self):
        self._stock("FFS-STALE2", -10, 27.0)
        self._stock("FFS-FRESH2", 30, 24.0)

        for row in self._free_stock_rows():
            self.assertGreaterEqual(
                row["quantity"],
                0.0,
                "expired stock is not part of free stock, so subtracting it from"
                " the undivided line drives that line below zero",
            )

    def test_stock_with_no_removal_date_keeps_its_own_row(self):
        self._stock("FFS-STALE3", -10, 27.0)
        self._stock("FFS-FRESH3", 30, 24.0)
        undated = self._stock("FFS-UNDATED", False, 10.0)
        self.assertFalse(
            undated.removal_date, "the scenario needs a lot with no removal date"
        )

        rows = self._free_stock_rows()
        fresh = [row for row in rows if row.get("removal_date") != -1]

        self.assertEqual(sorted(row["quantity"] for row in fresh), [10.0, 24.0])
        self.assertEqual(sum(row["quantity"] for row in fresh), self.product.qty_free)
