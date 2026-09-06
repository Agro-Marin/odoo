from odoo.tests import tagged

from odoo.addons.sale.tests.common import SaleCommon


@tagged("post_install", "-at_install")
class TestSaleOrder(SaleCommon):
    def test_avoid_setting_pickup_location_as_default_delivery_address(self):
        self._create_partner(
            type="delivery", parent_id=self.partner.id, is_pickup_location=True
        )
        so = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.assertFalse(so.partner_shipping_id.is_pickup_location)

    def test_remove_delivery_line_resets_pickup_location_data(self):
        """A stale pickup location must not survive a carrier change.

        Nothing else in this module keeps `pickup_location_data` in sync with
        `carrier_id`, so `_remove_delivery_line` -- the method every carrier
        change goes through via `set_delivery_line` -- must reset it itself.
        """
        so = self.env["sale.order"].create({"partner_id": self.partner.id})
        so.pickup_location_data = {"name": "Stale pickup point"}
        so._remove_delivery_line()
        self.assertFalse(so.pickup_location_data)
