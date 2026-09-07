import odoo
from odoo import fields

from odoo.addons.point_of_sale.tests.common import CommonPosTest


@odoo.tests.tagged("post_install", "-at_install")
class TestPointOfSaleFlow(CommonPosTest):
    def test_ship_later_lots(self):
        self.env.user.group_ids += self.env.ref("account.group_account_manager")
        self.stock_location = self.company_data["default_warehouse"].lot_stock_id
        self.twenty_dollars_no_tax.product_variant_id.write(
            {"tracking": "serial", "is_storable": True, "taxes_id": []}
        )
        lot_1 = self.env["stock.lot"].create(
            {
                "name": "1001",
                "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                "company_id": self.env.company.id,
            }
        )
        lot_2 = self.env["stock.lot"].create(
            {
                "name": "1002",
                "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                "company_id": self.env.company.id,
            }
        )
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "inventory_quantity": 1,
                "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                "location_id": self.stock_location.id,
                "lot_id": lot_1.id,
            }
        ).action_apply_inventory()
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "inventory_quantity": 1,
                "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                "location_id": self.stock_location.id,
                "lot_id": lot_2.id,
            }
        ).action_apply_inventory()

        sale_order = (
            self.env["sale.order"]
            .sudo()
            .create(
                {
                    "partner_id": self.partner_stva.id,
                    "line_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                                "name": self.twenty_dollars_no_tax.product_variant_id.name,
                                "price_unit": self.twenty_dollars_no_tax.product_variant_id.lst_price,
                                "product_qty": 2,
                            },
                        )
                    ],
                }
            )
        )
        sale_order.action_confirm()
        order, _ = self.create_backend_pos_order(
            {
                "order_data": {
                    "partner_id": self.partner_stva.id,
                    "shipping_date": fields.Date.today(),
                },
                "line_data": [
                    {
                        "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                        "pack_lot_ids": [[0, 0, {"lot_name": lot_1.name}]],
                        "sale_order_line_id": sale_order.line_ids[0].id,
                        "sale_order_origin_id": sale_order.id,
                    }
                ],
                "payment_data": [
                    {"payment_method_id": self.pos_config_usd.payment_method_ids[0].id}
                ],
            }
        )
        self.assertEqual(order.picking_ids.move_line_ids.lot_id, lot_1)

    def test_sale_order_count_and_pos_order_count_refresh_without_invalidation(self):
        # Regression test: both counters used to be non-stored computes with
        # no @api.depends, so they never refreshed within a transaction after
        # a pos.order.line linking a sale order was created, unless the
        # cache was invalidated by hand.
        sale_order = (
            self.env["sale.order"]
            .sudo()
            .create(
                {
                    "partner_id": self.partner_stva.id,
                    "line_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                                "name": self.twenty_dollars_no_tax.product_variant_id.name,
                                "price_unit": self.twenty_dollars_no_tax.product_variant_id.lst_price,
                                "product_qty": 2,
                            },
                        )
                    ],
                }
            )
        )
        sale_order.action_confirm()
        self.assertEqual(sale_order.sudo().pos_order_count, 0)

        order, _ = self.create_backend_pos_order(
            {
                "order_data": {
                    "partner_id": self.partner_stva.id,
                },
                "line_data": [
                    {
                        "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                        "tax_ids": [(6, 0, [])],
                        "sale_order_line_id": sale_order.line_ids[0].id,
                        "sale_order_origin_id": sale_order.id,
                    }
                ],
                "payment_data": [
                    {"payment_method_id": self.pos_config_usd.payment_method_ids[0].id}
                ],
            }
        )
        self.assertEqual(order.sudo().sale_order_count, 1)
        self.assertEqual(sale_order.sudo().pos_order_count, 1)

    def test_amount_taxinc_to_invoice_excludes_pos_settled_amount(self):
        # Regression test: SaleOrder._compute_amounts_invoice used to be
        # defined twice in the same class body, so this correction
        # (subtracting amounts already settled through POS, invoiced or not,
        # from the "still to invoice" balance) was silently dead code -- the
        # class body kept only the second definition.
        sale_order = (
            self.env["sale.order"]
            .sudo()
            .create(
                {
                    "partner_id": self.partner_stva.id,
                    "line_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                                "name": self.twenty_dollars_no_tax.product_variant_id.name,
                                "price_unit": self.twenty_dollars_no_tax.product_variant_id.lst_price,
                                "product_qty": 1,
                            },
                        )
                    ],
                }
            )
        )
        sale_order.action_confirm()
        self.assertEqual(sale_order.sudo().amount_taxinc_to_invoice, 20.0)

        self.create_backend_pos_order(
            {
                "order_data": {
                    "partner_id": self.partner_stva.id,
                },
                "line_data": [
                    {
                        "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                        "tax_ids": [(6, 0, [])],
                        "sale_order_line_id": sale_order.line_ids[0].id,
                        "sale_order_origin_id": sale_order.id,
                    }
                ],
                "payment_data": [
                    {"payment_method_id": self.pos_config_usd.payment_method_ids[0].id}
                ],
            }
        )
        # Settled in full through POS, with no invoice -- must no longer read
        # as still-to-invoice.
        self.assertEqual(sale_order.sudo().amount_taxinc_to_invoice, 0.0)

    def test_compute_name_cancelled_marker_survives_batched_recompute(self):
        # Regression test: `_compute_name` called bare `super()._compute_name()`
        # inside a loop over `self`, binding to the whole batch instead of the
        # loop variable -- silently re-running the base name computation over
        # every line in the same recompute batch, including one whose name
        # had just been marked "(Cancelled)" by this same method.
        sale_order = (
            self.env["sale.order"]
            .sudo()
            .create(
                {
                    "partner_id": self.partner_stva.id,
                    "line_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                                "name": self.twenty_dollars_no_tax.product_variant_id.name,
                                "price_unit": self.twenty_dollars_no_tax.product_variant_id.lst_price,
                                "product_qty": 1,
                            },
                        ),
                        (
                            0,
                            0,
                            {
                                "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                                "name": self.twenty_dollars_no_tax.product_variant_id.name,
                                "price_unit": self.twenty_dollars_no_tax.product_variant_id.lst_price,
                                "product_qty": 1,
                            },
                        ),
                    ],
                }
            )
        )
        sale_order.action_confirm()
        line_a, line_b = sale_order.line_ids

        self.create_backend_pos_order(
            {
                "order_data": {
                    "partner_id": self.partner_stva.id,
                },
                "line_data": [
                    {
                        "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                        "tax_ids": [(6, 0, [])],
                        "sale_order_line_id": line_a.id,
                        "sale_order_origin_id": sale_order.id,
                    }
                ],
                "payment_data": [
                    {"payment_method_id": self.pos_config_usd.payment_method_ids[0].id}
                ],
                "refund_data": [
                    {"payment_method_id": self.pos_config_usd.payment_method_ids[0].id}
                ],
            }
        )
        self.assertIn("(Cancelled)", line_a.sudo().name)

        # Force a batched recompute of `name` for both lines together -- the
        # exact shape of any write that dirties a `_compute_name` dependency
        # on more than one line of the same order in a single flush.
        name_field = self.env["sale.order.line"]._fields["name"]
        self.env.add_to_compute(name_field, sale_order.line_ids)
        self.env.flush_all()

        self.assertIn("(Cancelled)", line_a.sudo().name)
        self.assertNotIn("(Cancelled)", line_b.sudo().name)
