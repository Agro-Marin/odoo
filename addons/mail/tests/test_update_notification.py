from ast import literal_eval

from odoo.tests.common import TransactionCase

from odoo.addons.base.tests.test_cloc import TestClocCustomization


class TestUpdateNotification(TransactionCase):
    def test_user_count(self):
        ping_msg = (
            self.env["publisher_warranty.contract"]
            .with_context(active_test=False)
            ._get_message()
        )
        user_count = self.env["res.users"].search_count([("active", "=", True)])
        self.assertEqual(
            ping_msg.get("nbr_users"),
            user_count,
            "Update Notification: Users count is badly computed in ping message",
        )
        share_user_count = self.env["res.users"].search_count(
            [("active", "=", True), ("share", "=", True)]
        )
        self.assertEqual(
            ping_msg.get("nbr_share_users"),
            share_user_count,
            "Update Notification: Portal Users count is badly computed in ping message",
        )


class TestClocICP(TestClocCustomization):
    def test_check_cloc_result_in_icp(self):
        self.create_field("x_invoice_count")
        message = self.env["publisher_warranty.contract"]._get_message()
        self.assertTrue("maintenance" in message)
        store_cloc = self.env["ir.config_parameter"].get_param(
            "publisher_warranty.cloc"
        )
        self.assertEqual(literal_eval(store_cloc)["modules"]["odoo/studio"], 1)
