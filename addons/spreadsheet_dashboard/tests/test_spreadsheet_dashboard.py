import json

from odoo import Command
from odoo.exceptions import UserError

from .common import DashboardTestCommon


class TestSpreadsheetDashboard(DashboardTestCommon):
    def test_create_with_default_values(self):
        group = self.env["spreadsheet.dashboard.group"].create({"name": "a group"})
        dashboard = self.env["spreadsheet.dashboard"].create(
            {
                "name": "a dashboard",
                "dashboard_group_id": group.id,
            }
        )
        self.assertEqual(dashboard.group_ids, self.env.ref("base.group_user"))
        self.assertEqual(
            json.loads(dashboard.spreadsheet_data), dashboard._empty_spreadsheet_data()
        )

    def test_copy_name(self):
        group = self.env["spreadsheet.dashboard.group"].create({"name": "a group"})
        dashboard = self.env["spreadsheet.dashboard"].create(
            {
                "name": "a dashboard",
                "dashboard_group_id": group.id,
            }
        )
        copy = dashboard.copy()
        self.assertEqual(copy.name, "a dashboard (copy)")

        copy = dashboard.copy({"name": "a copy"})
        self.assertEqual(copy.name, "a copy")

    def test_copy_group_name(self):
        group = self.env["spreadsheet.dashboard.group"].create({"name": "My section"})

        copy = group.copy()
        self.assertEqual(copy.name, "My section (copy)")

        copy = group.copy({"name": "a copy"})
        self.assertEqual(copy.name, "a copy")

    def test_copy_group_name_in_every_language(self):
        # `name` is translate=True: renaming it in copy_data only touches the
        # duplicating user's language, so the copy would keep the source term
        # verbatim everywhere else.
        self.env["res.lang"]._activate_lang("fr_FR")
        group = self.env["spreadsheet.dashboard.group"].create({"name": "My section"})
        group.with_context(lang="fr_FR").name = "Ma section"

        copy = group.copy()
        self.assertEqual(copy.with_context(lang="en_US").name, "My section (copy)")
        # each language gets its own translation of the marker
        self.assertEqual(copy.with_context(lang="fr_FR").name, "Ma section (copie)")

    def test_action_open_dashboard(self):
        dashboard = self.create_dashboard()
        action = dashboard.action_open_dashboard()
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "action_spreadsheet_dashboard")
        self.assertEqual(action["params"]["dashboard_id"], dashboard.id)

    def test_allowed_user_can_read_a_dashboard_with_no_group(self):
        dashboard = self.env["spreadsheet.dashboard"].create(
            {
                "name": "user-restricted dashboard",
                "dashboard_group_id": self.env["spreadsheet.dashboard.group"]
                .create({"name": "a section"})
                .id,
                "group_ids": [],
                "allowed_user_ids": [Command.link(self.user.id)],
            }
        )
        as_user = self.env["spreadsheet.dashboard"].with_user(self.user)
        self.assertEqual(as_user.search([("id", "=", dashboard.id)]), dashboard)

    def test_user_outside_allowed_users_cannot_read_it(self):
        dashboard = self.env["spreadsheet.dashboard"].create(
            {
                "name": "private dashboard",
                "dashboard_group_id": self.env["spreadsheet.dashboard.group"]
                .create({"name": "a section"})
                .id,
                "group_ids": [],
                "allowed_user_ids": [],
            }
        )
        as_user = self.env["spreadsheet.dashboard"].with_user(self.user)
        self.assertFalse(as_user.search([("id", "=", dashboard.id)]))

    def test_group_access_still_works_alongside_allowed_users(self):
        # the two grants are OR-ed, so naming no user must not narrow the
        # existing group-based access
        dashboard = self.create_dashboard()
        self.assertFalse(dashboard.allowed_user_ids)
        as_user = self.env["spreadsheet.dashboard"].with_user(self.user)
        self.assertEqual(as_user.search([("id", "=", dashboard.id)]), dashboard)

    def test_unlink_prevent_spreadsheet_group(self):
        group = self.env["spreadsheet.dashboard.group"].create({"name": "a_group"})
        self.env["ir.model.data"].create(
            {
                "name": group.name,
                "module": "spreadsheet_dashboard",
                "model": group._name,
                "res_id": group.id,
            }
        )
        with self.assertRaises(
            UserError, msg="You cannot delete a_group as it is used in another module"
        ):
            group.unlink()

    def test_unpublish_dashboard(self):
        group = self.env["spreadsheet.dashboard.group"].create(
            {"name": "Dashboard group"}
        )
        dashboard = self.create_dashboard(group)
        self.assertEqual(group.published_dashboard_ids, dashboard)
        dashboard.is_published = False
        self.assertFalse(group.published_dashboard_ids)

    def test_publish_dashboard(self):
        group = self.env["spreadsheet.dashboard.group"].create(
            {"name": "Dashboard group"}
        )
        dashboard = self.create_dashboard(group)
        dashboard.is_published = False
        self.assertFalse(group.published_dashboard_ids)
        dashboard.is_published = True
        self.assertEqual(group.published_dashboard_ids, dashboard)

    def test_toggle_favorite(self):
        dashboard = self.create_dashboard().with_user(self.user)

        self.assertFalse(dashboard.is_user_favorite)
        self.assertNotIn(self.user, dashboard.favorite_user_ids)

        dashboard.with_user(self.user).action_toggle_user_favorite()

        self.assertTrue(dashboard.is_user_favorite)
        self.assertIn(self.user, dashboard.favorite_user_ids)

        dashboard.with_user(self.user).action_toggle_user_favorite()

        self.assertFalse(dashboard.is_user_favorite)
        self.assertNotIn(self.user, dashboard.favorite_user_ids)
