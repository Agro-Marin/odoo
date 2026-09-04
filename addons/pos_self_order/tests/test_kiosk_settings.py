from lxml import etree

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKioskSettings(TransactionCase):
    def _combined_arch(self, model, view_xmlid):
        view = self.env.ref(view_xmlid)
        return etree.fromstring(self.env[model].get_view(view.id, "form")["arch"])

    def test_employee_login_is_hidden_on_a_kiosk_configuration(self):
        arch = self._combined_arch("pos.config", "point_of_sale.pos_config_view_form")

        setting = arch.xpath("//setting[@id='multiple_employee_session']")
        self.assertTrue(setting, "the employee login setting must be addressable by id")
        self.assertEqual(setting[0].get("invisible"), "self_ordering_mode == 'kiosk'")
        self.assertTrue(
            arch.xpath("//field[@name='self_ordering_mode']"),
            "the modifier is dead unless the form actually reads the field",
        )

    def test_tip_product_is_hidden_on_a_kiosk_configuration(self):
        arch = self._combined_arch(
            "res.config.settings", "point_of_sale.res_config_settings_view_form"
        )

        setting = arch.xpath("//setting[@id='iface_tipproduct']")
        self.assertTrue(setting)
        self.assertEqual(setting[0].get("invisible"), "is_kiosk_mode")
