# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for DAG workflow execution via automation.runtime."""

import logging

from odoo import Command
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class TestWorkflowDAG(TransactionCase):
    """Test DAG dependency structure and automation.runtime execution."""

    def setUp(self):
        super().setUp()
        self.Automation = self.env["base.automation"]
        self.Action = self.env["ir.actions.server"]
        self.Runtime = self.env["automation.runtime"]
        self.Partner = self.env["res.partner"]

        self.model_partner = self.env["ir.model"]._get("res.partner")
        self.test_partner = self.Partner.create({"name": "Test Partner"})

        self.automation = self.Automation.create({
            "name": "Test DAG Workflow",
            "model_id": self.model_partner.id,
            "trigger": "on_hand",
        })

    def _create_action(self, name, code="pass", predecessors=None):
        """Create a server action under self.automation."""
        vals = {
            "name": name,
            "model_id": self.model_partner.id,
            "state": "code",
            "code": code,
            "base_automation_id": self.automation.id,
            "usage": "base_automation",
        }
        if predecessors:
            vals["predecessor_ids"] = [Command.set([p.id for p in predecessors])]
        return self.Action.create(vals)

    def _make_runtime(self, automation=None):
        """Create and start a runtime for the given automation (default: self.automation)."""
        auto = automation or self.automation
        runtime = self.Runtime.create({
            "automation_id": auto.id,
            "res_model": "res.partner",
            "res_id": self.test_partner.id,
        })
        runtime.action_start()
        return runtime

    def _line_for(self, runtime, action):
        """Return the runtime.line corresponding to a definition action."""
        return runtime.line_ids.filtered(lambda l: l.action_id == action)

    # =========================================================================
    # DAG Topology: predecessor/successor on ir.actions.server
    # =========================================================================

    def test_successor_relationship(self):
        """successor_ids is the inverse of predecessor_ids."""
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])

        self.assertIn(action_b, action_a.successor_ids)
        self.assertIn(action_a, action_b.predecessor_ids)

    def test_cycle_detection_direct(self):
        """Direct cycles (A → B → A) are prevented by constraint."""
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])

        with self.assertRaises(ValidationError):
            action_a.write({"predecessor_ids": [Command.link(action_b.id)]})

    def test_cycle_detection_indirect(self):
        """Indirect cycles (A → B → C → A) are prevented."""
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])
        action_c = self._create_action("C", predecessors=[action_b])

        with self.assertRaises(ValidationError):
            action_a.write({"predecessor_ids": [Command.link(action_c.id)]})

    def test_self_dependency_prevented(self):
        """An action cannot depend on itself."""
        action_a = self._create_action("A")

        with self.assertRaises(ValidationError):
            action_a.write({"predecessor_ids": [Command.link(action_a.id)]})

    # =========================================================================
    # automation.runtime: line creation mirrors DAG topology
    # =========================================================================

    def test_runtime_lines_created_from_dag(self):
        """_create_action_lines mirrors predecessor topology into runtime lines."""
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])
        action_c = self._create_action("C", predecessors=[action_b])

        runtime = self._make_runtime()

        line_a = self._line_for(runtime, action_a)
        line_b = self._line_for(runtime, action_b)
        line_c = self._line_for(runtime, action_c)

        # Root action starts ready
        self.assertEqual(line_a.state, "ready")
        # Dependents start waiting
        self.assertEqual(line_b.state, "waiting")
        self.assertEqual(line_c.state, "waiting")

        # DAG structure preserved in runtime lines
        self.assertIn(line_a, line_b.predecessor_ids)
        self.assertIn(line_b, line_c.predecessor_ids)

    def test_parallel_branches_both_ready(self):
        """Fan-out: completing A makes both B and C ready."""
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])
        action_c = self._create_action("C", predecessors=[action_a])

        runtime = self._make_runtime()
        line_a = self._line_for(runtime, action_a)
        line_b = self._line_for(runtime, action_b)
        line_c = self._line_for(runtime, action_c)

        # Only A is ready initially
        self.assertEqual(line_a.state, "ready")
        self.assertEqual(line_b.state, "waiting")
        self.assertEqual(line_c.state, "waiting")

        # Complete A
        line_a.action_mark_done()

        # Both B and C unblocked (parallel branches)
        self.assertEqual(line_b.state, "ready")
        self.assertEqual(line_c.state, "ready")

    def test_diamond_join(self):
        """Fan-in: D waits for both B and C (AND join)."""
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
        self.assertFalse(line_d.is_ready, "D still needs C")

        line_b.action_mark_done()
        # D still waiting — C hasn't completed yet
        self.assertEqual(line_d.state, "waiting", "D still needs C")
        self.assertFalse(line_d.is_ready, "is_ready only True when waiting+eligible")

        line_c.action_mark_done()
        # D unblocked — state transitions to ready; is_ready resets to False (by design)
        self.assertEqual(line_d.state, "ready", "D ready after both B and C")

    def test_multiple_root_actions(self):
        """Automations with multiple root actions start both as ready."""
        action_a = self._create_action("A")
        action_b = self._create_action("B")  # also a root

        runtime = self._make_runtime()
        line_a = self._line_for(runtime, action_a)
        line_b = self._line_for(runtime, action_b)

        self.assertEqual(line_a.state, "ready")
        self.assertEqual(line_b.state, "ready")

    def test_runtime_completes_when_all_lines_done(self):
        """Runtime transitions to 'done' when all lines complete."""
        action_a = self._create_action("A")

        runtime = self._make_runtime()
        self.assertEqual(runtime.state, "in_progress")

        line_a = self._line_for(runtime, action_a)
        line_a.action_mark_done()

        self.assertEqual(runtime.state, "done")

    def test_runtime_progress_display(self):
        """progress_display updates as lines complete."""
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])

        runtime = self._make_runtime()
        self.assertEqual(runtime.progress_display, "0/2 steps")

        self._line_for(runtime, action_a).action_mark_done()
        runtime.invalidate_recordset(["progress_display"])
        self.assertEqual(runtime.progress_display, "1/2 steps")

    # =========================================================================
    # automation.runtime: action_run_all executes DAG to completion
    # =========================================================================

    def test_run_all_simple_chain(self):
        """action_run_all executes A → B → C in order."""
        action_a = self._create_action("A", code="record.write({'comment': 'A'})")
        action_b = self._create_action("B", code="record.write({'comment': 'B'})",
                                       predecessors=[action_a])
        action_c = self._create_action("C", code="record.write({'comment': 'C'})",
                                       predecessors=[action_b])

        runtime = self.Runtime.create({
            "automation_id": self.automation.id,
            "res_model": "res.partner",
            "res_id": self.test_partner.id,
        })
        runtime.action_start()
        final_state = runtime.action_run_all()

        self.assertEqual(final_state, "done")
        self.assertEqual(runtime.state, "done")

        # All lines completed
        for line in runtime.line_ids:
            self.assertEqual(line.state, "done", f"Line '{line.name}' should be done")

    def test_run_all_parallel_branches(self):
        """action_run_all handles parallel branches correctly."""
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])
        action_c = self._create_action("C", predecessors=[action_a])
        action_d = self._create_action("D", predecessors=[action_b, action_c])

        runtime = self.Runtime.create({
            "automation_id": self.automation.id,
            "res_model": "res.partner",
            "res_id": self.test_partner.id,
        })
        runtime.action_start()
        final_state = runtime.action_run_all()

        self.assertEqual(final_state, "done")
        for line in runtime.line_ids:
            self.assertEqual(line.state, "done")

    # =========================================================================
    # action_manual_trigger routing
    # =========================================================================

    def test_manual_trigger_dag_creates_runtime(self):
        """action_manual_trigger creates automation.runtime for DAG automations."""
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])

        before_count = self.Runtime.search_count([("automation_id", "=", self.automation.id)])

        self.automation.with_context(
            active_model="res.partner",
            active_ids=self.test_partner.ids,
        ).action_manual_trigger()

        after_count = self.Runtime.search_count([("automation_id", "=", self.automation.id)])
        self.assertEqual(after_count, before_count + 1)

    def test_manual_trigger_no_dag_direct_process(self):
        """action_manual_trigger without DAG calls _process directly (no runtime)."""
        # Simple action, no predecessor_ids
        self._create_action("A", code="record.write({'comment': 'triggered'})")

        before_count = self.Runtime.search_count([("automation_id", "=", self.automation.id)])

        result = self.automation.with_context(
            active_model="res.partner",
            active_ids=self.test_partner.ids,
        ).action_manual_trigger()

        after_count = self.Runtime.search_count([("automation_id", "=", self.automation.id)])
        # No runtime created for simple automations
        self.assertEqual(after_count, before_count)
        self.assertEqual(result["type"], "ir.actions.client")
        self.assertEqual(result["params"]["type"], "success")

    def test_manual_trigger_wrong_trigger_raises(self):
        """action_manual_trigger on non-on_hand automation raises ValidationError."""
        auto = self.Automation.create({
            "name": "Write Automation",
            "model_id": self.model_partner.id,
            "trigger": "on_write",
        })

        with self.assertRaises(ValidationError):
            auto.action_manual_trigger()

    def test_manual_trigger_no_matching_records(self):
        """action_manual_trigger returns warning when filter excludes all records."""
        # Filter that no record can match
        self.automation.filter_domain = "[('name', '=', '__no_record_will_ever_match__')]"
        self._create_action("A")

        result = self.automation.with_context(
            active_model="res.partner",
            active_ids=self.test_partner.ids,
        ).action_manual_trigger()

        self.assertEqual(result["params"]["type"], "warning")

    # =========================================================================
    # automation.runtime: cancellation
    # =========================================================================

    def test_runtime_cancel(self):
        """Cancelling runtime cancels all non-done lines."""
        action_a = self._create_action("A")
        action_b = self._create_action("B", predecessors=[action_a])

        runtime = self._make_runtime()
        runtime.action_cancel()

        self.assertEqual(runtime.state, "cancel")
        for line in runtime.line_ids:
            self.assertIn(line.state, ["cancel", "done"])

    def test_runtime_res_model_res_id_set(self):
        """Runtime records the target model and record ID."""
        runtime = self.Runtime.create({
            "automation_id": self.automation.id,
            "res_model": "res.partner",
            "res_id": self.test_partner.id,
        })

        self.assertEqual(runtime.res_model, "res.partner")
        self.assertEqual(runtime.res_id, self.test_partner.id)


class TestWorkflowDAGExecution(TransactionCase):
    """Integration tests: actual server action code execution through automation.runtime."""

    def setUp(self):
        super().setUp()
        self.Automation = self.env["base.automation"]
        self.Action = self.env["ir.actions.server"]
        self.Runtime = self.env["automation.runtime"]
        self.model_partner = self.env["ir.model"]._get("res.partner")
        self.test_partner = self.env["res.partner"].create({"name": "Exec Test Partner"})

    def test_code_execution_writes_to_target_record(self):
        """Server action code runs against the runtime's res_model/res_id record."""
        automation = self.Automation.create({
            "name": "Email Setter",
            "model_id": self.model_partner.id,
            "trigger": "on_hand",
        })
        action_a = self.Action.create({
            "name": "Set Email",
            "model_id": self.model_partner.id,
            "state": "code",
            "code": "record.write({'email': 'dag@example.com'})",
            "base_automation_id": automation.id,
            "usage": "base_automation",
        })
        action_b = self.Action.create({
            "name": "Set Phone",
            "model_id": self.model_partner.id,
            "state": "code",
            "code": "record.write({'phone': '999-888-7777'})",
            "base_automation_id": automation.id,
            "usage": "base_automation",
            "predecessor_ids": [Command.link(action_a.id)],
        })

        runtime = self.Runtime.create({
            "automation_id": automation.id,
            "res_model": "res.partner",
            "res_id": self.test_partner.id,
        })
        runtime.action_start()
        runtime.action_run_all()

        self.assertEqual(runtime.state, "done")
        self.test_partner.invalidate_recordset(["email", "phone"])
        self.assertEqual(self.test_partner.email, "dag@example.com")
        self.assertEqual(self.test_partner.phone, "999-888-7777")

    def test_error_in_action_marks_line_error(self):
        """An exception in a server action marks the line as 'error' and propagates."""
        automation = self.Automation.create({
            "name": "Failing Workflow",
            "model_id": self.model_partner.id,
            "trigger": "on_hand",
        })
        action = self.Action.create({
            "name": "Failing Action",
            "model_id": self.model_partner.id,
            "state": "code",
            "code": "raise Exception('deliberate test error')",
            "base_automation_id": automation.id,
            "usage": "base_automation",
        })

        runtime = self.Runtime.create({
            "automation_id": automation.id,
            "res_model": "res.partner",
            "res_id": self.test_partner.id,
        })
        runtime.action_start()

        line = runtime.line_ids.filtered(lambda l: l.action_id == action)

        # NOTE: do NOT use assertRaises here — Odoo's assertRaises wraps the block
        # in a db savepoint that rolls back on catch, reverting deferred ORM writes
        # (including action_mark_error's write to state='error').
        exc_raised = False
        try:
            line.action_execute()
        except Exception:
            exc_raised = True
        self.assertTrue(exc_raised, "Expected action_execute to raise on failing code")

        self.assertEqual(line.state, "error")
        self.assertIn("deliberate test error", line.error_message)
