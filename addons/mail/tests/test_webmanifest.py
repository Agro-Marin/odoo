import shutil
import subprocess
import tempfile
from pathlib import Path

from odoo.tests.common import tagged

from odoo.addons.base.tests.common import HttpCaseWithUserDemo


@tagged("-at_install", "post_install", "web_manifest")
class MailServiceWorkerTest(HttpCaseWithUserDemo):

    def _parse_check(self, source, label):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is required to syntax-check the service worker")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "service_worker.js"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run(
                [node, "--check", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(
            result.returncode,
            0,
            f"the {label} service worker does not parse:\n{result.stderr}",
        )

    def _fetch_service_worker(self):
        response = self.url_open("/web/service-worker.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers["Content-Type"])
        return response.text

    def test_service_worker_parses_for_a_public_visitor(self):
        source = self._fetch_service_worker()
        self._parse_check(source, "public")

    def test_service_worker_parses_for_an_internal_user(self):
        self.authenticate("admin", "admin")
        source = self._fetch_service_worker()
        self._parse_check(source, "internal")

    def test_internal_user_actually_gets_mails_half(self):
        public_source = self._fetch_service_worker()
        self.authenticate("admin", "admin")
        internal_source = self._fetch_service_worker()
        self.assertGreater(
            len(internal_source),
            len(public_source),
            "the internal service worker should carry mail's half as well",
        )
        self.assertIn("PUSH_NOTIFICATION_ACTION", internal_source)
        self.assertNotIn("PUSH_NOTIFICATION_ACTION", public_source)
