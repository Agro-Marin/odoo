from odoo.addons.account.tests.common import AccountTestInvoicingHttpCommon
from odoo.tests import tagged


@tagged("-at_install", "post_install")
class TestPortalInvoicePageViewParams(AccountTestInvoicingHttpCommon):
    """A query param must not collide with the invoice page-view arguments.

    ``/my/invoices/<id>`` forwards its leftover query string as ``**kw`` into
    ``_invoice_get_page_view_values(invoice, access_token, **kw)`` and on into
    ``portal``'s ``_get_page_view_values(document, access_token, values,
    session_history, no_breadcrumbs, **kwargs)``. Every one of those names was
    rebindable from the URL, producing ``TypeError: ... got multiple values for
    argument ...`` -- HTTP 500 on a route declared ``auth="public"``.

    They are positional-only now, so the same query param is simply ignored.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_partner = cls.env["res.partner"].create({"name": "Portal Invoice"})
        cls.env["res.users"].create(
            {
                "login": "portal_invoice_params",
                "password": "portal_invoice_params",
                "partner_id": cls.portal_partner.id,
                "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
            }
        )
        cls.invoice = cls.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": cls.portal_partner.id,
                "invoice_date": "2026-01-01",
                "invoice_line_ids": [
                    (0, 0, {"name": "line", "quantity": 1, "price_unit": 100.0})
                ],
            }
        )
        cls.invoice.action_post()

    def test_colliding_query_params_do_not_500(self):
        self.authenticate("portal_invoice_params", "portal_invoice_params")
        url = f"/my/invoices/{self.invoice.id}"
        self.assertEqual(self.url_open(url).status_code, 200, "baseline must render")

        for param in (
            # portal._get_page_view_values
            "document",
            "access_token_unused",
            "values",
            "session_history",
            "no_breadcrumbs",
            # account._invoice_get_page_view_values
            "invoice",
            # account_payment._invoice_get_page_view_values
            "payment",
            "amount",
        ):
            with self.subTest(param=param):
                response = self.url_open(f"{url}?{param}=x")
                self.assertEqual(
                    response.status_code,
                    200,
                    f"'?{param}=x' must be ignored, not rebind an internal argument",
                )
