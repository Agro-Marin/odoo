from unittest.mock import patch

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.base.tests.common import HttpCaseWithUserPortal
from odoo.addons.sale.tests.common import SaleCommon


@tagged("post_install", "-at_install")
class TestAccessRightsControllers(HttpCase, SaleCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.user_portal = cls._create_new_portal_user()

    @mute_logger("odoo.addons.base.models.ir_model", "odoo.addons.base.models.ir_rule")
    def test_access_controller(self):
        private_so = self.sale_order
        portal_so = self.sale_order.copy()
        portal_so.partner_id = self.user_portal.partner_id.id

        portal_so._portal_ensure_token()
        token = portal_so.access_token

        self.authenticate(None, None)

        req = self.url_open(
            url="/my/orders/%s?report_type=pdf" % portal_so.id,
            allow_redirects=False,
        )
        self.assertEqual(req.status_code, 303)

        req = self.url_open(
            url="/my/orders/%s?access_token=%s&report_type=pdf"
            % (
                portal_so.id,
                "foo",
            ),
            allow_redirects=False,
        )
        self.assertEqual(req.status_code, 303)

        req = self.url_open(
            url="/my/orders/%s?access_token=%s&report_type=pdf"
            % (
                portal_so.id,
                token,
            ),
            allow_redirects=False,
        )
        self.assertEqual(req.status_code, 200)

        self.authenticate(self.user_portal.login, self.user_portal.login)

        req = self.url_open(
            url="/my/orders/%s?report_type=pdf" % portal_so.id,
            allow_redirects=False,
        )
        self.assertEqual(req.status_code, 200)

        req = self.url_open(
            url="/my/orders/%s?report_type=pdf" % private_so.id,
            allow_redirects=False,
        )
        self.assertEqual(req.status_code, 303)


@tagged("post_install", "-at_install")
class TestSalesControllers(HttpCase, SaleCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.user_portal = cls._create_new_portal_user()

    def test_sales_portal_report(self):
        portal_so = self.sale_order.copy()
        portal_so.message_subscribe(self.user_portal.partner_id.ids)

        self.authenticate(None, None)

        req = self.url_open(
            portal_so.get_portal_url(report_type="pdf"), allow_redirects=False
        )
        self.assertEqual(req.status_code, 200)
        self.assertEqual(
            req.headers["content-disposition"],
            f"inline; filename*=UTF-8''Quotation_{portal_so.name}.pdf",
        )

        req = self.url_open(
            portal_so.get_portal_url(report_type="pdf", download=True),
            allow_redirects=False,
        )
        self.assertEqual(req.status_code, 200)
        self.assertEqual(
            req.headers["content-disposition"],
            f"attachment; filename*=UTF-8''Quotation_{portal_so.name}.pdf",
        )

    def _viewed_message_count(self, order):
        subtype = self.env.ref("sale.mt_order_viewed")
        return len(order.message_ids.filtered(lambda m: m.subtype_id == subtype))

    def test_viewed_note_only_posts_for_draft_orders(self):
        """The "Quotation viewed by customer" note must only post for a
        draft/unconfirmed order, not a confirmed one (F20)."""
        confirmed_so = self.sale_order.copy()
        confirmed_so.message_subscribe(self.user_portal.partner_id.ids)
        confirmed_so.action_confirm()
        self.assertEqual(confirmed_so.state, "done")

        self.authenticate(None, None)
        req = self.url_open(confirmed_so.get_portal_url(), allow_redirects=False)
        self.assertEqual(req.status_code, 200)
        self.assertEqual(
            self._viewed_message_count(confirmed_so),
            0,
            "a confirmed order must not get the customer-viewed note",
        )

        draft_so = self.sale_order.copy()
        draft_so.message_subscribe(self.user_portal.partner_id.ids)
        self.assertEqual(draft_so.state, "draft")

        req = self.url_open(draft_so.get_portal_url(), allow_redirects=False)
        self.assertEqual(req.status_code, 200)
        self.assertEqual(
            self._viewed_message_count(draft_so),
            1,
            "a draft order must still get the customer-viewed note",
        )

    def test_signature_acceptance_propagates_signature_context(self):
        """After online signature acceptance, _confirm_order() must be
        called with sale_include_signature=True so the confirmation email's
        PDF shows the signature (F21)."""
        self.sale_order.company_id.portal_confirmation_sign = True
        self.sale_order._portal_ensure_token()

        seen_contexts = []
        original_confirm_order = type(self.sale_order)._confirm_order

        def _spy_confirm_order(recordset, *args, **kwargs):
            seen_contexts.append(dict(recordset.env.context))
            return original_confirm_order(recordset, *args, **kwargs)

        self.authenticate(None, None)
        with patch.object(type(self.sale_order), "_confirm_order", _spy_confirm_order):
            result = self.make_jsonrpc_request(
                f"/my/orders/{self.sale_order.id}/accept",
                {
                    "access_token": self.sale_order.access_token,
                    "name": "A Customer",
                    "signature": (
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
                        "2mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                    ),
                },
                timeout=60,
            )

        self.assertNotIn("error", result or {})
        self.assertEqual(len(seen_contexts), 1)
        self.assertTrue(seen_contexts[0].get("sale_include_signature"))


@tagged("post_install", "-at_install", "mail_flow")
class TestSaleSignature(HttpCaseWithUserPortal):
    def test_01_portal_sale_signature_tour(self):
        portal_user_partner = self.partner_portal
        sales_order = self.env["sale.order"].create(
            {
                "name": "test SO",
                "partner_id": portal_user_partner.id,
                "sent": True,
                "require_payment": False,
            }
        )
        self.env["sale.order.line"].create(
            {
                "order_id": sales_order.id,
                "product_id": self.env["product.product"]
                .create({"name": "A product"})
                .id,
            }
        )
        self.assertFalse(sales_order.message_partner_ids)

        email_act = sales_order.action_send_quotation()
        email_ctx = email_act.get("context", {})
        sales_order.with_context(**email_ctx).message_post_with_source(
            self.env["mail.template"].browse(email_ctx.get("default_template_id")),
            subtype_xmlid="mail.mt_comment",
        )
        self.assertFalse(
            sales_order.message_partner_ids,
            "Do not automatically set customer as follower, will be suggested recipient",
        )

        self.start_tour("/", "sale_signature", login="portal")
