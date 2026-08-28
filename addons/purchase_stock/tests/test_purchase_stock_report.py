from odoo.tests import Form

from odoo.addons.stock.tests.test_report import TestReportsCommon


class TestPurchaseStockReports(TestReportsCommon):
    def test_report_forecast_1_purchase_order_multi_receipt(self):
        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner
        with po_form.line_ids.new() as line:
            line.product_id = self.product
            line.product_qty = 5
        po = po_form.save()

        _, docs, lines = self.get_report_forecast(
            product_template_ids=self.product_template.ids
        )
        draft_picking_qty_in = self.sum_dicts(docs["product"], "draft_picking_qty")[
            "in"
        ]
        draft_purchase_qty = self.sum_dicts(docs["product"], "draft_purchase_qty")["in"]
        pending_qty_in = self.sum_dicts(docs["product"], "qty")["in"]
        self.assertEqual(len(lines), 1, "Must have 1 line for now.")
        self.assertEqual(draft_picking_qty_in, 0)
        self.assertEqual(draft_purchase_qty, 5)
        self.assertEqual(pending_qty_in, 5)

        po.action_confirm()
        _, docs, lines = self.get_report_forecast(
            product_template_ids=self.product_template.ids
        )
        draft_picking_qty_in = self.sum_dicts(docs["product"], "draft_picking_qty")[
            "in"
        ]
        draft_purchase_qty = self.sum_dicts(docs["product"], "draft_purchase_qty")["in"]
        pending_qty_in = self.sum_dicts(docs["product"], "qty")["in"]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1]["document_in"]["id"], po.id)
        self.assertEqual(lines[1]["quantity"], 5)
        self.assertEqual(lines[1]["document_out"], False)
        self.assertEqual(draft_picking_qty_in, 0)
        self.assertEqual(draft_purchase_qty, 0)
        self.assertEqual(pending_qty_in, 0)

        receipt = po.picking_ids
        receipt.button_validate()
        _, docs, lines = self.get_report_forecast(
            product_template_ids=self.product_template.ids
        )
        draft_picking_qty_in = self.sum_dicts(docs["product"], "draft_picking_qty")[
            "in"
        ]
        draft_purchase_qty = self.sum_dicts(docs["product"], "draft_purchase_qty")["in"]
        pending_qty_in = self.sum_dicts(docs["product"], "qty")["in"]
        self.assertEqual(len(lines), 1)
        self.assertEqual(draft_picking_qty_in, 0)
        self.assertEqual(draft_purchase_qty, 0)
        self.assertEqual(pending_qty_in, 0)

        po_form = Form(po)
        with po_form.line_ids.edit(0) as line:
            line.product_qty = 10
        po = po_form.save()
        _, docs, lines = self.get_report_forecast(
            product_template_ids=self.product_template.ids
        )
        draft_picking_qty_in = self.sum_dicts(docs["product"], "draft_picking_qty")[
            "in"
        ]
        draft_purchase_qty = self.sum_dicts(docs["product"], "draft_purchase_qty")["in"]
        pending_qty_in = self.sum_dicts(docs["product"], "qty")["in"]
        self.assertEqual(len(lines), 2, "Must have 2 line for now.")
        self.assertEqual(lines[1]["document_in"]["id"], po.id)
        self.assertEqual(lines[1]["quantity"], 5)
        self.assertEqual(draft_picking_qty_in, 0)
        self.assertEqual(draft_purchase_qty, 0)
        self.assertEqual(pending_qty_in, 0)

    def test_report_forecast_2_purchase_order_three_step_receipt(self):
        grp_multi_loc = self.env.ref("stock.group_stock_multi_locations")
        grp_multi_routes = self.env.ref("stock.group_adv_location")
        self.env.user.write({"group_ids": [(4, grp_multi_loc.id)]})
        self.env.user.write({"group_ids": [(4, grp_multi_routes.id)]})
        warehouse = self.env.ref("stock.warehouse0")
        warehouse.reception_steps = "three_steps"

        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner
        with po_form.line_ids.new() as line:
            line.product_id = self.product
            line.product_qty = 4
        po = po_form.save()

        _, docs, lines = self.get_report_forecast(
            product_template_ids=self.product_template.ids
        )
        draft_picking_qty_in = self.sum_dicts(docs["product"], "draft_picking_qty")[
            "in"
        ]
        draft_purchase_qty = self.sum_dicts(docs["product"], "draft_purchase_qty")["in"]
        pending_qty_in = self.sum_dicts(docs["product"], "qty")["in"]
        self.assertEqual(len(lines), 1, "Must have 1 line for now.")
        self.assertEqual(draft_picking_qty_in, 0)
        self.assertEqual(draft_purchase_qty, 4)
        self.assertEqual(pending_qty_in, 4)

        po.action_confirm()
        _, docs, lines = self.get_report_forecast(
            product_template_ids=self.product_template.ids
        )
        draft_picking_qty_in = self.sum_dicts(docs["product"], "draft_picking_qty")[
            "in"
        ]
        draft_purchase_qty = self.sum_dicts(docs["product"], "draft_purchase_qty")["in"]
        pending_qty_in = self.sum_dicts(docs["product"], "qty")["in"]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1]["document_in"]["id"], po.id)
        self.assertEqual(lines[1]["quantity"], 4)
        self.assertEqual(lines[1]["document_out"], False)
        self.assertEqual(draft_picking_qty_in, 0)
        self.assertEqual(draft_purchase_qty, 0)
        self.assertEqual(pending_qty_in, 0)
        receipt = po.picking_ids

        receipt.button_validate()
        _, docs, lines = self.get_report_forecast(
            product_template_ids=self.product_template.ids
        )
        draft_picking_qty_in = self.sum_dicts(docs["product"], "draft_picking_qty")[
            "in"
        ]
        draft_purchase_qty = self.sum_dicts(docs["product"], "draft_purchase_qty")["in"]
        pending_qty_in = self.sum_dicts(docs["product"], "qty")["in"]
        self.assertEqual(len(lines), 1)
        self.assertEqual(draft_picking_qty_in, 0)
        self.assertEqual(draft_purchase_qty, 0)
        self.assertEqual(pending_qty_in, 0)

        po_form = Form(po)
        with po_form.line_ids.edit(0) as line:
            line.product_qty = 10
        po = po_form.save()
        _, docs, lines = self.get_report_forecast(
            product_template_ids=self.product_template.ids
        )
        draft_picking_qty_in = self.sum_dicts(docs["product"], "draft_picking_qty")[
            "in"
        ]
        draft_purchase_qty = self.sum_dicts(docs["product"], "draft_purchase_qty")["in"]
        pending_qty_in = self.sum_dicts(docs["product"], "qty")["in"]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1]["document_in"]["id"], po.id)
        self.assertEqual(lines[1]["quantity"], 6)
        self.assertEqual(draft_picking_qty_in, 0)
        self.assertEqual(draft_purchase_qty, 0)
        self.assertEqual(pending_qty_in, 0)

    def test_report_forecast_3_report_line_corresponding_to_po_line_highlighted(self):
        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner
        with po_form.line_ids.new() as line:
            line.product_id = self.product
            line.product_qty = 5
        po1 = po_form.save()
        po1.action_confirm()
        po2 = po1.copy()
        po2.action_confirm()

        for po in [po1, po2]:
            context = po.line_ids[0].action_product_forecast_report()["context"]
            _, _, lines = self.get_report_forecast(
                product_template_ids=self.product_template.ids, context=context
            )
            for line in lines[1:]:
                if line["document_in"]["id"] == po.id:
                    self.assertTrue(
                        line["is_matched"],
                        "The corresponding PO line should be matched in the forecast report.",
                    )
                else:
                    self.assertFalse(
                        line["is_matched"],
                        "A line of the forecast report not linked to the PO shoud not be matched.",
                    )

    def test_vendor_delay_report_with_uom(self):
        uom_12 = self.env.ref("uom.product_uom_dozen")

        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner
        with po_form.line_ids.new() as line:
            line.product_id = self.product
            line.product_qty = 12
        po = po_form.save()
        po.action_confirm()

        receipt = po.picking_ids
        receipt_move = receipt.move_ids
        receipt_move.move_line_ids.unlink()
        receipt_move.move_line_ids = [
            (
                0,
                0,
                {
                    "location_id": receipt_move.location_id.id,
                    "location_dest_id": receipt_move.location_dest_id.id,
                    "product_id": self.product.id,
                    "product_uom_id": uom_12.id,
                    "quantity": 1,
                    "picking_id": receipt.id,
                },
            )
        ]
        receipt.move_ids.picked = True
        receipt.button_validate()

        data = self.env["vendor.delay.report"].formatted_read_group(
            [("partner_id", "=", self.partner.id)],
            ["product_id"],
            ["on_time_rate:sum", "qty_on_time:sum", "qty_total:sum"],
        )[0]
        self.assertEqual(data["qty_on_time:sum"], 12)
        self.assertEqual(data["qty_total:sum"], 12)
        self.assertEqual(data["on_time_rate:sum"], 100)

    def test_vendor_delay_report_with_multi_location(self):
        if not self.stock_location.child_ids:
            self.env["stock.location"].create(
                [
                    {
                        "name": "Shelf 1",
                        "location_id": self.stock_location.id,
                    },
                    {
                        "name": "Shelf 2",
                        "location_id": self.stock_location.id,
                    },
                ]
            )

        child_loc_01, child_loc_02 = self.stock_location.child_ids

        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner
        with po_form.line_ids.new() as line:
            line.product_id = self.product
            line.product_qty = 10
        po = po_form.save()
        po.action_confirm()

        receipt = po.picking_ids
        receipt_move = receipt.move_ids
        receipt_move.move_line_ids.unlink()
        receipt_move.move_line_ids = [
            (
                0,
                0,
                {
                    "location_id": receipt_move.location_id.id,
                    "location_dest_id": child_loc_01.id,
                    "product_id": self.product.id,
                    "product_uom_id": self.product.uom_id.id,
                    "quantity": 6,
                    "picking_id": receipt.id,
                },
            ),
            (
                0,
                0,
                {
                    "location_id": receipt_move.location_id.id,
                    "location_dest_id": child_loc_02.id,
                    "product_id": self.product.id,
                    "product_uom_id": self.product.uom_id.id,
                    "quantity": 4,
                    "picking_id": receipt.id,
                },
            ),
        ]
        receipt.move_ids.picked = True
        receipt.button_validate()

        data = self.env["vendor.delay.report"].formatted_read_group(
            [("partner_id", "=", self.partner.id)],
            ["product_id"],
            ["on_time_rate:sum", "qty_on_time:sum", "qty_total:sum"],
        )[0]
        self.assertEqual(data["qty_on_time:sum"], 10)
        self.assertEqual(data["qty_total:sum"], 10)
        self.assertEqual(data["on_time_rate:sum"], 100)

    def test_vendor_delay_report_with_backorder(self):
        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner
        with po_form.line_ids.new() as line:
            line.product_id = self.product
            line.product_qty = 10
        po = po_form.save()
        po.action_confirm()

        receipt01 = po.picking_ids
        receipt01_move = receipt01.move_ids
        receipt01_move.quantity = 6
        Form.from_action(self.env, receipt01.button_validate()).save().process()

        data = self.env["vendor.delay.report"].formatted_read_group(
            [("partner_id", "=", self.partner.id)],
            ["product_id"],
            ["on_time_rate:sum", "qty_on_time:sum", "qty_total:sum"],
        )[0]
        self.assertEqual(data["qty_on_time:sum"], 6)
        self.assertEqual(data["qty_total:sum"], 10)
        self.assertEqual(data["on_time_rate:sum"], 60)

        receipt02 = receipt01.backorder_ids
        receipt02.move_ids.quantity = 4
        receipt02.move_ids.picked = True
        receipt02.button_validate()

        (receipt01 | receipt02).move_ids.invalidate_recordset()
        data = self.env["vendor.delay.report"].formatted_read_group(
            [("partner_id", "=", self.partner.id)],
            ["product_id"],
            ["on_time_rate:sum", "qty_on_time:sum", "qty_total:sum"],
        )[0]
        self.assertEqual(data["qty_on_time:sum"], 10)
        self.assertEqual(data["qty_total:sum"], 10)
        self.assertEqual(data["on_time_rate:sum"], 100)

    def test_vendor_delay_report_without_backorder(self):
        product_no_categ = self.env["product.product"].create(
            {
                "name": "Product without category",
            }
        )
        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner
        with po_form.line_ids.new() as line:
            line.product_id = self.product
            line.product_qty = 10
        with po_form.line_ids.new() as line:
            line.product_id = product_no_categ
            line.product_qty = 10
        po = po_form.save()
        po.action_confirm()

        receipt = po.picking_ids
        receipt_moves = receipt.move_ids
        receipt_moves.quantity = 6
        receipt_moves.picked = True
        Form.from_action(
            self.env, receipt.button_validate()
        ).save().process_cancel_backorder()

        data = self.env["vendor.delay.report"].formatted_read_group(
            [("partner_id", "=", self.partner.id)],
            ["product_id"],
            ["on_time_rate:sum", "qty_on_time:sum", "qty_total:sum"],
        )
        self.assertEqual(
            [
                (rec["qty_on_time:sum"], rec["qty_total:sum"], rec["on_time_rate:sum"])
                for rec in data
            ],
            [(6, 10, 60), (6, 10, 60)],
        )

    def test_vendor_delay_report_with_duplicate_receipt_without_backorder(self):
        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner
        with po_form.line_ids.new() as line:
            line.product_id = self.product
            line.product_qty = 10
        po = po_form.save()
        po.action_confirm()

        receipt01 = po.picking_ids
        receipt01.move_ids.quantity = 6
        action = receipt01.button_validate()
        Form(
            self.env[action["res_model"]].with_context(action["context"])
        ).save().process_cancel_backorder()
        receipt02 = receipt01.copy()
        receipt02.move_ids.write(
            {
                "product_uom_qty": 4,
            }
        )
        receipt02.button_validate()
        data = self.env["vendor.delay.report"].web_read_group(
            [("partner_id", "=", self.partner.id)],
            ["product_id"],
            ["on_time_rate:sum", "qty_on_time:sum", "qty_total:sum"],
        )["groups"][0]
        self.assertEqual(data["qty_total:sum"], 10)
        self.assertEqual(data["qty_on_time:sum"], 10)
        self.assertEqual(data["on_time_rate:sum"], 100)
