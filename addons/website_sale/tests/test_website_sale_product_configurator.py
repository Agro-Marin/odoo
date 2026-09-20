from datetime import datetime

from odoo.fields import Command
from odoo.tests import HttpCase, tagged

from odoo.addons.website_sale.controllers.product_configurator import (
    WebsiteSaleProductConfiguratorController,
)
from odoo.addons.website_sale.tests.common import MockRequest, WebsiteSaleCommon


@tagged("post_install", "-at_install")
class TestWebsiteSaleProductConfigurator(HttpCase, WebsiteSaleCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.pc_controller = WebsiteSaleProductConfiguratorController()

    def test_02_variants_modal_window(self):

        always_attribute, dynamic_attribute, never_attribute, never_attribute_custom = (
            self.env["product.attribute"].create(
                [
                    {
                        "name": "Always attribute size",
                        "display_type": "radio",
                        "create_variant": "always",
                    },
                    {
                        "name": "Dynamic attribute size",
                        "display_type": "radio",
                        "create_variant": "dynamic",
                    },
                    {
                        "name": "Never attribute size",
                        "display_type": "radio",
                        "create_variant": "no_variant",
                    },
                    {
                        "name": "Never attribute size custom",
                        "display_type": "radio",
                        "create_variant": "no_variant",
                    },
                ]
            )
        )
        (
            always_S,
            always_M,
            dynamic_S,
            dynamic_M,
            never_S,
            never_M,
            never_custom_no,
            never_custom_yes,
        ) = self.env["product.attribute.value"].create(
            [
                {
                    "name": "S always",
                    "attribute_id": always_attribute.id,
                },
                {
                    "name": "M always",
                    "attribute_id": always_attribute.id,
                },
                {
                    "name": "S dynamic",
                    "attribute_id": dynamic_attribute.id,
                },
                {
                    "name": "M dynamic",
                    "attribute_id": dynamic_attribute.id,
                },
                {
                    "name": "S never",
                    "attribute_id": never_attribute.id,
                },
                {
                    "name": "M never",
                    "attribute_id": never_attribute.id,
                },
                {
                    "name": "No never custom",
                    "attribute_id": never_attribute_custom.id,
                },
                {
                    "name": "Yes never custom",
                    "attribute_id": never_attribute_custom.id,
                    "is_custom": True,
                },
            ]
        )

        product_short = self.env["product.template"].create(
            {
                "name": "Short (TEST)",
                "website_published": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": always_attribute.id,
                            "value_ids": [(4, always_S.id), (4, always_M.id)],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": dynamic_attribute.id,
                            "value_ids": [(4, dynamic_S.id), (4, dynamic_M.id)],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": never_attribute.id,
                            "value_ids": [(4, never_S.id), (4, never_M.id)],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": never_attribute_custom.id,
                            "value_ids": [
                                (4, never_custom_no.id),
                                (4, never_custom_yes.id),
                            ],
                        }
                    ),
                ],
            }
        )

        optional_product = self.env["product.template"].create(
            {
                "name": "Optional product (TEST)",
                "website_published": True,
            }
        )
        product_short.optional_product_ids = [(4, optional_product.id)]

        old_sale_order = self.env["sale.order"].search([])
        self.start_tour("/", "tour_variants_modal_window")

        new_sale_order = self.env["sale.order"].search([]) - old_sale_order
        new_order_line = new_sale_order.line_ids
        self.assertEqual(
            new_order_line.name,
            "Short (TEST) (M always, M dynamic)\nNever attribute size: M never\nNever attribute size custom: Yes never custom: TEST",
        )

    def test_product_configurator_optional_products(self):
        main_product = self.env["product.template"].create(
            {
                "name": "Main product",
                "website_published": True,
                "optional_product_ids": [
                    Command.create(
                        {
                            "name": "Optional product",
                            "website_published": True,
                        }
                    )
                ],
            }
        )

        with MockRequest(self.env, website=self.website):
            show_configurator = (
                self.pc_controller.website_sale_should_show_product_configurator(
                    product_template_id=main_product.id,
                    ptav_ids=[],
                    is_product_configured=False,
                )
            )

        self.assertTrue(show_configurator)

    def test_optional_products_not_visible_on_other_websites(self):
        second_website = self.env["website"].create({"name": "second website"})
        optional_product = self.env["product.template"].create(
            {
                "name": "Optional product",
                "website_published": True,
                "website_id": second_website.id,
            }
        )

        main_product = self.env["product.template"].create(
            {
                "name": "Main product",
                "website_published": True,
                "optional_product_ids": [Command.set(optional_product.ids)],
            }
        )

        with MockRequest(self.env, website=self.website):
            show_configurator = (
                self.pc_controller.website_sale_should_show_product_configurator(
                    product_template_id=main_product.id,
                    ptav_ids=[],
                    is_product_configured=False,
                )
            )

        self.assertFalse(show_configurator)

    def test_product_configurator_single_variant(self):
        attribute = self.env["product.attribute"].create(
            {
                "name": "Attribute",
                "value_ids": [Command.create({"name": "A"})],
            }
        )
        main_product = self.env["product.template"].create(
            {
                "name": "Main product",
                "website_published": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    ),
                ],
            }
        )

        with MockRequest(self.env, website=self.website):
            show_configurator = (
                self.pc_controller.website_sale_should_show_product_configurator(
                    product_template_id=main_product.id,
                    ptav_ids=[],
                    is_product_configured=False,
                )
            )

        self.assertFalse(show_configurator)

    def test_product_configurator_configured_with_empty_multi_checkbox(self):
        multi_attribute = self.env["product.attribute"].create(
            {
                "name": "Multi-checkbox attribute",
                "display_type": "multi",
                "create_variant": "no_variant",
                "value_ids": [
                    Command.create({"name": "A"}),
                    Command.create({"name": "B"}),
                ],
            }
        )
        main_product = self.env["product.template"].create(
            {
                "name": "Main product",
                "website_published": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": multi_attribute.id,
                            "value_ids": [Command.set(multi_attribute.value_ids.ids)],
                        }
                    ),
                ],
            }
        )

        with MockRequest(self.env, website=self.website):
            show_configurator = (
                self.pc_controller.website_sale_should_show_product_configurator(
                    product_template_id=main_product.id,
                    ptav_ids=[],
                    is_product_configured=True,
                )
            )

        self.assertFalse(show_configurator)

    def test_product_configurator_only_no_variant_attributes(self):
        no_variant_attribute = self.env["product.attribute"].create(
            {
                "name": "No variant attribute",
                "create_variant": "no_variant",
                "value_ids": [
                    Command.create({"name": "A"}),
                    Command.create({"name": "B"}),
                ],
            }
        )
        main_product = self.env["product.template"].create(
            {
                "name": "Main product",
                "website_published": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": no_variant_attribute.id,
                            "value_ids": [
                                Command.set(no_variant_attribute.value_ids.ids)
                            ],
                        }
                    ),
                ],
            }
        )

        with MockRequest(self.env, website=self.website):
            show_configurator = (
                self.pc_controller.website_sale_should_show_product_configurator(
                    product_template_id=main_product.id,
                    ptav_ids=[],
                    is_product_configured=False,
                )
            )

        self.assertTrue(show_configurator)

    def test_product_configurator_only_dynamic_attributes(self):
        dynamic_attribute = self.env["product.attribute"].create(
            {
                "name": "Dynamic attribute",
                "create_variant": "dynamic",
                "value_ids": [
                    Command.create({"name": "A"}),
                    Command.create({"name": "B"}),
                ],
            }
        )
        main_product = self.env["product.template"].create(
            {
                "name": "Main product",
                "website_published": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": dynamic_attribute.id,
                            "value_ids": [Command.set(dynamic_attribute.value_ids.ids)],
                        }
                    ),
                ],
            }
        )

        with MockRequest(self.env, website=self.website):
            show_configurator = (
                self.pc_controller.website_sale_should_show_product_configurator(
                    product_template_id=main_product.id,
                    ptav_ids=[],
                    is_product_configured=False,
                )
            )

        self.assertTrue(show_configurator)

    def test_product_configurator_single_custom_attribute(self):
        custom_attribute = self.env["product.attribute"].create(
            {
                "name": "Custom attribute",
                "value_ids": [
                    Command.create(
                        {
                            "name": "Custom value",
                            "is_custom": True,
                        }
                    ),
                ],
            }
        )
        main_product = self.env["product.template"].create(
            {
                "name": "Main product",
                "website_published": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": custom_attribute.id,
                            "value_ids": [Command.set(custom_attribute.value_ids.ids)],
                        }
                    ),
                ],
            }
        )

        with MockRequest(self.env, website=self.website):
            show_configurator = (
                self.pc_controller.website_sale_should_show_product_configurator(
                    product_template_id=main_product.id,
                    ptav_ids=[],
                    is_product_configured=False,
                )
            )

        self.assertTrue(show_configurator)

    def test_product_configurator_sale_not_ok(self):
        optional_product = self.env["product.template"].create(
            {
                "name": "Optional product",
                "website_published": True,
                "sale_ok": False,
            }
        )
        main_product = self.env["product.template"].create(
            {
                "name": "Main product",
                "website_published": True,
                "optional_product_ids": [Command.set(optional_product.ids)],
            }
        )

        with MockRequest(self.env, website=self.website):
            show_configurator = (
                self.pc_controller.website_sale_should_show_product_configurator(
                    product_template_id=main_product.id,
                    ptav_ids=[],
                    is_product_configured=False,
                )
            )
            configurator_values = (
                self.pc_controller.website_sale_product_configurator_get_values(
                    product_template_id=main_product.id,
                    quantity=1,
                    currency_id=self.currency.id,
                    so_date="2000-01-01",
                    pricelist_id=self.pricelist.id,
                )
            )

        self.assertFalse(show_configurator)
        self.assertListEqual(configurator_values["optional_products"], [])

    def test_product_configurator_extra_price_taxes(self):
        self.website.show_line_subtotals_tax_selection = "tax_included"
        tax = self.env["account.tax"].create({"name": "Tax", "amount": 10})
        attribute = self.env["product.attribute"].create(
            {
                "name": "Attribute",
                "value_ids": [Command.create({"name": "A", "default_extra_price": 1})],
            }
        )
        product = self.env["product.template"].create(
            {
                "name": "Product",
                "website_published": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    ),
                ],
                "taxes_id": tax,
            }
        )

        with MockRequest(self.env, website=self.website):
            ptav_price_extra = self.pc_controller._get_ptav_price_extra(
                product.attribute_line_ids.product_template_value_ids,
                self.currency,
                datetime(2000, 1, 1),
                product,
            )

        self.assertEqual(ptav_price_extra, 1.1)

    def test_product_configurator_zero_priced(self):
        self.website.prevent_zero_price_sale = True
        price_attribute = self.env["product.attribute"].create(
            {
                "name": "Price",
                "value_ids": [
                    Command.create({"name": "Zero-priced"}),
                    Command.create(
                        {"name": "Nonzero-priced", "default_extra_price": 1}
                    ),
                ],
            }
        )
        optional_product = self.env["product.template"].create(
            {
                "name": "Optional product",
                "website_published": True,
                "list_price": 0,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": price_attribute.id,
                            "value_ids": [Command.set(price_attribute.value_ids.ids)],
                        }
                    ),
                ],
            }
        )
        self.env["product.template"].create(
            {
                "name": "Main product",
                "website_published": True,
                "optional_product_ids": [Command.set(optional_product.ids)],
            }
        )
        self.start_tour("/", "website_sale_product_configurator_zero_priced")

    def test_product_configurator_strikethrough_price(self):
        self.env["res.config.settings"].create(
            {
                "group_product_price_comparison": True,
                "group_product_pricelist": True,
            }
        ).execute()
        self.website.show_line_subtotals_tax_selection = "tax_included"
        tax = self.env["account.tax"].create({"name": "Tax", "amount": 10})
        optional_product = self.env["product.template"].create(
            {
                "name": "Optional product",
                "website_published": True,
                "list_price": 5,
                "compare_list_price": 10,
                "taxes_id": tax,
            }
        )
        main_product = self.env["product.template"].create(
            {
                "name": "Main product",
                "website_published": True,
                "list_price": 100,
                "optional_product_ids": [Command.set(optional_product.ids)],
                "taxes_id": tax,
            }
        )
        self.pricelist.item_ids = [
            Command.create(
                {
                    "applied_on": "1_product",
                    "percent_price": 50,
                    "compute_price": "percentage",
                    "product_tmpl_id": main_product.id,
                }
            ),
        ]
        self.start_tour(
            "/shop", "website_sale_product_configurator_strikethrough_price"
        )

    def test_get_product_combination_multi_attribute_with_archived_variant_and_inactive_ptav(
        self,
    ):
        attribute_single = self.env["product.attribute"].create(
            {
                "name": "attribute single",
                "value_ids": [
                    Command.create(
                        {
                            "name": "single",
                        }
                    ),
                ],
            }
        )
        attribute_multi = self.env["product.attribute"].create(
            {
                "name": "attribute multi",
                "value_ids": [
                    Command.create({"name": "first"}),
                    Command.create({"name": "second"}),
                    Command.create({"name": "third"}),
                ],
            }
        )
        main_product = self.env["product.template"].create(
            {
                "name": "Main product",
                "website_published": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute_single.id,
                            "value_ids": [Command.set(attribute_single.value_ids.ids)],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": attribute_multi.id,
                            "value_ids": [Command.set(attribute_multi.value_ids.ids)],
                        }
                    ),
                ],
            }
        )
        main_product.product_variant_ids.filtered(
            lambda product: (
                product.product_template_attribute_value_ids[1].name == "first"
            ),
        ).action_archive()
        main_product.attribute_line_ids[1].product_template_value_ids[
            0
        ].ptav_active = False
        with MockRequest(self.env, website=self.website):
            product_values = self.pc_controller._prepare_product_values(
                main_product,
                self.env["product.public.category"],
                attribute_values=str(attribute_single.value_ids.id),
            )
        is_combination_possible = product_values["combination_info"][
            "is_combination_possible"
        ]
        combination_product_id = product_values["combination_info"]["product_id"]
        self.assertTrue(is_combination_possible)
        self.assertTrue(
            self.env["product.product"].browse(combination_product_id).active
        )
