"""A webhook URL is usually a credential, and this action used to log it.

Slack, Discord and Teams all mint an incoming-webhook URL whose path IS the
secret — `hooks.slack.com/services/T…/B…/<token>` — and anyone holding it can
post to the channel. Others carry a token in the query string.
`_run_action_webhook` logged the whole URL five times per call, twice at INFO,
so it reached every log file, every aggregator and every traceback pasted into a
ticket.

Two channels had to close, not one. Keeping the URL out of our own format
strings does nothing about the libraries quoting it back:

    HTTPError    404 Client Error: … for url: https://host/services/T…/B…/<token>
    ConnError    HTTPSConnectionPool(host=…): Max retries exceeded with
                 url: /services/T…/B…/<token> (Caused by …)

Both were measured against real `requests` before this was written, which is why
the scrubber replaces the bare path as well as the full URL.
"""

from unittest.mock import patch

import requests

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_actions_server import (
    _webhook_log_target,
    _webhook_scrub,
)

_MODULE = "odoo.addons.base.models.ir_actions_server"
_SECRET = "T00000/B00000/xoxbSECRETTOKENvalue"
_URL = f"https://hooks.slack.com/services/{_SECRET}"


@tagged("post_install", "-at_install")
class TestWebhookLogTarget(TransactionCase):
    """The helpers, without a transaction."""

    def test_only_the_host_survives(self):
        self.assertEqual(_webhook_log_target(_URL), "hooks.slack.com")

    def test_userinfo_and_port_do_not_survive(self):
        self.assertEqual(
            _webhook_log_target("https://user:pw@example.com:8443/hook?token=abc"),
            "example.com",
        )

    def test_a_url_with_no_host_still_names_something(self):
        self.assertEqual(_webhook_log_target("not a url"), "<unknown host>")

    def test_the_scrubber_removes_the_full_url(self):
        message = f"404 Client Error: Not Found for url: {_URL}"
        scrubbed = _webhook_scrub(message, _URL, "hooks.slack.com")
        self.assertNotIn(_SECRET, scrubbed)
        self.assertIn("404 Client Error", scrubbed, "the useful half stays")

    def test_the_scrubber_removes_a_bare_path(self):
        """urllib3 quotes the path on its own, without the scheme or host."""
        message = (
            "HTTPSConnectionPool(host='hooks.slack.com', port=443): Max retries "
            f"exceeded with url: /services/{_SECRET} (Caused by NameResolutionError)"
        )
        scrubbed = _webhook_scrub(message, _URL, "hooks.slack.com")
        self.assertNotIn(_SECRET, scrubbed)
        self.assertIn("Max retries exceeded", scrubbed)

    def test_the_scrubber_removes_a_query_token(self):
        url = "https://example.com/hook?token=abcd1234"
        scrubbed = _webhook_scrub(f"failed for url: {url}", url, "example.com")
        self.assertNotIn("abcd1234", scrubbed)

    def test_a_root_path_is_not_substituted_into_the_sentence(self):
        """A path of "/" as a needle would rewrite every separator."""
        url = "https://example.com/"
        message = "Max retries exceeded with url: / (Caused by x/y/z)"
        self.assertEqual(_webhook_scrub(message, url, "example.com"), message)


@tagged("post_install", "-at_install")
class TestWebhookNeverLogsItsSecret(TransactionCase):
    """Through the action, which is where it actually leaked."""

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
        """Every line the action emits for one call, at the loosest level."""
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
        """The exception's own text is the channel this closes."""
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
