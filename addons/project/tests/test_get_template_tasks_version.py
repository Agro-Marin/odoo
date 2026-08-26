import json

from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install", "web_http", "web_search_panel")
class TestGetTemplateTasksEnvelopeVersion(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["project.project"].create(
            {
                "name": "Plan-C Template Project",
            }
        )
        cls.template_task = cls.env["project.task"].create(
            {
                "name": "Plan-C Template Task A",
                "project_id": cls.project.id,
                "is_template": True,
            }
        )

    def _call(self):
        self.authenticate("admin", "admin")
        response = self.url_open(
            "/web/dataset/call_kw/project.project/get_template_tasks",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "model": "project.project",
                        "method": "get_template_tasks",
                        "args": [self.project.id],
                        "kwargs": {},
                    },
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_envelope_carries_version_sibling(self):
        envelope = self._call()
        self.assertIn("version", envelope, "envelope must carry version sibling")
        self.assertEqual(len(envelope["version"]), 64)
        self.assertIsInstance(envelope["result"], list)

    def test_same_query_same_version(self):
        v1 = self._call()["version"]
        v2 = self._call()["version"]
        self.assertEqual(v1, v2)

    def test_record_change_changes_version(self):
        v1 = self._call()["version"]
        self.template_task.name = "Plan-C Template Task A (renamed)"
        v2 = self._call()["version"]
        self.assertNotEqual(v1, v2)
