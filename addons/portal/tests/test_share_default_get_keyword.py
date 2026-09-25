from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestShareDefaultGetKeyword(TransactionCase):
    def test_default_get_takes_the_base_keyword(self):
        partner = self.env["res.partner"].create({"name": "Share target"})
        defaults = (
            self.env["portal.share"]
            .with_context(active_model="res.partner", active_id=partner.id)
            .default_get(fields=["res_model", "res_id"])
        )
        self.assertEqual(defaults["res_model"], "res.partner")
        self.assertEqual(defaults["res_id"], partner.id)
