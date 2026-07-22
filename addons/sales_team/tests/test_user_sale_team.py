"""Tests for the user's computed primary sales team."""

from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestUserSaleTeam(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = mail_new_test_user(
            cls.env,
            login="sale_team_user",
            email="sale.team@example.com",
            groups="sales_team.group_sale_salesman",
        )
        cls.team = cls.env["crm.team"].create({"name": "STU team"})

    def test_no_membership_no_team(self):
        """A user without memberships has no sales team (boundary)."""
        self.user.invalidate_recordset(["sale_team_id"])
        self.assertFalse(self.user.sale_team_id)

    def test_membership_sets_sale_team(self):
        """A team membership sets the user's primary sales team."""
        self.env["crm.team.member"].create(
            {"user_id": self.user.id, "crm_team_id": self.team.id}
        )
        self.user.invalidate_recordset(["sale_team_id"])
        self.assertEqual(self.user.sale_team_id, self.team)

    def test_archive_user_archives_memberships(self):
        """Archiving a user archives its team memberships."""
        member = self.env["crm.team.member"].create(
            {"user_id": self.user.id, "crm_team_id": self.team.id}
        )
        self.user.action_archive()
        self.assertFalse(member.active)
