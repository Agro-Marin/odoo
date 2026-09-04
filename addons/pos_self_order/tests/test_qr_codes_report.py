from odoo.tests import TransactionCase, tagged

REPORT = "pos_self_order.report_self_order_qr_codes_page"


@tagged("post_install", "-at_install")
class TestQrCodesReport(TransactionCase):
    """How the QR-codes sheet may be reached.

    The sheet is built entirely from a `data` dict assembled by the
    self-ordering settings page. There is no `_get_report_values` behind it,
    so any other route to the same report renders a document with no QR
    codes on it at all.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref(REPORT)
        cls.config = cls.env["pos.config"].search([], limit=1)

    def test_the_print_menu_of_a_register_does_not_offer_the_sheet(self):
        """A route that cannot produce QR codes is not offered."""
        bindings = self.env["ir.actions.actions"].get_bindings("pos.config")
        self.assertNotIn(
            self.report.id,
            [action["id"] for action in bindings.get("report", [])],
            "the QR-codes report has no report values, so it must not be bound",
        )

    def test_rendering_without_the_settings_data_produces_no_qr_codes(self):
        """This is why the route is not offered.

        Rendered against records instead of the settings payload, QWeb
        resolves every missing variable to nothing: the sheet comes out with
        its headings and not one code on it.
        """
        html = self.env["ir.actions.report"]._render_qweb_html(REPORT, self.config.ids)[
            0
        ]
        self.assertNotIn(b"/report/barcode/QR/", html)
