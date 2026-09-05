from datetime import datetime

from odoo.tests import TransactionCase, tagged
from odoo.tools import format_date


@tagged("post_install", "-at_install")
class TestPackageBarcodeExpiry(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.product = cls.env["product.product"].create(
            {
                "name": "Yoghurt",
                "is_storable": True,
                "tracking": "lot",
                "use_expiration_date": True,
            }
        )
        cls.plain = cls.env["product.product"].create(
            {"name": "Bolt", "is_storable": True, "tracking": "lot"}
        )

    def _package_with(self, product, lot_name, expiration_date=None):
        lot = self.env["stock.lot"].create(
            {
                "name": lot_name,
                "product_id": product.id,
                "expiration_date": expiration_date,
            }
        )
        package = self.env["stock.package"].create({})
        self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "location_id": self.stock_location.id,
                "lot_id": lot.id,
                "package_id": package.id,
                "quantity": 3,
            }
        )
        return package, lot

    def _render(self, package):
        return (
            self.env["ir.actions.report"]
            ._render_qweb_html("stock.action_report_package_barcode", package.ids)[0]
            .decode()
        )

    def test_label_prints_the_expiration_date(self):
        package, lot = self._package_with(
            self.product, "EXP-PKG-1", datetime(2026, 12, 31, 10, 0, 0)
        )
        html = self._render(package)
        self.assertIn("EXP-PKG-1", html)
        self.assertIn("Exp.", html)
        self.assertIn(format_date(self.env, lot.expiration_date), html)

    def test_label_of_a_lot_without_a_date_is_untouched(self):
        package, _lot = self._package_with(self.plain, "NO-EXP-PKG")
        html = self._render(package)
        self.assertIn("NO-EXP-PKG", html)
        self.assertNotIn("Exp.", html)
        self.assertIn(
            "d-inline-block p-2 text-end align-top",
            html,
            "the shared lot block keeps its padding when there is no date",
        )
