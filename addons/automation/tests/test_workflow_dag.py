import logging

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

_logger = logging.getLogger(__name__)


class TestWorkflowDAG(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Automation = self.env["automation.rule"]
        self.Action = self.env["ir.actions.server"]
        self.Runtime = self.env["automation.runtime"]
        self.Partner = self.env["res.partner"]

        self.model_partner = self.env["ir.model"]._get("res.partner")
        self.test_partner = self.Partner.create({"name": "Test Partner"})

        self.automation = self.Automation.create(
            {
                "name": "Test DAG Workflow",
                "model_id": self.model_partner.id,
                "trigger": "on_hand",
            }
        )

    def _create_action(self, name, code="pass", predecessors=None):
        vals = {
            "name": name,
            "model_id": self.model_partner.id,
            "state": "code",
            "code": code,
            "automation_rule_id": self.automation.id,
            "usage": "automation",
        }
        if predecessors:
            vals["predecessor_ids"] = [Command.set([p.id for p in predecessors])]
        return self.Action.create(vals)

    def _make_runtime(self, automation=None):
        auto = automation or self.automation
        runtime = self.Runtime.create(
            {
                "automation_id": auto.id,
                "res_model": "res.partner",
                "res_id": self.test_partner.id,
            }
        )
        runtime.action_start()
        return runtime

    def _line_for(self, runtime, action):
        return runtime.line_ids.filtered(lambda l: l.action_id == action)

    def test_successor_relationship(self):
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])

        self.assertIn(action_b, action_a.successor_ids)
        self.assertIn(action_a, action_b.predecessor_ids)

    def test_cycle_detection_direct(self):
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])

        with self.assertRaises(ValidationError):
            action_a.write({"predecessor_ids": [Command.link(action_b.id)]})

    def test_cycle_detection_indirect(self):
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])
        action_c = self._create_action("C", predecessors=[action_b])

        with self.assertRaises(ValidationError):
            action_a.write({"predecessor_ids": [Command.link(action_c.id)]})

    def test_self_dependency_prevented(self):
        action_a = self._create_action("A")

        with self.assertRaises(ValidationError):
            action_a.write({"predecessor_ids": [Command.link(action_a.id)]})

    def test_runtime_lines_created_from_dag(self):
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])
        action_c = self._create_action("C", predecessors=[action_b])

        runtime = self._make_runtime()

        line_a = self._line_for(runtime, action_a)
        line_b = self._line_for(runtime, action_b)
        line_c = self._line_for(runtime, action_c)

        self.assertEqual(line_a.state, "ready")
        self.assertEqual(line_b.state, "waiting")
        self.assertEqual(line_c.state, "waiting")

        self.assertIn(line_a, line_b.predecessor_ids)
        self.assertIn(line_b, line_c.predecessor_ids)

    def test_parallel_branches_both_ready(self):
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])
        action_c = self._create_action("C", predecessors=[action_a])

        runtime = self._make_runtime()
        line_a = self._line_for(runtime, action_a)
        line_b = self._line_for(runtime, action_b)
        line_c = self._line_for(runtime, action_c)

        self.assertEqual(line_a.state, "ready")
        self.assertEqual(line_b.state, "waiting")
        self.assertEqual(line_c.state, "waiting")

        line_a.action_mark_done()

        self.assertEqual(line_b.state, "ready")
        self.assertEqual(line_c.state, "ready")

    def test_diamond_join(self):
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])
        action_c = self._create_action("C", predecessors=[action_a])
        action_d = self._create_action("D", predecessors=[action_b, action_c])

        runtime = self._make_runtime()
        line_a = self._line_for(runtime, action_a)
        line_b = self._line_for(runtime, action_b)
        line_c = self._line_for(runtime, action_c)
        line_d = self._line_for(runtime, action_d)

        line_a.action_mark_done()

        self.assertEqual(line_b.state, "ready")
        self.assertEqual(line_c.state, "ready")
        self.assertEqual(line_d.state, "waiting", "D still needs B and C")
        self.assertFalse(line_d._predecessors_satisfied(), "D still needs B and C")

        line_b.action_mark_done()
        self.assertEqual(line_d.state, "waiting", "D still needs C")
        self.assertFalse(line_d._predecessors_satisfied(), "D still needs C")

        line_c.action_mark_done()
        self.assertEqual(line_d.state, "ready", "D ready after both B and C")
        self.assertTrue(line_d._predecessors_satisfied())

    def test_multiple_root_actions(self):
        action_a = self._create_action("A")
        action_b = self._create_action("B")

        runtime = self._make_runtime()
        line_a = self._line_for(runtime, action_a)
        line_b = self._line_for(runtime, action_b)

        self.assertEqual(line_a.state, "ready")
        self.assertEqual(line_b.state, "ready")

    def test_runtime_completes_when_all_lines_done(self):
        action_a = self._create_action("A")

        runtime = self._make_runtime()
        self.assertEqual(runtime.state, "in_progress")

        line_a = self._line_for(runtime, action_a)
        line_a.action_mark_done()

        self.assertEqual(runtime.state, "done")

    def test_runtime_progress_display(self):
        action_a = self._create_action("A")
        self._create_action("B", predecessors=[action_a])

        runtime = self._make_runtime()
        self.assertEqual(runtime.progress_display, "0/2 steps")

        self._line_for(runtime, action_a).action_mark_done()
        runtime.invalidate_recordset(["progress_display"])
        self.assertEqual(runtime.progress_display, "1/2 steps")

    def test_run_all_simple_chain(self):
        action_a = self._create_action("A", code="record.write({'comment': 'A'})")
        action_b = self._create_action(
            "B", code="record.write({'comment': 'B'})", predecessors=[action_a]
        )
        self._create_action(
            "C", code="record.write({'comment': 'C'})", predecessors=[action_b]
        )

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "res_model": "res.partner",
                "res_id": self.test_partner.id,
            }
        )
        runtime.action_start()
        final_state = runtime.action_run_all()

        self.assertEqual(final_state, "done")
        self.assertEqual(runtime.state, "done")

        for line in runtime.line_ids:
            self.assertEqual(line.state, "done", f"Line '{line.name}' should be done")

    def test_run_all_parallel_branches(self):
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])
        action_c = self._create_action("C", predecessors=[action_a])
        self._create_action("D", predecessors=[action_b, action_c])

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "res_model": "res.partner",
                "res_id": self.test_partner.id,
            }
        )
        runtime.action_start()
        final_state = runtime.action_run_all()

        self.assertEqual(final_state, "done")
        for line in runtime.line_ids:
            self.assertEqual(line.state, "done")

    def test_manual_trigger_dag_creates_runtime(self):
        action_a = self._create_action("A")
        self._create_action("B", predecessors=[action_a])

        before_count = self.Runtime.search_count(
            [("automation_id", "=", self.automation.id)]
        )

        self.automation.with_context(
            active_model="res.partner",
            active_ids=self.test_partner.ids,
        ).action_manual_trigger()

        after_count = self.Runtime.search_count(
            [("automation_id", "=", self.automation.id)]
        )
        self.assertEqual(after_count, before_count + 1)

    def test_manual_trigger_no_dag_direct_process(self):
        self._create_action("A", code="record.write({'comment': 'triggered'})")

        before_count = self.Runtime.search_count(
            [("automation_id", "=", self.automation.id)]
        )

        result = self.automation.with_context(
            active_model="res.partner",
            active_ids=self.test_partner.ids,
        ).action_manual_trigger()

        after_count = self.Runtime.search_count(
            [("automation_id", "=", self.automation.id)]
        )
        self.assertEqual(after_count, before_count)
        self.assertEqual(result["type"], "ir.actions.client")
        self.assertEqual(result["params"]["type"], "success")

    def test_manual_trigger_wrong_trigger_raises(self):
        auto = self.Automation.create(
            {
                "name": "Write Automation",
                "model_id": self.model_partner.id,
                "trigger": "on_write",
            }
        )

        with self.assertRaises(ValidationError):
            auto.action_manual_trigger()

    def test_manual_trigger_no_matching_records(self):
        self.automation.filter_domain = (
            "[('name', '=', '__no_record_will_ever_match__')]"
        )
        self._create_action("A")

        result = self.automation.with_context(
            active_model="res.partner",
            active_ids=self.test_partner.ids,
        ).action_manual_trigger()

        self.assertEqual(result["params"]["type"], "warning")

    def test_runtime_cancel(self):
        action_a = self._create_action("A")
        self._create_action("B", predecessors=[action_a])

        runtime = self._make_runtime()
        runtime.action_cancel()

        self.assertEqual(runtime.state, "cancel")
        for line in runtime.line_ids:
            self.assertIn(line.state, ["cancel", "done"])

    def test_runtime_res_model_res_id_set(self):
        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "res_model": "res.partner",
                "res_id": self.test_partner.id,
            }
        )

        self.assertEqual(runtime.res_model, "res.partner")
        self.assertEqual(runtime.res_id, self.test_partner.id)


class TestWorkflowDAGExecution(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Automation = self.env["automation.rule"]
        self.Action = self.env["ir.actions.server"]
        self.Runtime = self.env["automation.runtime"]
        self.model_partner = self.env["ir.model"]._get("res.partner")
        self.test_partner = self.env["res.partner"].create(
            {"name": "Exec Test Partner"}
        )

    def test_code_execution_writes_to_target_record(self):
        automation = self.Automation.create(
            {
                "name": "Email Setter",
                "model_id": self.model_partner.id,
                "trigger": "on_hand",
            }
        )
        action_a = self.Action.create(
            {
                "name": "Set Email",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'email': 'dag@example.com'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )
        self.Action.create(
            {
                "name": "Set Phone",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'phone': '999-888-7777'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
                "predecessor_ids": [Command.link(action_a.id)],
            }
        )

        runtime = self.Runtime.create(
            {
                "automation_id": automation.id,
                "res_model": "res.partner",
                "res_id": self.test_partner.id,
            }
        )
        runtime.action_start()
        runtime.action_run_all()

        self.assertEqual(runtime.state, "done")
        self.test_partner.invalidate_recordset(["email", "phone"])
        self.assertEqual(self.test_partner.email, "dag@example.com")
        self.assertEqual(self.test_partner.phone, "999-888-7777")

    @mute_logger("odoo.addons.automation.models.automation_runtime_line")
    def test_error_in_action_marks_line_error(self):
        automation = self.Automation.create(
            {
                "name": "Failing Workflow",
                "model_id": self.model_partner.id,
                "trigger": "on_hand",
            }
        )
        action = self.Action.create(
            {
                "name": "Failing Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "raise Exception('deliberate test error')",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        runtime = self.Runtime.create(
            {
                "automation_id": automation.id,
                "res_model": "res.partner",
                "res_id": self.test_partner.id,
            }
        )
        runtime.action_start()

        line = runtime.line_ids.filtered(lambda l: l.action_id == action)

        self.assertFalse(line.action_execute(), "a failed step reports False")

        self.assertEqual(line.state, "error")
        self.assertIn("deliberate test error", line.error_message)
        self.assertEqual(runtime.state, "error", "the run itself is marked failed")

    @mute_logger("odoo.addons.automation.models.automation_runtime_line")
    def test_run_all_stops_the_batch_and_settles_stranded_lines_on_failure(self):
        automation = self.Automation.create(
            {
                "name": "Batch Failure Workflow",
                "model_id": self.model_partner.id,
                "trigger": "on_hand",
            }
        )
        action_fails = self.Action.create(
            {
                "name": "A-fails",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "raise Exception('deliberate test error')",
                "automation_rule_id": automation.id,
                "usage": "automation",
                "sequence": 1,
            }
        )
        action_sibling = self.Action.create(
            {
                "name": "B-sibling",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'comment': 'B-ran'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
                "sequence": 2,
            }
        )
        action_successor = self.Action.create(
            {
                "name": "C-depends-on-A",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'comment': 'C-ran'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
                "sequence": 3,
                "predecessor_ids": [Command.link(action_fails.id)],
            }
        )

        runtime = self.Runtime.create(
            {
                "automation_id": automation.id,
                "res_model": "res.partner",
                "res_id": self.test_partner.id,
            }
        )
        runtime.action_start()
        runtime.action_run_all()

        line_fails = runtime.line_ids.filtered(lambda l: l.action_id == action_fails)
        line_sibling = runtime.line_ids.filtered(
            lambda l: l.action_id == action_sibling
        )
        line_successor = runtime.line_ids.filtered(
            lambda l: l.action_id == action_successor
        )

        self.assertEqual(runtime.state, "error")
        self.assertEqual(line_fails.state, "error")
        self.assertEqual(
            line_sibling.state,
            "error",
            "an independent sibling must not run once the batch has failed",
        )
        self.assertEqual(
            line_successor.state,
            "error",
            "a successor of the failed step must not be left waiting forever",
        )
        self.test_partner.invalidate_recordset(["comment"])
        self.assertFalse(
            self.test_partner.comment,
            "the sibling's side effect must not have happened",
        )
