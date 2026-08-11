from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestIrModelSmsCapability(TransactionCase):
    """Which models are offered as SMS targets.

    ``is_mail_thread_sms`` drives the model picker of SMS server actions and
    mailings. Offering a model that cannot actually be texted produces a
    send that fails later; hiding one that can makes the feature look
    unavailable.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrModel = cls.env["ir.model"]

    def _model_entry(self, name):
        return self.IrModel.search([("model", "=", name)], limit=1)

    def test_a_thread_carrying_a_phone_can_be_texted(self):
        """A mail thread with a phone number is a valid SMS target."""
        partner_model = self._model_entry("res.partner")
        self.assertTrue(partner_model.is_mail_thread)
        self.assertTrue(partner_model.is_mail_thread_sms)

    def test_a_phone_alone_does_not_make_a_model_textable(self):
        """Carrying a phone is not enough -- the model must be a thread.

        res.users holds both a phone and a partner yet is not a mail thread,
        so it must not be offered (negative).
        """
        users_model = self._model_entry("res.users")
        self.assertIn("phone", self.env["res.users"]._fields)
        self.assertFalse(users_model.is_mail_thread)
        self.assertFalse(users_model.is_mail_thread_sms)

    def test_a_model_with_neither_is_not_textable(self):
        """A plain model is never an SMS target (negative)."""
        self.assertFalse(self._model_entry("ir.model").is_mail_thread_sms)

    def test_the_search_finds_the_textable_models(self):
        """Searching for SMS targets returns them, partners included."""
        found = self.IrModel.search([("is_mail_thread_sms", "in", [True])])
        self.assertTrue(found)
        self.assertIn(self._model_entry("res.partner"), found)

    def test_the_search_and_the_field_never_disagree(self):
        """Both implementations of the rule must select the same models.

        The compute and the search repeat the same condition in two places,
        so they can drift apart silently; this pins them together.
        """
        selected = self.IrModel.search([("is_mail_thread_sms", "in", [True])])
        every_model = self.IrModel.search([])
        computed = every_model.filtered(
            lambda entry: entry.model in self.env and entry.is_mail_thread_sms
        )
        self.assertEqual(selected, computed)

    def test_an_unsupported_comparison_is_refused(self):
        """The field answers membership only, rather than anything else.

        Silently answering a comparison it does not implement would return
        every model as textable (negative).
        """
        with self.assertRaises(ValueError):
            self.IrModel.search([("is_mail_thread_sms", ">", 0)])
