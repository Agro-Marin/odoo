from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sale_purchase.tests.common import TestSalePurchaseCommon


@tagged("-at_install", "post_install")
class TestSalePurchase(TestSalePurchaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_data_2 = cls.setup_other_company()

        SaleOrder = cls.env["sale.order"]
        cls.analytic_plan = cls.env["account.analytic.plan"].create(
            {"name": "Plan Test"}
        )
        cls.test_analytic_account_1, cls.test_analytic_account_2 = cls.env[
            "account.analytic.account"
        ].create(
            [
                {
                    "name": "analytic_account_test_1",
                    "plan_id": cls.analytic_plan.id,
                },
                {
                    "name": "analytic_account_test_2",
                    "plan_id": cls.analytic_plan.id,
                },
            ]
        )
        cls.sale_order_1 = SaleOrder.create(
            {
                "partner_id": cls.partner_a.id,
                "partner_invoice_id": cls.partner_a.id,
                "partner_shipping_id": cls.partner_a.id,
            }
        )
        cls.sol1_service_deliver = cls.env["sale.order.line"].create(
            {
                "product_id": cls.company_data["product_service_delivery"].id,
                "product_qty": 1,
                "order_id": cls.sale_order_1.id,
                "tax_ids": False,
            }
        )
        cls.sol1_product_order = cls.env["sale.order.line"].create(
            {
                "product_id": cls.company_data["product_order_no"].id,
                "product_qty": 2,
                "order_id": cls.sale_order_1.id,
                "tax_ids": False,
            }
        )
        cls.sol1_service_purchase_1 = cls.env["sale.order.line"].create(
            {
                "product_id": cls.service_purchase_1.id,
                "product_qty": 4,
                "order_id": cls.sale_order_1.id,
                "tax_ids": False,
            }
        )

        cls.sale_order_2 = SaleOrder.create(
            {
                "partner_id": cls.partner_a.id,
                "partner_invoice_id": cls.partner_a.id,
                "partner_shipping_id": cls.partner_a.id,
            }
        )
        cls.sol2_product_deliver = cls.env["sale.order.line"].create(
            {
                "product_id": cls.company_data["product_delivery_no"].id,
                "product_qty": 5,
                "order_id": cls.sale_order_2.id,
                "tax_ids": False,
            }
        )
        cls.sol2_service_order = cls.env["sale.order.line"].create(
            {
                "product_id": cls.company_data["product_service_order"].id,
                "product_qty": 6,
                "order_id": cls.sale_order_2.id,
                "tax_ids": False,
            }
        )
        cls.sol2_service_purchase_2 = cls.env["sale.order.line"].create(
            {
                "product_id": cls.service_purchase_2.id,
                "product_qty": 7,
                "order_id": cls.sale_order_2.id,
                "tax_ids": False,
            }
        )

    def test_sale_create_purchase(self):
        self.sale_order_1.action_confirm()
        self.sale_order_2.action_confirm()

        purchase_order = self.env["purchase.order"].search(
            [
                ("partner_id", "=", self.service_purchase_1.seller_ids.partner_id.id),
                ("state", "=", "draft"),
            ]
        )
        purchase_lines_so1 = self.env["purchase.order.line"].search(
            [("sale_line_id", "in", self.sale_order_1.line_ids.ids)]
        )
        purchase_line1 = purchase_lines_so1[0]

        purchase_lines_so2 = self.env["purchase.order.line"].search(
            [("sale_line_id", "in", self.sale_order_2.line_ids.ids)]
        )
        purchase_line2 = purchase_lines_so2[0]

        self.assertEqual(
            len(purchase_order),
            2,
            "Two PO should have been created, from the 2 Sales orders",
        )
        self.assertEqual(
            len(purchase_order.line_ids), 2, "The purchase order should have 2 lines"
        )
        self.assertIn(
            self.sale_order_1.name,
            purchase_order[1].origin,
            "The PO should have SO 1 in its source documents",
        )
        self.assertIn(
            self.sale_order_2.name,
            purchase_order[0].origin,
            "The PO should have SO 2 in its source documents",
        )
        self.assertEqual(
            len(purchase_lines_so1),
            1,
            "Only one SO line from SO 1 should have create a PO line",
        )
        self.assertEqual(
            len(purchase_lines_so2),
            1,
            "Only one SO line from SO 2 should have create a PO line",
        )
        self.assertEqual(
            len(purchase_order.activity_ids),
            0,
            "No activity should be scheduled on the PO",
        )
        self.assertEqual(
            set(purchase_order.mapped("state")),
            {"draft"},
            "The created PO should be in draft state.",
        )

        self.assertNotEqual(
            purchase_line1.product_id,
            purchase_line2.product_id,
            "The 2 PO line should have different products",
        )
        self.assertEqual(
            purchase_line1.product_id,
            self.sol1_service_purchase_1.product_id,
            "The create PO line must have the same product as its mother SO line",
        )
        self.assertEqual(
            purchase_line2.product_id,
            self.sol2_service_purchase_2.product_id,
            "The create PO line must have the same product as its mother SO line",
        )

        self.assertEqual(
            purchase_line1.price_unit,
            self.service_purchase_1.seller_ids.price,
            "Unit price should be taken from the vendor line",
        )
        self.assertEqual(
            purchase_line2.price_unit,
            self.service_purchase_2.seller_ids.price,
            "Unit price should be taken from the vendor line",
        )
        self.assertEqual(
            purchase_line1.discount,
            self.service_purchase_1.seller_ids.discount,
            "Discount should be taken from the vendor line",
        )

        purchase_order.action_cancel()

        self.assertEqual(
            len(self.sale_order_1.activity_ids),
            1,
            "One activity should be scheduled on the SO 1 since the PO has been cancelled",
        )
        self.assertEqual(
            self.sale_order_1.user_id,
            self.sale_order_1.activity_ids[0].user_id,
            "The activity should be assigned to the SO responsible",
        )

        self.assertEqual(
            len(self.sale_order_2.activity_ids),
            1,
            "One activity should be scheduled on the SO 2 since the PO has been cancelled",
        )
        self.assertEqual(
            self.sale_order_2.user_id,
            self.sale_order_2.activity_ids[0].user_id,
            "The activity should be assigned to the SO responsible",
        )

    def test_uom_conversion(self):
        self.service_purchase_2.seller_ids.product_uom_id = self.env.ref(
            "uom.product_uom_unit"
        )
        self.sale_order_2.action_confirm()
        purchase_line = self.env["purchase.order.line"].search(
            [("sale_line_id", "=", self.sol2_service_purchase_2.id)]
        )

        self.assertTrue(purchase_line, "The SO line should generate a PO line")
        self.assertEqual(
            purchase_line.product_uom_id,
            self.service_purchase_2.seller_ids.product_uom_id,
            "The UoM on the purchase line should be the one from the product configuration",
        )
        self.assertNotEqual(
            purchase_line.product_uom_id,
            self.sol2_service_purchase_2.product_uom_id,
            "As the product configuration, the UoM on the SO line should still be different from the one on the PO line",
        )
        self.assertEqual(
            purchase_line.product_qty,
            self.sol2_service_purchase_2.product_qty * 12,
            "The quantity from the SO should be converted with th UoM factor on the PO line",
        )

    def test_no_supplier(self):
        self.service_purchase_1.seller_ids.unlink()
        with self.assertRaises(UserError):
            self.sale_order_1.action_confirm()

    def test_reconfirm_sale_order(self):
        self.sale_order_1.action_confirm()

        purchase_order = self.env["purchase.order"].search(
            [
                ("partner_id", "=", self.service_purchase_1.seller_ids.partner_id.id),
                ("state", "=", "draft"),
            ]
        )
        purchase_lines = self.env["purchase.order.line"].search(
            [("sale_line_id", "in", self.sale_order_1.line_ids.ids)]
        )
        purchase_line = purchase_lines[0]

        self.assertEqual(
            len(purchase_lines),
            1,
            "Only one purchase line should be created on SO confirmation",
        )
        self.assertEqual(
            len(purchase_order),
            1,
            "One purchase order should have been created on SO confirmation",
        )
        self.assertEqual(
            len(purchase_order.line_ids),
            1,
            "Only one line on PO, after SO confirmation",
        )
        self.assertEqual(
            purchase_order,
            purchase_lines.order_id,
            "The generated purchase line should be in the generated purchase order",
        )
        self.assertEqual(
            purchase_order.state, "draft", "Generated purchase should be in draft state"
        )
        self.assertEqual(
            purchase_line.price_unit,
            self.service_purchase_1.seller_ids.price,
            "Purchase line price is the one from the supplier",
        )
        self.assertEqual(
            purchase_line.product_qty,
            self.sol1_service_purchase_1.product_qty,
            "Quantity on SO line is not the same on the purchase line (same UoM)",
        )

        self.sale_order_1._action_cancel()

        self.assertEqual(
            len(purchase_order.activity_ids),
            1,
            "One activity should be scheduled on the PO since a SO has been cancelled",
        )

        purchase_order = self.env["purchase.order"].search(
            [
                ("partner_id", "=", self.service_purchase_1.seller_ids.partner_id.id),
                ("state", "=", "draft"),
            ]
        )
        purchase_lines = self.env["purchase.order.line"].search(
            [("sale_line_id", "in", self.sale_order_1.line_ids.ids)]
        )
        purchase_line = purchase_lines[0]

        self.assertEqual(
            len(purchase_lines),
            1,
            "Always one purchase line even after SO cancellation",
        )
        self.assertTrue(
            purchase_order, "Always one purchase order even after SO cancellation"
        )
        self.assertEqual(
            len(purchase_order.line_ids),
            1,
            "Still one line on PO, even after SO cancellation",
        )
        self.assertEqual(
            purchase_order,
            purchase_lines.order_id,
            "The generated purchase line should still be in the generated purchase order",
        )
        self.assertEqual(
            purchase_order.state,
            "draft",
            "Generated purchase should still be in draft state",
        )
        self.assertEqual(
            purchase_line.price_unit,
            self.service_purchase_1.seller_ids.price,
            "Purchase line price is still the one from the supplier",
        )
        self.assertEqual(
            purchase_line.product_qty,
            self.sol1_service_purchase_1.product_qty,
            "Quantity on SO line should still be the same on the purchase line (same UoM)",
        )

        self.sale_order_1.action_draft()
        self.sale_order_1.action_confirm()

        purchase_order = self.env["purchase.order"].search(
            [
                ("partner_id", "=", self.service_purchase_1.seller_ids.partner_id.id),
                ("state", "=", "draft"),
            ]
        )
        purchase_lines = self.env["purchase.order.line"].search(
            [("sale_line_id", "in", self.sale_order_1.line_ids.ids)]
        )
        purchase_line = purchase_lines[0]

        self.assertEqual(
            len(purchase_lines),
            1,
            "Still only one purchase line should be created even after SO reconfirmation",
        )
        self.assertEqual(
            len(purchase_order),
            1,
            "Still one purchase order should be after SO reconfirmation",
        )
        self.assertEqual(
            len(purchase_order.line_ids),
            1,
            "Only one line on PO, even after SO reconfirmation",
        )
        self.assertEqual(
            purchase_order,
            purchase_lines.order_id,
            "The generated purchase line should be in the generated purchase order",
        )
        self.assertEqual(
            purchase_order.state, "draft", "Generated purchase should be in draft state"
        )
        self.assertEqual(
            purchase_line.price_unit,
            self.service_purchase_1.seller_ids.price,
            "Purchase line price is the one from the supplier",
        )
        self.assertEqual(
            purchase_line.product_qty,
            self.sol1_service_purchase_1.product_qty,
            "Quantity on SO line is not the same on the purchase line (same UoM)",
        )

    def test_update_ordered_sale_quantity(self):
        self.sale_order_1.action_confirm()

        purchase_order = self.env["purchase.order"].search(
            [
                ("partner_id", "=", self.service_purchase_1.seller_ids.partner_id.id),
                ("state", "=", "draft"),
            ]
        )
        purchase_lines = self.env["purchase.order.line"].search(
            [("sale_line_id", "in", self.sale_order_1.line_ids.ids)]
        )
        purchase_line = purchase_lines[0]

        self.assertEqual(
            purchase_order.state,
            "draft",
            "The created purchase should be in draft state",
        )
        self.assertFalse(
            purchase_order.activity_ids, "There is no activities on the PO"
        )
        self.assertEqual(
            purchase_line.product_qty,
            self.sol1_service_purchase_1.product_qty,
            "Quantity on SO line is not the same on the purchase line (same UoM)",
        )

        self.sol1_service_purchase_1.write(
            {"product_qty": self.sol1_service_purchase_1.product_qty + 12}
        )
        self.assertEqual(
            purchase_line.product_qty,
            self.sol1_service_purchase_1.product_qty,
            "The quantity of draft PO line should be increased as the one from the sale line changed",
        )

        sale_line_old_quantity = self.sol1_service_purchase_1.product_qty

        self.sol1_service_purchase_1.write(
            {"product_qty": self.sol1_service_purchase_1.product_qty - 3}
        )
        self.assertEqual(
            len(purchase_order.activity_ids),
            1,
            "One activity should have been created on the PO",
        )
        self.assertEqual(
            purchase_order.activity_ids.user_id,
            purchase_order.user_id,
            "Activity assigned to PO responsible",
        )
        self.assertEqual(
            purchase_order.activity_ids.state,
            "today",
            "Activity is for today, as it is urgent",
        )

        purchase_order.action_confirm()

        self.sol1_service_purchase_1.write(
            {"product_qty": self.sol1_service_purchase_1.product_qty - 5}
        )

        self.env.invalidate_all()

        self.assertEqual(
            purchase_line.product_qty,
            sale_line_old_quantity,
            "The quantity on the PO line should not have changed.",
        )
        self.assertEqual(
            len(purchase_order.activity_ids),
            2,
            "a second activity should have been created on the PO",
        )
        self.assertEqual(
            purchase_order.activity_ids.mapped("user_id"),
            purchase_order.user_id,
            "Activities assigned to PO responsible",
        )
        self.assertEqual(
            purchase_order.activity_ids.mapped("state"),
            ["today", "today"],
            "Activities are for today, as it is urgent",
        )

        delta = 8
        self.sol1_service_purchase_1.write(
            {"product_qty": self.sol1_service_purchase_1.product_qty + delta}
        )

        self.assertEqual(
            purchase_line.product_qty,
            sale_line_old_quantity,
            "The quantity on the PO line should not have changed.",
        )
        self.assertEqual(
            len(purchase_order.activity_ids), 2, "Always 2 activity on confirmed the PO"
        )

        purchase_order2 = self.env["purchase.order"].search(
            [
                ("partner_id", "=", self.service_purchase_1.seller_ids.partner_id.id),
                ("state", "=", "draft"),
            ]
        )
        purchase_lines = self.env["purchase.order.line"].search(
            [("sale_line_id", "in", self.sale_order_1.line_ids.ids)]
        )
        purchase_lines2 = purchase_lines.filtered(
            lambda pol: pol.order_id == purchase_order2
        )
        purchase_line2 = purchase_lines2[0]

        self.assertTrue(
            purchase_order2,
            "A second PO is created by increasing sale quantity when first PO is confirmed",
        )
        self.assertEqual(
            purchase_order2.state, "draft", "The second PO is in draft state"
        )
        self.assertNotEqual(purchase_order, purchase_order2, "The 2 PO are different")
        self.assertEqual(
            len(purchase_lines), 2, "The same Sale Line has created 2 purchase lines"
        )
        self.assertEqual(
            len(purchase_order2.line_ids), 1, "The 2nd PO has only one line"
        )
        self.assertEqual(
            purchase_line2.sale_line_id,
            self.sol1_service_purchase_1,
            "The 2nd PO line came from the SO line sol1_service_purchase_1",
        )
        self.assertEqual(
            purchase_line2.product_qty,
            delta,
            "The quantity of the new PO line is the quantity added on the Sale Line, after first PO confirmation",
        )

    def test_pol_description(self):
        service = self.env["product.product"].create(
            {
                "name": "Super Product",
                "type": "service",
                "service_to_purchase": True,
                "seller_ids": [
                    (
                        0,
                        0,
                        {
                            "partner_id": self.partner_vendor_service.id,
                            "min_qty": 1,
                            "price": 10,
                            "product_code": "C01",
                            "product_name": "Name01",
                            "sequence": 1,
                        },
                    )
                ],
            }
        )

        so = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": service.name,
                            "product_id": service.id,
                            "product_qty": 1,
                        },
                    )
                ],
            }
        )
        so.action_confirm()

        po = self.env["purchase.order"].search(
            [("partner_id", "=", self.partner_vendor_service.id)],
            order="id desc",
            limit=1,
        )
        self.assertEqual(po.line_ids.name, "[C01] Name01")

    def test_pol_custom_attribute(self):
        product_attribute = self.env["product.attribute"].create(
            {
                "name": "product attribute",
                "display_type": "radio",
                "create_variant": "always",
            }
        )

        product_attribute_value = self.env["product.attribute.value"].create(
            {
                "name": "single product attribute value",
                "is_custom": True,
                "attribute_id": product_attribute.id,
            }
        )

        product_attribute_line = self.env["product.template.attribute.line"].create(
            {
                "attribute_id": product_attribute.id,
                "product_tmpl_id": self.service_purchase_1.product_tmpl_id.id,
                "value_ids": [Command.link(product_attribute_value.id)],
            }
        )

        custom_value = "test"

        sale_order = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "name": self.service_purchase_1.name,
                            "product_id": self.service_purchase_1.id,
                            "product_qty": 1,
                            "product_custom_attribute_value_ids": [
                                Command.create(
                                    {
                                        "custom_product_template_attribute_value_id": product_attribute_line.product_template_value_ids.id,
                                        "custom_value": custom_value,
                                    }
                                )
                            ],
                        }
                    )
                ],
            }
        )
        sale_order.action_confirm()
        pol = sale_order._get_purchase_orders().line_ids
        self.assertEqual(
            pol.name,
            f"{self.service_purchase_1.display_name}\n{product_attribute.name}: {product_attribute_value.name}: {custom_value}",
        )

    def test_service_to_purchase_multi_company(self):
        company_1 = self.env.company
        company_2 = self.company_data_2["company"]
        self.env.user.company_ids += company_2
        self.assertTrue(self.service_purchase_1.service_to_purchase)
        self.assertFalse(
            self.service_purchase_1.with_company(company_2).service_to_purchase
        )
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "company_id": company_2.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.service_purchase_1.id,
                            "product_qty": 1,
                        }
                    )
                ],
            }
        )
        order.with_context(
            allowed_company_ids=(company_1 + company_2).ids
        ).with_company(company_1).action_confirm()
        self.assertFalse(order.purchase_order_count)

        order2 = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "company_id": company_1.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.service_purchase_1.id,
                            "product_qty": 1,
                        }
                    )
                ],
            }
        )

        order2.with_context(
            allowed_company_ids=(company_1 + company_2).ids
        ).with_company(company_2).action_confirm()
        self.assertTrue(order2.purchase_order_count)

    def test_service_to_purchase_branch_tax_propagation(self):
        branch = self.env["res.company"].create(
            {
                "name": "Branch Company",
                "parent_id": self.env.company.id,
            }
        )
        self.env.user.company_id = branch
        service_product = self.env["product.product"].create(
            {
                "name": "Branch Out-sourced Service",
                "standard_price": 200.0,
                "type": "service",
                "invoice_policy": "transferred",
                "taxes_id": self.company_data["default_tax_sale"],
                "supplier_taxes_id": self.company_data["default_tax_purchase"],
                "service_to_purchase": True,
                "seller_ids": [
                    Command.create(
                        {
                            "partner_id": self.partner_b.id,
                            "min_qty": 1,
                            "price": 100,
                        }
                    )
                ],
            }
        )
        so = self.env["sale.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": service_product.id,
                        }
                    )
                ],
            }
        )
        self.assertEqual(so.line_ids.tax_ids, self.company_data["default_tax_sale"])
        so.action_confirm()
        self.assertEqual(
            so.line_ids.purchase_line_ids.tax_ids,
            self.company_data["default_tax_purchase"],
        )
