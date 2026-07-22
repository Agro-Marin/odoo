"""Tests for the contacts systray activity-icon override."""

from odoo import modules
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestActivityIcon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Activity partner"})
        cls.activity_type = cls.env.ref("mail.mail_activity_data_todo")
        cls.env["mail.activity"].create(
            {
                "res_model_id": cls.env["ir.model"]._get_id("res.partner"),
                "res_id": cls.partner.id,
                "activity_type_id": cls.activity_type.id,
                "user_id": cls.env.user.id,
                "summary": "Call the partner",
            }
        )

    def test_partner_activity_uses_contacts_icon(self):
        """The res.partner activity group is re-iconed with the contacts icon."""
        contacts_icon = modules.module.Manifest.for_addon("contacts").icon
        groups = self.env["res.users"]._get_activity_groups()
        partner_groups = [g for g in groups if g.get("model") == "res.partner"]
        self.assertTrue(partner_groups, "expected a res.partner activity group")
        for group in partner_groups:
            self.assertEqual(group["icon"], contacts_icon)

    def test_other_models_keep_their_icon(self):
        """Non-partner activity groups are left untouched (boundary)."""
        contacts_icon = modules.module.Manifest.for_addon("contacts").icon
        groups = self.env["res.users"]._get_activity_groups()
        for group in groups:
            if group.get("model") != "res.partner":
                self.assertNotEqual(group.get("icon"), contacts_icon)
