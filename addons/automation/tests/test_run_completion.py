from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from .test_workflow_dag import link


class RunCompletionCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Action = self.env["ir.actions.server"]
        self.model_partner = self.env["ir.model"]._get("res.partner")
        self.partner = self.env["res.partner"].create({"name": "Completion Partner"})
        self.automation = self.env["automation.rule"].create(
            {
                "name": "Completion",
                "model_id": self.model_partner.id,
                "trigger": "on_hand",
            }
        )

    def _action(self, name, code="pass", **kw):
        return self.Action.create(
            {
                "name": name,
                "model_id": self.model_partner.id,
                "state": "code",
                "code": code,
                "automation_rule_id": self.automation.id,
                "usage": "automation",
                **kw,
            }
        )

    def _run(self):
        runtime = self.env["automation.runtime"].create(
            {
                "automation_id": self.automation.id,
                "res_model": "res.partner",
                "res_id": self.partner.id,
            }
        )
        runtime.action_start()
        runtime.action_run_all()
        return runtime

    def _line(self, runtime, action):
        return runtime.line_ids.filtered(lambda step: step.action_id == action)


class TestUntakenBranches(RunCompletionCase):
    def test_a_false_branch_is_skipped_and_the_run_finishes(self):
        first = self._action("first")
        taken = self._action("taken")
        untaken = self._action("untaken", "record.write({'ref': 'untaken ran'})")
        link(self.env, first, taken, condition="expression", condition_expr="True")
        link(self.env, first, untaken, condition="expression", condition_expr="False")

        runtime = self._run()

        self.assertEqual(self._line(runtime, untaken).state, "skipped")
        self.assertEqual(runtime.state, "done")
        self.partner.invalidate_recordset(["ref"])
        self.assertFalse(self.partner.ref)

    def test_an_error_handler_is_skipped_when_its_source_succeeds(self):
        work = self._action("work")
        handler = self._action("handler")
        link(self.env, work, handler, condition="on_error")

        runtime = self._run()

        self.assertEqual(self._line(runtime, handler).state, "skipped")
        self.assertEqual(runtime.state, "done")

    def test_a_skip_propagates_down_the_untaken_path(self):
        first = self._action("first")
        untaken = self._action("untaken")
        further = self._action("further")
        link(self.env, first, untaken, condition="expression", condition_expr="False")
        link(self.env, untaken, further, condition="always")

        runtime = self._run()

        self.assertEqual(self._line(runtime, further).state, "skipped")
        self.assertEqual(runtime.state, "done")

    def test_an_exclusive_choice_rejoins(self):
        first = self._action("first")
        yes = self._action("yes")
        no = self._action("no")
        join = self._action("join", "record.write({'ref': 'joined'})")
        link(self.env, first, yes, condition="expression", condition_expr="True")
        link(self.env, first, no, condition="expression", condition_expr="False")
        link(self.env, yes, join)
        link(self.env, no, join)

        runtime = self._run()

        self.assertEqual(self._line(runtime, no).state, "skipped")
        self.assertEqual(self._line(runtime, join).state, "done")
        self.assertEqual(runtime.state, "done")
        self.partner.invalidate_recordset(["ref"])
        self.assertEqual(self.partner.ref, "joined")

    @mute_logger("odoo.addons.automation.models.automation_runtime_line")
    def test_a_join_behind_a_handled_failure_is_skipped(self):
        good = self._action("good")
        bad = self._action("bad", "raise ValueError('boom')")
        handler = self._action("handler")
        join = self._action("join")
        link(self.env, good, join)
        link(self.env, bad, join)
        link(self.env, bad, handler, condition="on_error")

        runtime = self._run()

        self.assertEqual(self._line(runtime, handler).state, "done")
        self.assertEqual(self._line(runtime, join).state, "skipped")
        self.assertEqual(runtime.state, "done")

    def test_a_parallel_join_still_waits_for_every_branch(self):
        first = self._action("first")
        pause = self._action("pause", node_type="wait", wait_delay=1)
        other = self._action("other")
        join = self._action("join")
        link(self.env, first, pause)
        link(self.env, first, other)
        link(self.env, pause, join)
        link(self.env, other, join)

        runtime = self._run()

        self.assertEqual(self._line(runtime, join).state, "waiting")
        self.assertEqual(runtime.state, "waiting_resume")


class TestTerminalPauses(RunCompletionCase):
    def test_a_run_ending_on_a_wait_finishes_when_it_resumes(self):
        first = self._action("first")
        pause = self._action("pause", node_type="wait", wait_delay=1)
        link(self.env, first, pause)
        runtime = self._run()
        self.assertEqual(runtime.state, "waiting_resume")

        self._line(runtime, pause).date_resume = self.env.cr.now()
        self.env["automation.runtime"]._resume_waiting_executions()

        self.assertEqual(self._line(runtime, pause).state, "done")
        self.assertEqual(runtime.state, "done")

    def test_a_run_ending_on_an_approval_finishes_when_approved(self):
        approver = self.env["res.users"].create(
            {
                "name": "Terminal Approver",
                "login": "terminal_approver_wf",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        gate = self._action(
            "gate",
            node_type="approval",
            approval_user_ids=[(6, 0, approver.ids)],
        )
        runtime = self._run()
        self.assertEqual(runtime.state, "waiting_resume")

        self._line(runtime, gate).activity_ids._action_done()

        self.assertEqual(runtime.state, "done")


class TestResumeScheduling(RunCompletionCase):
    def test_the_resume_cron_is_active(self):
        cron = self.env.ref("automation.ir_cron_data_automation_resume")

        self.assertTrue(cron.active)

    def test_a_wait_asks_the_resume_cron_to_run_when_it_is_due(self):
        cron = self.env.ref("automation.ir_cron_data_automation_resume")
        pause = self._action("pause", node_type="wait", wait_delay=2, wait_unit="hour")

        runtime = self._run()

        due = self._line(runtime, pause).date_resume
        triggers = self.env["ir.cron.trigger"].search([("cron_id", "=", cron.id)])
        self.assertIn(due, triggers.mapped("call_at"))
