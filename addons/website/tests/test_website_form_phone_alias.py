from odoo import Command
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.addons.website.controllers.form import WebsiteForm


@tagged("post_install", "-at_install")
class TestWebsiteFormPhoneAlias(TransactionCase):
    def test_whitelisting_a_phone_field_whitelists_phone_ids(self):
        fields = self.env["ir.model.fields"]

        self.assertTrue(fields.formbuilder_whitelist("res.partner", ["name", "phone"]))

        self.env.invalidate_all()
        phone_ids = fields.search(
            [("model", "=", "res.partner"), ("name", "=", "phone_ids")]
        )
        self.assertFalse(phone_ids.website_form_blacklisted)

    def test_a_field_the_model_does_not_have_is_still_refused(self):
        with self.assertRaises(ValueError):
            self.env["ir.model.fields"].formbuilder_whitelist(
                "res.partner", ["no_such_field"]
            )

    def test_a_posted_phone_lands_in_phone_ids(self):
        partner_model = self.env["ir.model"]._get("res.partner")
        partner_model.website_form_access = True
        self.env["ir.model.fields"].formbuilder_whitelist(
            "res.partner", ["name", "phone"]
        )

        with MockRequest(self.env, website=self.env["website"].browse(1)):
            data = WebsiteForm().extract_data(
                partner_model.sudo(), {"name": "Caller", "phone": "+32 470 00 00 00"}
            )

        self.assertEqual(
            data["record"]["phone_ids"],
            [Command.create({"number": "+32 470 00 00 00", "type": "mobile"})],
        )
