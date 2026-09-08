from odoo import Command
from odoo.tests.common import TransactionCase, new_test_user


class DashboardTestCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group = cls.env["res.groups"].create({"name": "test group"})
        cls.user = new_test_user(cls.env, login="Raoul", password="Raoul")
        cls.user.group_ids |= cls.group
        # Downloading a shared dashboard is an export, so it needs
        # ``base.group_allow_export``; ``cls.user`` deliberately lacks it.
        cls.exporter = new_test_user(
            cls.env,
            login="exporter",
            password="exporter",
            groups="base.group_user,base.group_allow_export",
        )
        cls.dashboard_manager = new_test_user(
            cls.env,
            login="dashboard_manager",
            groups="spreadsheet_dashboard.group_dashboard_manager",
        )

    def create_dashboard(self, group=None):
        dashboard_group = group or self.env["spreadsheet.dashboard.group"].create(
            {"name": "Dashboard group"}
        )
        return self.env["spreadsheet.dashboard"].create(
            {
                "name": "a dashboard",
                "group_ids": [Command.set(self.group.ids)],
                "dashboard_group_id": dashboard_group.id,
            }
        )

    def share_dashboard(self, dashboard, **values):
        return self.env["spreadsheet.dashboard.share"].create(
            {
                "dashboard_id": dashboard.id,
                "spreadsheet_data": dashboard.spreadsheet_data,
                **values,
            }
        )
