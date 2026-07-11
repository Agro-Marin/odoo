"""Plan-C envelope-version stamp tests for ``project.project.get_template_tasks``.

``get_template_tasks`` returns a ``list`` (via ``search_read``) and uses the
envelope-side channel (``@versioned_envelope`` from
``odoo.tools.cache_version``) instead of in-payload stamping.

These tests exercise the full HTTP round-trip and assert the JSON-RPC
envelope carries the ``version`` sibling — the same contract verified for
``web_read`` in ``addons/web/tests/test_search_panel_version.py`` but
applied to the project-side opt-in introduced in Phase 4a.
"""

import json

from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install", "web_http", "web_search_panel")
class TestGetTemplateTasksEnvelopeVersion(HttpCase):
    """``get_template_tasks`` is consumed by ``project_task_template_dropdown.js``
    (and the FSM override) with ``update: "always"`` caching, making it a
    candidate for envelope versioning.  These tests pin the wire contract.
    """

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
        """POST a real call_kw to /web/dataset/call_kw/project.project/get_template_tasks."""
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
        # Confirm the envelope path is the right vehicle: result is a list.
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
