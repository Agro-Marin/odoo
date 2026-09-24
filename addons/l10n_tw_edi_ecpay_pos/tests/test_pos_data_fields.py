from odoo.tests import TransactionCase, tagged


@tagged("post_install", "post_install_l10n", "-at_install")
class TestPosClientFields(TransactionCase):
    def test_the_ecpay_flag_reaches_the_browser(self):
        config = self.env["pos.config"]
        self.assertIn("is_ecpay_enabled", config._load_pos_data_fields(config.browse()))

    def test_the_invoice_choices_the_till_makes_travel_with_the_order(self):
        """The payment screen writes these on the order and `_prepare_invoice_vals`
        reads them back; a field missing from the order payload makes the round
        trip silently, and the e-invoice is issued without its carrier or love
        code."""
        order = self.env["pos.order"]
        sent = set(order._load_pos_data_fields(self.env["pos.config"].browse()))
        self.assertLessEqual(
            {
                "l10n_tw_edi_is_print",
                "l10n_tw_edi_love_code",
                "l10n_tw_edi_carrier_type",
                "l10n_tw_edi_carrier_number",
                "l10n_tw_edi_carrier_number_2",
            },
            sent,
        )
