from unittest.mock import patch

import requests

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_actions_server import (
    _get_webhook_log_target,
    _scrub_webhook_url,
)

_MODULE = "odoo.addons.base.models.ir_actions_server"
_SECRET = "T00000/B00000/xoxbSECRETTOKENvalue"
_URL = f"https://hooks.slack.com/services/{_SECRET}"


@tagged("post_install", "-at_install")
class TestWebhookLogTarget(TransactionCase):

    def test_only_the_host_survives(self):
        self.assertEqual(_get_webhook_log_target(_URL), "hooks.slack.com")

    def test_userinfo_and_port_do_not_survive(self):
        self.assertEqual(
            _get_webhook_log_target("https://user:pw@example.com:8443/hook?token=abc"),
            "example.com",
        )

    def test_a_url_with_no_host_still_names_something(self):
        self.assertEqual(_get_webhook_log_target("not a url"), "<unknown host>")

    def test_the_scrubber_removes_the_full_url(self):
        message = f"404 Client Error: Not Found for url: {_URL}"
        scrubbed = _scrub_webhook_url(message, _URL, "hooks.slack.com")
        self.assertNotIn(_SECRET, scrubbed)
        self.assertIn("404 Client Error", scrubbed, "the useful half stays")

    def test_the_scrubber_removes_a_bare_path(self):
        message = (
            "HTTPSConnectionPool(host='hooks.slack.com', port=443): Max retries "
            f"exceeded with url: /services/{_SECRET} (Caused by NameResolutionError)"
        )
        scrubbed = _scrub_webhook_url(message, _URL, "hooks.slack.com")
        self.assertNotIn(_SECRET, scrubbed)
        self.assertIn("Max retries exceeded", scrubbed)

    def test_the_scrubber_removes_a_query_token(self):
        url = "https://example.com/hook?token=abcd1234"
        scrubbed = _scrub_webhook_url(f"failed for url: {url}", url, "example.com")
        self.assertNotIn("abcd1234", scrubbed)

    def test_a_root_path_is_not_substituted_into_the_sentence(self):
        url = "https://example.com/"
        message = "Max retries exceeded with url: / (Caused by x/y/z)"
        self.assertEqual(_scrub_webhook_url(message, url, "example.com"), message)


@tagged("post_install", "-at_install")
class TestWebhookNeverLogsItsSecret(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "webhook target"})
        cls.model = cls.env["ir.model"]._get("res.partner")

    def _action(self, **vals):
        return self.env["ir.actions.server"].create(
            {
                "name": "notify",
                "model_id": self.model.id,
                "state": "webhook",
                "webhook_url": _URL,
                **vals,
            }
        )

    def _run(self, action):
        action.with_context(active_id=self.partner.id, active_model="res.partner").run()
        self.env.cr.precommit.run()
        self.env.cr.postcommit.run()

    def _captured(self, side_effect=None, level="DEBUG"):
        action = self._action()
        with (
            patch.object(requests, "post", side_effect=side_effect) as post,
            self.assertLogs(_MODULE, level=level) as logs,
        ):
            if side_effect is None:
                post.return_value.raise_for_status.return_value = None
            self._run(action)
        return "\n".join(logs.output), post

    @mute_logger(_MODULE)
    def test_a_successful_call_logs_the_host_and_not_the_token(self):
        output, post = self._captured()

        self.assertNotIn(_SECRET, output, "the token reached the log")
        self.assertIn("hooks.slack.com", output)
        self.assertIn("notify", output, "the action is what identifies it now")
        self.assertEqual(
            post.call_args.args[0],
            _URL,
            "the full URL must still reach requests -- only the log is trimmed",
        )

    @mute_logger(_MODULE)
    def test_a_timeout_logs_no_token(self):
        output, _post = self._captured(side_effect=requests.exceptions.ReadTimeout)
        self.assertNotIn(_SECRET, output)
        self.assertIn("may or may not", output)

    @mute_logger(_MODULE)
    def test_a_connection_error_logs_no_token(self):
        error = requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='hooks.slack.com', port=443): Max retries "
            f"exceeded with url: /services/{_SECRET} (Caused by NameResolutionError)"
        )
        output, _post = self._captured(side_effect=error)

        self.assertNotIn(_SECRET, output)
        self.assertIn("NOT be retried", output)
        self.assertIn("Max retries exceeded", output, "the diagnosis is still readable")

    @mute_logger(_MODULE)
    def test_an_http_error_logs_no_token(self):
        response = requests.Response()
        response.status_code = 404
        response.url = _URL
        error = requests.exceptions.HTTPError(
            f"404 Client Error: Not Found for url: {_URL}", response=response
        )
        output, _post = self._captured(side_effect=error)

        self.assertNotIn(_SECRET, output)
        self.assertIn("404", output)

    @mute_logger(_MODULE)
    def test_a_rollback_logs_no_token(self):
        action = self._action()
        with (
            patch.object(requests, "post") as post,
            self.assertLogs(_MODULE, level="WARNING") as logs,
        ):
            action.with_context(
                active_id=self.partner.id, active_model="res.partner"
            ).run()
            self.env.cr.postrollback.run()

        output = "\n".join(logs.output)
        self.assertNotIn(_SECRET, output)
        self.assertIn("rolled back", output)
        post.assert_not_called()
