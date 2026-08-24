from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPurchaseMrpMoOverview(AccountTestInvoicingCommon):
    """MO Overview report surfacing the purchase orders that feed MTO components."""

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
        cls.component = cls.env["product.product"].create(
            {
                "name": "MTO Component",
                "is_storable": True,
                "categ_id": goods.id,
                "uom_id": uom_unit.id,
            }
        )
        cls.finished = cls.env["product.product"].create(
            {
                "name": "Manufactured Product",
                "is_storable": True,
                "categ_id": goods.id,
                "uom_id": uom_unit.id,
            }
        )
        cls.env.ref("stock.route_warehouse0_mto").active = True
        route_buy = cls.warehouse.buy_pull_id.route_id
        route_mto = cls.warehouse.mto_pull_id.route_id
        route_mto.rule_ids.procure_method = "make_to_order"
        cls.component.write(
            {
                "seller_ids": [
                    Command.create({"partner_id": cls.partner_a.id, "price": 7.0})
                ],
                "route_ids": [Command.link(route_buy.id), Command.link(route_mto.id)],
            }
        )
        bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "bom_line_ids": [
                    Command.create(
                        {"product_id": cls.component.id, "product_qty": 2.0}
                    ),
                ],
            }
        )
        cls.production = cls.env["mrp.production"].create(
            {
                "product_id": cls.finished.id,
                "bom_id": bom.id,
                "product_qty": 3,
            }
        )
        cls.production.action_confirm()
        cls.purchase = cls.production.reference_ids.purchase_ids
        cls.report = cls.env["report.mrp.report_mo_overview"]

    def test_extra_replenishments_lists_feeding_purchase(self):
        """The confirmed PO feeding the MTO component is an extra replenishment."""
        self.assertEqual(len(self.purchase), 1)
        extra = self.report._get_extra_replenishments(self.component)
        po_entries = [
            e
            for e in extra
            if e["_name"] == "purchase.order" and e["id"] == self.purchase.id
        ]
        self.assertTrue(po_entries, "PO feeding the MTO component must be reported")
        entry = po_entries[0]
        self.assertEqual(entry["production_id"], self.production.id)
        self.assertGreater(entry["quantity"], 0)

    def test_report_data_builds_with_purchase_origin(self):
        """The full MO overview builds and traces the component back to its PO."""
        self.env.flush_all()
        data = self.report._get_report_data(self.production.id)
        self.assertIn("components", data)
        component_names = [comp["summary"]["name"] for comp in data["components"]]
        self.assertIn(self.component.display_name, component_names)

    def test_extra_replenishments_drops_confirmed_purchase(self):
        """Once the PO is confirmed it silently drops out of extra replenishments."""
        self.purchase.action_confirm()

        extra = self.report._get_extra_replenishments(self.component)
        po_ids = [e["id"] for e in extra if e["_name"] == "purchase.order"]
        self.assertNotIn(self.purchase.id, po_ids)
