from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestL10nDeConfig(AccountTestInvoicingCommon):
    @classmethod
    @AccountTestInvoicingCommon.setup_chart_template("de_skr03")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.state_id = cls.env.ref("base.state_de_by")
        cls.company.l10n_de_stnr = "181/815/08155"

    def test_a_state_change_revalidates_the_tax_number(self):
        with self.assertRaisesRegex(ValidationError, "SteuerNummer"):
            self.company.state_id = self.env.ref("base.state_de_be")

    def test_a_tax_number_change_is_tracked(self):
        config = self.company.l10n_de_config_id.with_context(
            tracking_disable=False, mail_notrack=False
        )
        config.l10n_de_widnr = "DE123456789-00001"
        self.cr.precommit.run()

        tracked = config.message_ids.tracking_value_ids.field_id.mapped("name")
        self.assertIn("l10n_de_widnr", tracked)
