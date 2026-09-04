from freezegun import freeze_time

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest

# 20:00 on 9 March at America/Mexico_City is 02:00 on 10 March in UTC: inside
# this window `fields.Date.today()` has already rolled over while the cashier's
# calendar has not. Every register in this company closes inside it.
EVENING_IN_UTC = "2026-03-10 02:00:00"
LOCAL_TODAY = "2026-03-09"
LOCAL_TOMORROW = "2026-03-10"


@tagged("post_install", "-at_install")
class TestPosUserLocalDates(CommonPosTest):
    """Date-only decisions taken in the cashier's evening.

    A register is closed at the end of the working day, which at UTC-6 is
    already the next UTC date. Anything that compares a date-only value
    against `fields.Date.today()` is therefore reading tomorrow's calendar
    for the last six hours of every shift.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.tz = "America/Mexico_City"

    @freeze_time(EVENING_IN_UTC)
    def test_a_future_order_still_refuses_to_be_cancelled_in_the_evening(self):
        """An order to deliver tomorrow may not be voided, evening included.

        The guard exists so a cashier cannot void an order somebody is coming
        back for. Read in UTC it stops guarding at 18:00 local.
        """
        self.pos_config_usd.open_ui()
        order = self.env["pos.order"].create(
            {
                "session_id": self.pos_config_usd.current_session_id.id,
                "state": "draft",
                "preset_time": f"{LOCAL_TOMORROW} 21:00:00",
                "amount_tax": 0,
                "amount_total": 0,
                "amount_paid": 0,
                "amount_return": 0,
            }
        )
        with self.assertRaises(UserError):
            order.with_context(active_ids=order.ids).action_pos_order_cancel()
        self.assertEqual(order.state, "draft")

    @freeze_time(EVENING_IN_UTC)
    def test_a_pricelist_rule_ending_today_is_still_loaded_in_the_evening(self):
        """A promotion runs until closing time, not until 18:00.

        `date_end` is the last day the rule applies, so a register opened at
        20:00 local must still be sent it.
        """
        product_tmpl = self.env["product.template"].create(
            {"name": "Evening promotion product", "available_in_pos": True}
        )
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Evening promotion",
                "currency_id": self.env.company.currency_id.id,
            }
        )
        rule = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": pricelist.id,
                "product_tmpl_id": product_tmpl.id,
                "applied_on": "1_product",
                "compute_price": "fixed",
                "fixed_price": 5.0,
                "date_end": f"{LOCAL_TODAY} 23:59:59",
            }
        )
        self.pos_config_usd.write(
            {
                "use_pricelist": True,
                "available_pricelist_ids": [(4, pricelist.id)],
                "pricelist_id": pricelist.id,
            }
        )
        self.pos_config_usd.open_ui()
        session = self.pos_config_usd.current_session_id
        loaded = session.get_pos_ui_product_pricelist_item_by_product(
            product_tmpl.ids,
            product_tmpl.product_variant_ids.ids,
            self.pos_config_usd.id,
        )
        self.assertIn(
            rule.id,
            [item["id"] for item in loaded["product.pricelist.item"]],
            "a rule that runs to the end of the cashier's today must be loaded",
        )
