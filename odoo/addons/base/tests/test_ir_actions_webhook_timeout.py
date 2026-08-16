"""The webhook action's timeout, and the log line an operator has to act on.

`_run_action_webhook` sends an unauthenticated POST with a fixed one-second
timeout, catches the resulting `ReadTimeout` and logs that the call "may or may
not have failed". Neither the action nor the URL appeared in that message, so a
silent non-delivery was indistinguishable from any other line in the log — and
one second is short enough that a receiver which merely thinks for a moment hits
it.

The timeout is a field now, defaulting to the same 1 second so nothing changes
for an action already configured. What changed is that it CAN be changed, and
that both failure paths name what failed.
"""

from unittest.mock import patch

import requests

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestWebhookTimeout(TransactionCase):
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
                # A public host: `_webhook_url_blocked_reason` resolves DNS and
                # refuses anything that is not globally routable, so a loopback
                # URL never reaches the request at all.
                "webhook_url": "https://example.com/hook",
                **vals,
            }
        )

    def _run(self, action):
        action.with_context(active_id=self.partner.id, active_model="res.partner").run()
        self.env.cr.precommit.run()
        self.env.cr.postcommit.run()

    def test_the_default_is_the_historical_one_second(self):
        self.assertEqual(self._action().webhook_timeout, 1)

    def test_the_configured_timeout_reaches_the_request(self):
        action = self._action(webhook_timeout=12)
        with patch.object(requests, "post") as post:
            self._run(action)
        self.assertEqual(post.call_args.kwargs["timeout"], 12)

    @mute_logger("odoo.addons.base.models.ir_actions_server")
    def test_a_timeout_names_the_action_and_says_what_to_do(self):
        action = self._action()
        with (
            patch.object(requests, "post", side_effect=requests.exceptions.ReadTimeout),
            self.assertLogs(
                "odoo.addons.base.models.ir_actions_server", level="WARNING"
            ) as logs,
        ):
            self._run(action)

        message = "\n".join(logs.output)
        self.assertIn("notify", message, "the action must be identifiable")
        self.assertIn("example.com", message, "so must the receiver")
        self.assertIn("may or may not", message, "a timeout is genuinely ambiguous")

    @mute_logger("odoo.addons.base.models.ir_actions_server")
    def test_a_refusal_is_an_error_and_says_it_will_not_retry(self):
        """A connection failure is not ambiguous: it did not arrive."""
        action = self._action()
        with (
            patch.object(
                requests,
                "post",
                side_effect=requests.exceptions.ConnectionError("refused"),
            ),
            self.assertLogs(
                "odoo.addons.base.models.ir_actions_server", level="ERROR"
            ) as logs,
        ):
            self._run(action)

        message = "\n".join(logs.output)
        self.assertIn("notify", message)
        self.assertIn("NOT be retried", message)

    def test_the_ceiling_refuses_a_worker_holding_value(self):
        with self.assertRaises(ValidationError) as caught:
            self._action(webhook_timeout=600)
        self.assertIn("after the transaction commits", str(caught.exception))

    def test_zero_is_refused_rather_than_meaning_no_timeout(self):
        """requests treats timeout=0 as 'no timeout', which is the opposite."""
        with self.assertRaises(ValidationError):
            self._action(webhook_timeout=0)

    def test_the_ceiling_only_binds_webhook_actions(self):
        """A code action has no webhook to time out."""
        action = self.env["ir.actions.server"].create(
            {
                "name": "not a webhook",
                "model_id": self.model.id,
                "state": "code",
                "code": "pass",
                "webhook_timeout": 0,
            }
        )
        self.assertEqual(action.state, "code")
