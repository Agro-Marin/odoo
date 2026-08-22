from odoo.tests import tagged

from odoo.addons.product.tests.test_product_attribute_value_config import (
    TestProductAttributeValueCommon,
)


@tagged("post_install", "-at_install")
class TestSaleProductAttributeValueConfig(TestProductAttributeValueCommon):
    def test_01_is_combination_possible_archived(self):
        def do_test(self):
            computer_ssd_256 = self._get_product_template_attribute_value(self.ssd_256)
            computer_ram_8 = self._get_product_template_attribute_value(self.ram_8)
            computer_hdd_1 = self._get_product_template_attribute_value(self.hdd_1)
            computer_hdd_2 = self._get_product_template_attribute_value(self.hdd_2)

            variant = self.computer._get_variant_for_combination(
                computer_ssd_256 + computer_ram_8 + computer_hdd_1
            )
            variant2 = self.computer._get_variant_for_combination(
                computer_ssd_256 + computer_ram_8 + computer_hdd_2
            )

            self.assertTrue(variant)
            self.assertTrue(variant2)

            so = self.env["sale.order"].create({"partner_id": 1})
            self.env["sale.order.line"].create(
                {"order_id": so.id, "name": "test", "product_id": variant.id}
            )
            self.env["sale.order.line"].create(
                {"order_id": so.id, "name": "test", "product_id": variant2.id}
            )

            variant2.active = False
            self.assertTrue(
                self.computer._is_combination_possible(
                    computer_ssd_256 + computer_ram_8 + computer_hdd_1
                )
            )
            self.assertFalse(
                self.computer._is_combination_possible(
                    computer_ssd_256 + computer_ram_8 + computer_hdd_2
                )
            )
            variant.active = False
            self.assertFalse(
                self.computer._is_combination_possible(
                    computer_ssd_256 + computer_ram_8 + computer_hdd_2
                )
            )
            self.assertFalse(
                self.computer._is_combination_possible(
                    computer_ssd_256 + computer_ram_8 + computer_hdd_1
                )
            )

            self.computer_hdd_attribute_lines.write({"active": False})
            self.assertTrue(
                self.computer._is_combination_possible(
                    computer_ssd_256 + computer_ram_8
                )
            )

            self.hdd_attribute.create_variant = "no_variant"
            self._add_hdd_attribute_line()
            computer_hdd_1 = self._get_product_template_attribute_value(self.hdd_1)
            computer_hdd_2 = self._get_product_template_attribute_value(self.hdd_2)

            self.assertTrue(
                self.computer._is_combination_possible(
                    computer_ssd_256 + computer_ram_8 + computer_hdd_1
                )
            )

            variant = self.computer._get_variant_for_combination(
                computer_ssd_256 + computer_ram_8 + computer_hdd_1
            )
            variant.active = False
            self.assertFalse(
                self.computer._is_combination_possible(
                    computer_ssd_256 + computer_ram_8 + computer_hdd_1
                )
            )

            self.computer_ssd_attribute_lines.write({"active": False})

            variant4 = self.computer._get_variant_for_combination(
                computer_ram_8 + computer_hdd_1
            )
            self.env["sale.order.line"].create(
                {"order_id": so.id, "name": "test", "product_id": variant4.id}
            )
            self.assertTrue(
                self.computer._is_combination_possible(computer_ram_8 + computer_hdd_1)
            )

            self.computer_hdd_attribute_lines.write({"active": False})
            self.hdd_attribute.create_variant = "always"
            self._add_hdd_attribute_line()
            computer_ssd_256 = self._get_product_template_attribute_value(self.ssd_256)
            computer_ram_8 = self._get_product_template_attribute_value(self.ram_8)
            computer_hdd_1 = self._get_product_template_attribute_value(self.hdd_1)
            computer_hdd_2 = self._get_product_template_attribute_value(self.hdd_2)

            variant5 = self.computer._get_variant_for_combination(
                computer_ram_8 + computer_hdd_1
            )
            self.env["sale.order.line"].create(
                {"order_id": so.id, "name": "test", "product_id": variant5.id}
            )

            self.assertTrue(variant4 != variant5)

            self.assertTrue(
                self.computer._is_combination_possible(computer_ram_8 + computer_hdd_1)
            )

        computer_ssd_256_before = self._get_product_template_attribute_value(
            self.ssd_256
        )

        do_test(self)

        self.computer_ssd_attribute_lines = self.env[
            "product.template.attribute.line"
        ].create(
            {
                "product_tmpl_id": self.computer.id,
                "attribute_id": self.ssd_attribute.id,
                "value_ids": [(6, 0, [self.ssd_256.id, self.ssd_512.id])],
            }
        )

        computer_ssd_256_after = self._get_product_template_attribute_value(
            self.ssd_256
        )
        self.assertEqual(computer_ssd_256_after, computer_ssd_256_before)
        self.assertEqual(
            computer_ssd_256_after.attribute_line_id,
            computer_ssd_256_before.attribute_line_id,
        )
        do_test(self)
