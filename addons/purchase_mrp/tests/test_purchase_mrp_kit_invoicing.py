"""Kit invoiced-qty preparation, MO→PO traceability and cost-share guard."""

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestKitQtyTransferred(AccountTestInvoicingCommon):
    """_prepare_qty_transferred over phantom-BOM purchase lines."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "KI kit vendor"})
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.component_a, cls.component_b, cls.kit = (
            cls.env["product.product"].create(
                {
                    "name": name,
                    "is_storable": True,
                    "uom_id": cls.uom_unit.id,
                    "purchase_ok": True,
                }
            )
            for name in ("KI Comp A", "KI Comp B", "KI Kit")
        )
        cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.kit.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "phantom",
                "bom_line_ids": [
                    Command.create(
                        {"product_id": cls.component_a.id, "product_qty": 2}
                    ),
                    Command.create(
                        {"product_id": cls.component_b.id, "product_qty": 1}
                    ),
                ],
            },
        )

    def _make_confirmed_kit_po(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "name": self.kit.name,
                            "product_id": self.kit.id,
                            "product_qty": 1,
                            "product_uom_id": self.kit.uom_id.id,
                            "price_unit": 60.0,
                            "date_planned": fields.Datetime.now(),
                        }
                    )
                ],
            },
        )
        po.action_confirm()
        return po

    def test_prepare_qty_transferred_full_kit_receipt(self):
        """Receiving every component values the kit line at its full qty."""
        po = self._make_confirmed_kit_po()
        picking = po.picking_ids
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.move_ids.picked = True
        picking.button_validate()

        res = po.line_ids._prepare_qty_transferred()
        self.assertEqual(res[po.line_ids], 1.0)

    def test_prepare_qty_transferred_unreceived_kit_is_zero(self):
        """With no done component move the kit line values at zero."""
        po = self._make_confirmed_kit_po()

        res = po.line_ids._prepare_qty_transferred()
        self.assertEqual(res[po.line_ids], 0.0)


@tagged("post_install", "-at_install")
class TestMoPurchaseLinks(AccountTestInvoicingCommon):
    """MO→PO traceability: _get_purchase_orders and the smart-button action."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "KI mo vendor"})
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.raw_a, cls.raw_b, cls.manufactured = (
            cls.env["product.product"].create(
                {
                    "name": name,
                    "is_storable": True,
                    "uom_id": cls.uom_unit.id,
                    "purchase_ok": True,
                }
            )
            for name in ("KI Raw A", "KI Raw B", "KI Finished")
        )
        bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.manufactured.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": cls.raw_a.id, "product_qty": 1}),
                    Command.create({"product_id": cls.raw_b.id, "product_qty": 1}),
                ],
            },
        )
        cls.mo = cls.env["mrp.production"].create(
            {
                "product_id": cls.manufactured.id,
                "product_qty": 1.0,
                "bom_id": bom.id,
            },
        )
        cls.mo.action_confirm()

    def _make_po(self, product):
        return self.env["purchase.order"].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "name": product.name,
                            "product_id": product.id,
                            "product_qty": 1,
                            "product_uom_id": product.uom_id.id,
                            "price_unit": 10.0,
                            "date_planned": fields.Datetime.now(),
                        }
                    )
                ],
            },
        )

    def test_get_purchase_orders_follows_raw_move_links(self):
        """POs are collected from purchase_line_id links on raw moves."""
        po = self._make_po(self.raw_a)
        self.mo.move_raw_ids[0].purchase_line_id = po.line_ids.id

        self.assertEqual(self.mo._get_purchase_orders(), po)
        self.assertEqual(self.mo.purchase_order_count, 1)

    def test_action_view_multiple_purchase_orders_lists_them(self):
        """Two linked POs switch the smart button to the list view."""
        po_a = self._make_po(self.raw_a)
        po_b = self._make_po(self.raw_b)
        moves = self.mo.move_raw_ids
        moves[0].purchase_line_id = po_a.line_ids.id
        moves[1].created_purchase_line_ids = [Command.set(po_b.line_ids.ids)]

        action = self.mo.action_view_purchase_orders()
        self.assertEqual(action["view_mode"], "list,form")
        self.assertCountEqual(action["domain"][0][2], [po_a.id, po_b.id])

    def test_document_iterate_key_prefers_created_purchase_lines(self):
        """A raw move with created purchase lines iterates through them."""
        po = self._make_po(self.raw_a)
        move = self.mo.move_raw_ids[0]
        move.created_purchase_line_ids = [Command.set(po.line_ids.ids)]

        self.assertEqual(
            self.mo._get_document_iterate_key(move), "created_purchase_line_ids"
        )


@tagged("post_install", "-at_install")
class TestBomCostShareGuard(AccountTestInvoicingCommon):
    """Negative cost-share components are rejected at BOM validation."""

    def test_negative_cost_share_rejected(self):
        product = self.env["product.product"].create(
            {"name": "KI Guarded kit", "is_storable": True},
        )
        component = self.env["product.product"].create(
            {"name": "KI Guarded comp", "is_storable": True},
        )
        with self.assertRaises(UserError):
            self.env["mrp.bom"].create(
                {
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "product_qty": 1.0,
                    "type": "phantom",
                    "bom_line_ids": [
                        Command.create(
                            {"product_id": component.id, "cost_share": -10.0}
                        )
                    ],
                },
            )
