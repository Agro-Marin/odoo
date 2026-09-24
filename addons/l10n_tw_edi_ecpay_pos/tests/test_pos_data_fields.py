from odoo.tests import TransactionCase, tagged


@tagged("post_install", "post_install_l10n", "-at_install")
class TestPosClientFields(TransactionCase):
    def test_the_ecpay_flag_reaches_the_browser(self):
        config = self.env["pos.config"]
        self.assertIn("is_ecpay_enabled", config._load_pos_data_fields(config.browse()))
