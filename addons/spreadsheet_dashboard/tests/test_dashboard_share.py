from odoo.exceptions import AccessError
from odoo.tests.common import new_test_user

from .common import DashboardTestCommon

EXCEL_FILES = [
    {
        "content": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "path": "[Content_Types].xml",
    }
]


class DashboardSharing(DashboardTestCommon):
    def test_share_url(self):
        dashboard = self.create_dashboard()
        share_vals = {
            "spreadsheet_data": dashboard.spreadsheet_data,
            "dashboard_id": dashboard.id,
            "excel_files": EXCEL_FILES,
        }
        url = self.env["spreadsheet.dashboard.share"].action_get_share_url(share_vals)
        share = self.env["spreadsheet.dashboard.share"].search(
            [("dashboard_id", "=", dashboard.id)]
        )
        self.assertEqual(url, share.full_url)
        self.assertEqual(share.dashboard_id, dashboard)
        self.assertEqual(share.name, "a dashboard - Share Link")
        self.assertTrue(share.excel_export)

    def test_can_create_own(self):
        dashboard = self.create_dashboard()
        with self.with_user(self.user.login):
            share = self.share_dashboard(dashboard)

        self.assertTrue(share)
        self.assertTrue(share.create_uid, self.user)

    def test_cannot_read_others(self):
        dashboard = self.create_dashboard()
        share = self.share_dashboard(dashboard)
        with self.assertRaises(AccessError):
            _ = share.with_user(self.user).access_token

    def test_name_is_editable(self):
        dashboard = self.create_dashboard()
        share = self.share_dashboard(dashboard)
        share.name = "Q3 board for the auditors"
        dashboard.name = "renamed dashboard"
        self.assertEqual(share.name, "Q3 board for the auditors")

    def test_revoking_a_link_keeps_the_record(self):
        dashboard = self.create_dashboard()
        share = self.share_dashboard(dashboard)
        self.assertTrue(share.active)
        share.active = False
        self.assertTrue(share.exists())
        self.assertFalse(
            self.env["spreadsheet.dashboard.share"].search([("id", "=", share.id)])
        )

    def test_dashboard_manager_sees_every_share(self):
        dashboard = self.create_dashboard()
        with self.with_user(self.user.login):
            own_share = self.share_dashboard(dashboard)
        other = new_test_user(self.env, login="Jeanne")
        other.group_ids |= self.group
        with self.with_user(other.login):
            other_share = self.share_dashboard(dashboard)

        as_manager = self.env["spreadsheet.dashboard.share"].with_user(
            self.dashboard_manager
        )
        self.assertEqual(as_manager.search([]), own_share | other_share)
        as_user = self.env["spreadsheet.dashboard.share"].with_user(self.user)
        self.assertEqual(as_user.search([]), own_share)
