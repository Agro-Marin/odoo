from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestKitQtyTransferred(AccountTestInvoicingCommon):
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
                            "date_commitment": fields.Datetime.now(),
                        }
                    )
                ],
            },
        )
        po.action_confirm()
        return po

    def test_prepare_qty_transferred_full_kit_receipt(self):
        po = self._make_confirmed_kit_po()
        picking = po.picking_ids
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.move_ids.picked = True
        picking.button_validate()

        res = po.line_ids._prepare_qty_transferred()
        self.assertEqual(res[po.line_ids], 1.0)

    def test_prepare_qty_transferred_unreceived_kit_is_zero(self):
        po = self._make_confirmed_kit_po()

        res = po.line_ids._prepare_qty_transferred()
        self.assertEqual(res[po.line_ids], 0.0)

    def test_prepare_qty_transferred_partial_kit_receipt_is_zero(self):
        po = self._make_confirmed_kit_po()
        picking = po.picking_ids
        for move in picking.move_ids:
            is_a = move.product_id == self.component_a
            move.quantity = move.product_uom_qty if is_a else 0
        picking.move_ids.picked = True
        picking.button_validate()

        res = po.line_ids._prepare_qty_transferred()
        self.assertEqual(res[po.line_ids], 0.0)


@tagged("post_install", "-at_install")
class TestMoPurchaseLinks(AccountTestInvoicingCommon):
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
                            "date_commitment": fields.Datetime.now(),
                        }
                    )
                ],
            },
        )

    def test_get_purchase_orders_follows_raw_move_links(self):
        po = self._make_po(self.raw_a)
        self.mo.move_raw_ids[0].purchase_line_id = po.line_ids.id

        self.assertEqual(self.mo._get_purchase_orders(), po)
        self.assertEqual(self.mo.purchase_order_count, 1)

    def test_action_view_multiple_purchase_orders_lists_them(self):
        po_a = self._make_po(self.raw_a)
        po_b = self._make_po(self.raw_b)
        moves = self.mo.move_raw_ids
        moves[0].purchase_line_id = po_a.line_ids.id
        moves[1].created_purchase_line_ids = [Command.set(po_b.line_ids.ids)]

        action = self.mo.action_view_purchase_orders()
        self.assertEqual(action["view_mode"], "list,form")
        self.assertCountEqual(action["domain"][0][2], [po_a.id, po_b.id])

    def test_document_iterate_key_prefers_created_purchase_lines(self):
        po = self._make_po(self.raw_a)
        move = self.mo.move_raw_ids[0]
        move.created_purchase_line_ids = [Command.set(po.line_ids.ids)]

        self.assertEqual(
            self.mo._get_document_iterate_key(move), "created_purchase_line_ids"
        )

    def test_purchase_order_count_denied_without_purchase_group(self):
        user = new_test_user(
            self.env,
            login="mo_purchase_links_user",
            groups="base.group_user,mrp.group_mrp_user",
        )

        with self.assertRaises(AccessError):
            self.mo.with_user(user).read(["purchase_order_count"])


@tagged("post_install", "-at_install")
class TestBomCostShareGuard(AccountTestInvoicingCommon):
    def test_negative_cost_share_rejected(self):
        product = self.env["product.product"].create(
            {"name": "KI Guarded kit", "is_storable": True},
        )
        component = self.env["product.product"].create(
            {"name": "KI Guarded comp", "is_storable": True},
        )
        with self.assertRaises(ValidationError):
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

    def _kit_bom(self, shares):
        kit = self.env["product.product"].create(
            {"name": "CS kit", "is_storable": True},
        )
        components = self.env["product.product"].create(
            [{"name": f"CS comp {i}", "is_storable": True} for i in range(len(shares))],
        )
        return self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "phantom",
                "bom_line_ids": [
                    Command.create(
                        {
                            "product_id": component.id,
                            "product_qty": 1.0,
                            "cost_share": share,
                        },
                    )
                    for component, share in zip(components, shares, strict=True)
                ],
            },
        )

    def test_total_is_a_set_invariant_not_a_line_one(self):
        bom = self._kit_bom([60.0, 40.0])
        first, second = bom.bom_line_ids

        first.cost_share = 30.0
        second.cost_share = 70.0
        bom.flush_recordset()
        self.assertEqual(bom.bom_line_ids.mapped("cost_share"), [30.0, 70.0])

        with self.assertRaises(ValidationError):
            bom.write(
                {
                    "bom_line_ids": [
                        Command.update(first.id, {"cost_share": 30.0}),
                        Command.update(second.id, {"cost_share": 30.0}),
                    ]
                }
            )

    def test_negative_cost_share_rejected_on_direct_line_write(self):
        bom = self._kit_bom([60.0, 40.0])
        with self.assertRaises(ValidationError):
            bom.bom_line_ids[0].cost_share = -10.0
            bom.flush_recordset()

    def test_zero_cost_shares_stay_valid(self):
        bom = self._kit_bom([0.0, 0.0])
        self.assertEqual(sum(bom.bom_line_ids.mapped("cost_share")), 0.0)

    def test_variant_specific_bom_checks_only_its_own_variant(self):
        colour = self.env["product.attribute"].create(
            {
                "name": "CS colour",
                "value_ids": [
                    Command.create({"name": "red"}),
                    Command.create({"name": "blue"}),
                ],
            },
        )
        template = self.env["product.template"].create(
            {
                "name": "CS variant kit",
                "is_storable": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": colour.id,
                            "value_ids": [Command.set(colour.value_ids.ids)],
                        },
                    )
                ],
            },
        )
        component = self.env["product.product"].create(
            {"name": "CS variant comp", "is_storable": True},
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": template.id,
                "product_id": template.product_variant_ids[0].id,
                "product_qty": 1.0,
                "type": "phantom",
                "bom_line_ids": [
                    Command.create(
                        {
                            "product_id": component.id,
                            "product_qty": 1.0,
                            "cost_share": 100.0,
                        },
                    )
                ],
            },
        )
        self.assertEqual(bom.bom_line_ids.cost_share, 100.0)

    def test_kit_is_resolved_against_the_line_company_not_the_reader(self):
        other_company = self.env["res.company"].create({"name": "Kit co B"})
        kit, here, there = self.env["product.product"].create(
            [
                {"name": "Two-company kit", "is_storable": True},
                {"name": "Component here", "is_storable": True},
                {"name": "Component there", "is_storable": True},
            ],
        )

        def kit_bom(company, component, qty):
            return (
                self.env["mrp.bom"]
                .with_company(company)
                .create(
                    {
                        "product_tmpl_id": kit.product_tmpl_id.id,
                        "product_qty": 1.0,
                        "type": "phantom",
                        "company_id": company.id,
                        "bom_line_ids": [
                            Command.create(
                                {"product_id": component.id, "product_qty": qty}
                            )
                        ],
                    },
                )
            )

        kit_bom(self.env.company, here, 2.0)
        bom_there = kit_bom(other_company, there, 7.0)

        order = self.env["purchase.order"].create(
            {
                "partner_id": self.partner.id,
                "company_id": other_company.id,
                "line_ids": [
                    Command.create({"product_id": kit.id, "product_qty": 2.0})
                ],
            },
        )
        self.assertNotEqual(order.company_id, self.env.company)

        move_dests = self.env["stock.move"].create(
            {
                "product_id": there.id,
                "product_uom_id": there.uom_id.id,
                "product_uom_qty": 14.0,
                "bom_line_id": bom_there.bom_line_ids[0].id,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": self.env.ref("stock.stock_location_stock").id,
                "company_id": other_company.id,
            },
        )
        self.assertEqual(
            order.line_ids._get_stock_move_dests_initial_demand(move_dests),
            2.0,
            "the other company's BoM should size the demand, not ours",
        )
