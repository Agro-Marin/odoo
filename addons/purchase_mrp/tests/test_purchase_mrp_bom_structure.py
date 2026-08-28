import contextlib
from pathlib import Path

from odoo import Command
from odoo.modules import Manifest
from odoo.tests import TransactionCase, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPurchaseMrpBomStructure(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.env.user.group_ids = [
            Command.link(cls.env.ref("mrp.group_mrp_user").id),
            Command.link(cls.env.ref("purchase.group_purchase_user").id),
        ]
        goods = cls.env.ref("product.product_category_goods")
        uom_unit = cls.env.ref("uom.product_uom_unit")
        route_buy = cls.warehouse.buy_pull_id.route_id
        cls.buy_component = cls.env["product.product"].create(
            {
                "name": "Bought Component",
                "is_storable": True,
                "categ_id": goods.id,
                "uom_id": uom_unit.id,
                "seller_ids": [
                    Command.create(
                        {"partner_id": cls.partner_a.id, "price": 5.0, "delay": 3}
                    ),
                ],
                "route_ids": [Command.link(route_buy.id)],
            }
        )
        cls.finished = cls.env["product.product"].create(
            {
                "name": "Assembled Product",
                "is_storable": True,
                "categ_id": goods.id,
                "uom_id": uom_unit.id,
            }
        )
        cls.bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create(
                        {"product_id": cls.buy_component.id, "product_qty": 2.0}
                    ),
                ],
            }
        )
        cls.report = cls.env["report.mrp.report_bom_structure"]

    def test_bom_structure_reports_buy_route(self):
        data = self.report._get_report_data(bom_id=self.bom.id)
        component = data["lines"]["components"][0]
        self.assertEqual(component["availability_state"], "estimated")

    def test_bom_structure_in_stock_component_available(self):
        self.env["stock.quant"]._update_available_quantity(
            self.buy_component, self.warehouse.lot_stock_id, 100.0
        )
        data = self.report._get_report_data(bom_id=self.bom.id)
        component = data["lines"]["components"][0]
        self.assertEqual(component["availability_state"], "available")

    def test_bom_structure_route_alert_below_vendor_min_qty(self):
        self.buy_component.seller_ids.min_qty = 50

        data = self.report._get_report_data(bom_id=self.bom.id)

        component = data["lines"]["components"][0]
        self.assertTrue(component["route_alert"])


@tagged("post_install", "-at_install")
class TestPurchaseMrpAssets(TransactionCase):
    def test_own_static_sources_are_bundled(self):
        module_path = Path(Manifest.for_addon("purchase_mrp").path)
        sources = {
            f"purchase_mrp/{path.relative_to(module_path).as_posix()}"
            for path in (module_path / "static" / "src").rglob("*")
            if path.is_file() and path.suffix in (".js", ".scss", ".css", ".xml")
        }
        self.assertTrue(sources, "the module ships no static sources to check")

        IrAsset = self.env["ir.asset"]
        params = IrAsset._prepare_assets_params()
        bundled = set()
        for bundle in set(IrAsset.search([]).mapped("bundle")) | {
            key
            for manifest in Manifest.all_addon_manifests()
            for key in (manifest.get("assets") or {})
        }:
            with contextlib.suppress(Exception):
                bundled.update(
                    entry.path.lstrip("/")
                    for entry in IrAsset._get_asset_paths(bundle, params)
                )
        self.assertFalse(
            sources - bundled,
            "static sources declared by no bundle, so never served",
        )
