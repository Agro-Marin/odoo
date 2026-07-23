# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResourceResourceCrud(TransactionCase):
    """resource.resource create/copy/write and company/user onchanges."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "CRUD Calendar", "tz": "Europe/Brussels"}
        )
        cls.user = cls.env["res.users"].create(
            {"name": "Resource User", "login": "res_crud_user", "tz": "Asia/Tokyo"}
        )
        cls.resource = cls.env["resource.resource"].create(
            {"name": "Machine", "calendar_id": cls.calendar.id}
        )

    def test_copy_appends_copy_to_name(self):
        """Copying a resource appends "(copy)" to its name."""
        copy = self.resource.copy()
        self.assertIn("(copy)", str(copy.name))

    def test_create_inherits_tz_from_calendar(self):
        """A resource created without a tz inherits the calendar's tz."""
        resource = self.env["resource.resource"].create(
            {"name": "Machine 2", "calendar_id": self.calendar.id}
        )
        self.assertEqual(resource.tz, "Europe/Brussels")

    def test_write_idempotence_skips_noop(self):
        """A no-op write under check_idempotence is dropped."""
        result = self.resource.with_context(check_idempotence=True).write(
            {"name": self.resource.name}
        )
        self.assertTrue(result)

    def test_compute_avatar_follows_user(self):
        """avatar_128 mirrors the linked user's avatar."""
        self.resource.user_id = self.user
        self.assertEqual(self.resource.avatar_128, self.user.avatar_128)

    def test_onchange_company_sets_calendar(self):
        """Setting the company populates the company default calendar."""
        resource = self.env["resource.resource"].new(
            {"company_id": self.env.company.id}
        )
        resource._onchange_company_id()
        self.assertEqual(resource.calendar_id, self.env.company.resource_calendar_id)

    def test_onchange_user_sets_tz(self):
        """Setting the user copies its timezone onto the resource."""
        resource = self.env["resource.resource"].new({"user_id": self.user.id})
        resource._onchange_user_id()
        self.assertEqual(resource.tz, self.user.tz)
