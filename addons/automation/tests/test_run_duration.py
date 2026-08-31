import logging

from odoo import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.automation.models.automation_rule import job_log_level


@tagged("post_install", "-at_install")
class TestRunDurationLogLevel(TransactionCase):
    """The log level of an automation run scales with how long the run took."""

    def test_level_is_debug_for_a_fast_run(self):
        self.assertEqual(job_log_level("done", 0.05), logging.DEBUG)

    def test_level_is_info_past_a_tenth_of_a_second(self):
        self.assertEqual(job_log_level("done", 0.5), logging.INFO)

    def test_level_is_warning_past_a_second(self):
        self.assertEqual(job_log_level("done", 2), logging.WARNING)

    def test_level_is_error_whenever_the_run_did_not_finish(self):
        """A failed or aborted run is an error however fast it was."""
        self.assertEqual(job_log_level("failed", 0.01), logging.ERROR)
        self.assertEqual(job_log_level("aborted", 0.01), logging.ERROR)


@tagged("post_install", "-at_install")
class TestRunDurationLogged(TransactionCase):
    """Running a rule reports what its actions cost."""

    LOGGER = "odoo.addons.automation.models.automation_rule"

    def _make_rule_with_action(self):
        model = self.env.ref("base.model_res_partner")
        automation = self.env["automation.rule"].create(
            {
                "name": "Force Archived Contacts",
                "trigger": "on_create_or_write",
                "model_id": model.id,
            }
        )
        action = self.env["ir.actions.server"].create(
            {
                "name": "Set Active To False",
                "automation_rule_id": automation.id,
                "state": "object_write",
                "update_path": "active",
                "update_boolean_value": "false",
                "model_id": model.id,
            }
        )
        automation.write({"action_server_ids": [Command.link(action.id)]})
        return automation

    def test_a_run_logs_its_duration(self):
        """Without this, a rule that slows the server leaves no trace at all."""
        self._make_rule_with_action()
        with self.assertLogs(self.LOGGER, level=logging.DEBUG) as capture:
            partner = self.env["res.partner"].create({"name": "Bilbo Baggins"})
        self.assertFalse(partner.active, "the rule must actually have run")
        self.assertTrue(
            any("duration" in message for message in capture.output),
            f"no run duration was logged; got {capture.output}",
        )

    def test_the_duration_line_names_the_rule_and_the_record_count(self):
        """The line has to be actionable: which rule, over how many records."""
        automation = self._make_rule_with_action()
        with self.assertLogs(self.LOGGER, level=logging.DEBUG) as capture:
            self.env["res.partner"].create({"name": "Frodo Baggins"})
        lines = [message for message in capture.output if "duration" in message]
        self.assertTrue(lines, f"no run duration was logged; got {capture.output}")
        self.assertTrue(
            any("Force Archived Contacts" in line for line in lines),
            f"the duration line does not name the rule: {lines}",
        )
        self.assertTrue(
            any(str(automation.id) in line for line in lines),
            f"the duration line does not carry the rule id: {lines}",
        )
