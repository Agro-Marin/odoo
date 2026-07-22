"""Tests for the spreadsheet.dashboard model helpers."""

import json

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDashboardModel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = cls.env["spreadsheet.dashboard.group"].create({"name": "SD test group"})
        cls.dashboard = cls.env["spreadsheet.dashboard"].create(
            {
                "name": "SD test dashboard",
                "dashboard_group_id": group.id,
                "spreadsheet_data": json.dumps({"sheets": []}),
            }
        )

    def test_serialized_readonly_dashboard_is_valid_json(self):
        """The readonly serialization embeds the snapshot and revisions keys."""
        payload = json.loads(self.dashboard._get_serialized_readonly_dashboard())
        self.assertIn("snapshot", payload)
        self.assertIn("revisions", payload)
        self.assertIn("default_currency", payload)

    def test_sample_dashboard_missing_file_returns_none(self):
        """Without a sample file the sample loader degrades to None (boundary)."""
        self.dashboard.sample_dashboard_file_path = "does/not/exist.json"
        self.assertIsNone(self.dashboard._get_sample_dashboard())
