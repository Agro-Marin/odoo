from lxml import etree

import odoo
from odoo import Command

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@odoo.tests.tagged("post_install", "-at_install")
class TestConfigureShops(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_order_template = cls.env.ref(
            "sale_management.group_sale_order_template", raise_if_not_found=False
        )
        if group_order_template:
            cls.env.ref("base.group_user").write(
                {"implied_ids": [(4, group_order_template.id)]}
            )

    def test_total_rounding_setting_is_not_labelled_cash_only(self):
        """The setting rounds the order total whatever the payment method;
        `only_round_cash_method` is what narrows it to cash. Calling it "Cash
        Rounding" told the user the opposite."""
        arch = etree.fromstring(
            self.env["res.config.settings"].get_view(view_type="form")["arch"],
        )
        setting = arch.xpath(
            "//setting[@documentation="
            "'/applications/sales/point_of_sale/pricing/cash_rounding.html']",
        )
        self.assertTrue(setting, "the POS rounding setting reaches the settings page")

        self.assertEqual(setting[0].get("string"), "Total Rounding")
        self.assertEqual(
            setting[0].xpath(".//button[@type='action']")[0].get("string"),
            "Roundings",
        )
        self.assertEqual(
            setting[0]
            .xpath(".//label[@for='pos_only_round_cash_method']")[0]
            .get(
                "string",
            ),
            "Apply only on cash methods",
        )
        self.assertEqual(
            self.env["pos.config"]._fields["cash_rounding"].string,
            "Total Rounding",
        )
        self.assertEqual(
            self.env["pos.config"]._fields["rounding_method"].string,
            "Rounding Method",
        )

    def test_configuration_lists_guide_an_empty_screen(self):
        """Every POS configuration list a new shop lands on says what to put
        there, and shows sample rows instead of a bare grid."""
        actions = {
            "point_of_sale.action_pos_bill": "Add coins and bills",
            "point_of_sale.action_pos_note_model": "Create predefined notes",
            "point_of_sale.action_pos_preset_form": "Add a new preset",
            "point_of_sale.pos_product_attribute_action": "Create product attributes",
            "point_of_sale.pos_product_combo_choice_action": "Add combo choices",
        }
        for xmlid, expected in actions.items():
            action = self.env.ref(xmlid)
            self.assertIn(expected, action.help or "", xmlid)

        # The two new actions are POS-owned so the help does not leak into the
        # Sales menus; the menu items must point at them, not at product's.
        self.assertEqual(
            self.env.ref("point_of_sale.pos_menu_products_attribute_action").action,
            self.env.ref("point_of_sale.pos_product_attribute_action"),
        )
        self.assertEqual(
            self.env.ref("point_of_sale.menu_product_combo").action,
            self.env.ref("point_of_sale.pos_product_combo_choice_action"),
        )

        for xmlid in (
            "point_of_sale.view_pos_bill_tree",
            "point_of_sale.view_pos_preset_tree",
        ):
            self.assertEqual(
                etree.fromstring(self.env.ref(xmlid).arch).get("sample"),
                "1",
                xmlid,
            )

    def _remove_on_payment_taxes(self):
        self.env["account.tax"].search(
            [
                ("company_ids", "in", [self.env.company.id]),
                ("tax_exigibility", "=", "on_payment"),
            ]
        ).unlink()

    def test_properly_set_pos_config_x2many_fields(self):

        self._remove_on_payment_taxes()
        pos_config = self.env["pos.config"].create(
            {
                "name": "Shop 1",
                "module_pos_restaurant": False,
                "payment_method_ids": [
                    Command.create(
                        {
                            "name": "Bank 1",
                            "receivable_account_id": self.env.company.account_default_pos_receivable_account_id.id,
                            "is_cash_count": False,
                            "split_transactions": False,
                            "company_id": self.env.company.id,
                        }
                    ),
                    Command.create(
                        {
                            "name": "Bank 2",
                            "receivable_account_id": self.env.company.account_default_pos_receivable_account_id.id,
                            "is_cash_count": False,
                            "split_transactions": False,
                            "company_id": self.env.company.id,
                        }
                    ),
                    Command.create(
                        {
                            "name": "Cash",
                            "receivable_account_id": self.env.company.account_default_pos_receivable_account_id.id,
                            "is_cash_count": True,
                            "company_id": self.env.company.id,
                        }
                    ),
                ],
            }
        )

        linked_ids = pos_config.payment_method_ids.ids
        second_id = linked_ids[1]
        commands = [Command.link(_id) for _id in linked_ids if _id != second_id]

        pos_config.with_context(from_settings_view=True).write(
            {"payment_method_ids": commands}
        )

        self.assertTrue(second_id not in pos_config.payment_method_ids.ids)
        self.assertTrue(len(pos_config.payment_method_ids) == 2)

    def test_write_default_and_available_presets_on_multiple_pos_configs(self):
        preset = self.env["pos.preset"].create({"name": "Preset 1"})

        pos_config1 = self.env["pos.config"].create(
            {"name": "Shop 1", "module_pos_restaurant": False}
        )
        pos_config2 = self.env["pos.config"].create(
            {"name": "Shop 2", "module_pos_restaurant": False}
        )
        pos_config3 = self.env["pos.config"].create(
            {"name": "Shop 3", "module_pos_restaurant": False}
        )

        pos_configs = pos_config1 | pos_config2 | pos_config3

        pos_configs.write(
            {
                "use_presets": True,
                "available_preset_ids": [(6, 0, [preset.id])],
                "default_preset_id": preset.id,
            }
        )
