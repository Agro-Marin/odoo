from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestPortalShareTarget(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.recipient = cls.env["res.partner"].create(
            {"name": "Share Recipient", "email": "share.recipient@example.com"}
        )
        cls.non_portal_record = cls.env["res.partner"].create({"name": "Share Target"})

    def _wizard_on(self, res_model, res_id):
        return self.env["portal.share"].create(
            {
                "res_model": res_model,
                "res_id": res_id,
                "partner_ids": [(6, 0, self.recipient.ids)],
            }
        )

    def test_reading_a_non_portal_target_does_not_raise(self):
        wizard = self._wizard_on("res.partner", self.non_portal_record.id)
        values = wizard.read(["resource_ref", "share_link", "access_warning"])[0]
        self.assertFalse(
            values["resource_ref"],
            "a model outside the mixin.portal hierarchy has no shareable "
            "reference, so the field must come back empty rather than raise",
        )
        self.assertFalse(values["share_link"])

    def test_unknown_model_does_not_raise(self):
        wizard = self._wizard_on("no.such.model", 1)
        values = wizard.read(["resource_ref", "share_link"])[0]
        self.assertFalse(values["resource_ref"])
        self.assertFalse(values["share_link"])

    def test_missing_res_id_does_not_raise(self):
        wizard = self._wizard_on("res.partner", 0)
        self.assertFalse(wizard.resource_ref)
        self.assertFalse(wizard.share_link)

    def test_sending_to_a_non_portal_target_is_refused_cleanly(self):
        wizard = self._wizard_on("res.partner", self.non_portal_record.id)
        messages_before = self.env["mail.message"].search_count([])
        with self.assertRaises(UserError):
            wizard.action_send_mail()
        self.assertEqual(
            self.env["mail.message"].search_count([]),
            messages_before,
            "no share mail may be posted for an unshareable target",
        )

    def test_default_get_from_a_non_portal_active_model(self):
        wizard = (
            self.env["portal.share"]
            .with_context(
                active_model="res.partner", active_id=self.non_portal_record.id
            )
            .create({"partner_ids": [(6, 0, self.recipient.ids)]})
        )
        self.assertEqual(wizard.res_model, "res.partner")
        self.assertFalse(wizard.read(["resource_ref"])[0]["resource_ref"])
