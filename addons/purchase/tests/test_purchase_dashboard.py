from datetime import timedelta

from odoo import fields
from odoo.tests import Form, new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.mail.tests.common import MailCase


@tagged("-at_install", "post_install")
class TestPurchaseDashboard(AccountTestInvoicingCommon, MailCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.user_a = new_test_user(
            cls.env,
            login="purchaseusera",
            groups="purchase.group_purchase_user,purchase.group_purchase_user_all",
        )
        cls.user_b = new_test_user(
            cls.env, login="purchaseuserb", groups="purchase.group_purchase_user"
        )

        product_data = {
            "name": "SuperProduct",
            "type": "consu",
        }
        cls.product_100 = cls.env["product.product"].create(
            {**product_data, "standard_price": 100}
        )
        cls.product_250 = cls.env["product.product"].create(
            {**product_data, "standard_price": 250}
        )

    @classmethod
    def default_env_context(cls):
        return {}

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_purchase_dashboard(self):
        rfqs = self.env["purchase.order"].create(
            [
                {
                    "partner_id": self.partner_a.id,
                    "company_id": self.user_a.company_id.id,
                    "currency_id": self.user_a.company_id.currency_id.id,
                    "date_order": fields.Date.today(),
                    "user_id": self.user_a.id if i == 0 else self.user_b.id,
                }
                for i in range(3)
            ]
        )
        for rfq, qty in zip(rfqs, [1, 2, 3], strict=True):
            rfq_form = Form(rfq)
            with rfq_form.line_ids.new() as line_1:
                line_1.product_id = self.product_100
                line_1.product_qty = qty
            with rfq_form.line_ids.new() as line_2:
                line_2.product_id = self.product_250
                line_2.product_qty = qty
            rfq_form.save()

        self.env["purchase.order"].create(
            [
                {
                    "partner_id": self.partner_a.id,
                    "company_id": self.user_a.company_id.id,
                    "currency_id": self.user_a.company_id.currency_id.id,
                    "date_order": fields.Date.today() - timedelta(days=7),
                    "user_id": self.user_b.id,
                }
            ]
        )

        self.env["purchase.order"].with_user(self.user_a).create(
            [
                {
                    "partner_id": self.partner_a.id,
                    "company_id": self.user_a.company_id.id,
                    "currency_id": self.user_a.company_id.currency_id.id,
                    "priority": "1",
                    "date_order": fields.Date().today() + timedelta(days=7),
                }
            ]
        )

        self.flush_tracking()
        with self.mock_mail_gateway():
            rfqs[0].with_user(self.user_a).write({"sent": True})
            self.flush_tracking()
        self.assertTrue(rfqs[0].sent)
        with self.mock_mail_gateway():
            rfqs[1].with_user(self.user_b).write({"sent": True})
            self.flush_tracking()
        self.assertTrue(rfqs[1].sent)

        rfqs.action_confirm()
        dashboard_result = rfqs.with_user(self.user_a).prepare_dashboard()

        self.assertFalse(dashboard_result["global"]["sent"]["all"])
        self.assertFalse(dashboard_result["my"]["late"]["all"])
        self.assertEqual(dashboard_result["global"]["draft"]["all"], 2)
        self.assertEqual(dashboard_result["global"]["draft"]["priority"], 1)
        self.assertEqual(dashboard_result["my"]["draft"]["all"], 1)
        self.assertEqual(dashboard_result["global"]["late"]["all"], 1)

        self.assertTrue(dashboard_result["multiuser"])

    def test_prepare_dashboard_multiuser_flag_single_user(self):
        self.env["purchase.order"].with_user(self.user_a).create(
            {
                "partner_id": self.partner_a.id,
                "company_id": self.user_a.company_id.id,
                "currency_id": self.user_a.company_id.currency_id.id,
            }
        )
        result = self.env["purchase.order"].with_user(self.user_a).prepare_dashboard()
        self.assertIn("multiuser", result)
        self.assertFalse(result["multiuser"])

    def test_send_reminder_preview_without_email_returns_dict(self):
        order = self.env["purchase.order"].create({"partner_id": self.partner_a.id})
        reminder_user = new_test_user(
            self.env,
            login="purchasereminder",
            groups="purchase.group_purchase_user,purchase.group_send_reminder",
            email=False,
        )
        result = order.with_user(reminder_user).send_reminder_preview()
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("toast_type"), "warning")
        self.assertTrue(result.get("toast_message"))

    def test_prepare_dashboard_days_to_order_is_numeric(self):
        result = self.env["purchase.order"].with_user(self.user_a).prepare_dashboard()
        for scope in ("global", "my"):
            self.assertIsInstance(
                result[scope]["days_to_order"],
                float,
                f"{scope}.days_to_order must be numeric for the template comparison",
            )

    def test_dashboard_cards_have_matching_search_filters(self):
        action = self.env.ref("purchase.action_purchase_order")
        arch = self.env["purchase.order"].get_views(
            [(action.search_view_id.id, "search")],
        )["views"]["search"]["arch"]
        for name in (
            "draft_rfqs",
            "waiting_rfqs",
            "late",
            "not_acknowledged",
            "late_receipt",
            "my_purchases",
        ):
            self.assertIn(
                f'name="{name}"',
                arch,
                f"dashboard card filter {name!r} is missing from the search view",
            )
