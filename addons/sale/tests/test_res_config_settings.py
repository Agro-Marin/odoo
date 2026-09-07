from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleSettingsShipping(TransactionCase):
    def _shipping_block(self):
        arch = etree.fromstring(
            self.env["res.config.settings"].get_view(view_type="form")["arch"]
        )
        blocks = arch.xpath("//block[@name='sale_shipping_setting_container']")
        self.assertEqual(len(blocks), 1, "the Sales shipping block should be unique")
        return blocks[0]

    def test_sales_settings_offer_delivery_methods_and_nothing_else(self):
        """Sales settings must not repeat Inventory's carrier connectors.

        The ten connector cards were declared twice, once here and once in
        `stock`, down to the same documentation links; four of them carry no
        field at all and only say to go to Apps. Sales keeps the switch that
        is its own, `module_delivery`, and the connectors stay in Inventory.
        """
        self.assertEqual(self._shipping_block().xpath(".//setting/@id"), ["delivery"])

    def test_sales_settings_declare_no_carrier_module_field(self):
        """No carrier connector field is reachable from the Sales page."""
        block = self._shipping_block()
        connector_fields = [
            name
            for name in block.xpath(".//field/@name")
            if name.startswith("module_delivery_")
        ]
        self.assertEqual(connector_fields, [])
