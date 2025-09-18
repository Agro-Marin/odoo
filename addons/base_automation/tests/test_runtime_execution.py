# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for base.automation.runtime workflow execution."""

import logging

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TestRuntimeExecution(TransactionCase):
    """Test runtime-based workflow execution with context."""

    @classmethod
    def setUpClass(cls):
        """Set up test data that will be reused across test methods."""
        super().setUpClass()

        cls.Runtime = cls.env["base.automation.runtime"]
        cls.RuntimeLine = cls.env["base.automation.runtime.line"]
        cls.Automation = cls.env["base.automation"]
        cls.Action = cls.env["ir.actions.server"]
        cls.Partner = cls.env["res.partner"]

        # Get base.automation model (runtime workflows use this as model)
        cls.model_automation = cls.env["ir.model"]._get("base.automation")

        # Create test partner
        cls.test_partner = cls.Partner.create(
            {
                "name": "Test Partner for Runtime",
                "email": "test@runtime.com",
            }
        )

        # Create test automation for runtime workflows
        cls.automation = cls.Automation.create(
            {
                "name": "Test Runtime Workflow",
                "model_id": cls.model_automation.id,
                "trigger": "on_hand",
                "use_workflow_dag": True,
                "auto_execute_workflow": False,
            }
        )

    def _create_runtime_action(self, name, code="pass", predecessors=None):
        """Helper to create a server action for runtime workflow.

        Args:
            name: Action name
            code: Python code to execute
            predecessors: List of action records that must complete first

        Returns:
            ir.actions.server record
        """
        vals = {
            "name": name,
            "model_id": self.model_automation.id,
            "state": "code",
            "code": code,
            "base_automation_id": self.automation.id,
            "usage": "base_automation",
        }

        if predecessors:
            vals["predecessor_ids"] = [(6, 0, [p.id for p in predecessors])]

        return self.Action.create(vals)

    # =========================================================================
    # Test Runtime Lifecycle
    # =========================================================================

    def test_runtime_creation(self):
        """Test creating a runtime instance."""
        _logger.info("Testing runtime creation")

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1500.00,
                "date": "2025-10-20",
                "reference": "TEST-001",
            }
        )

        self.assertEqual(runtime.state, "draft")
        self.assertEqual(runtime.partner_id, self.test_partner)
        self.assertEqual(runtime.amount, 1500.00)
        self.assertNotEqual(runtime.name, "New")  # Should have sequence
        self.assertEqual(runtime.progress, 0)

    def test_runtime_start_creates_lines(self):
        """Test that starting runtime creates action lines."""
        _logger.info("Testing runtime start creates lines")

        # Create actions
        action_a = self._create_runtime_action("Action A")
        action_b = self._create_runtime_action("Action B", predecessors=[action_a])
        action_c = self._create_runtime_action("Action C", predecessors=[action_b])

        # Create runtime
        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        # Start workflow
        runtime.action_start()

        # Check state
        self.assertEqual(runtime.state, "in_progress")

        # Check lines created
        self.assertEqual(len(runtime.line_ids), 3)

        # Check sequential DAG structure
        line_a = runtime.line_ids.filtered(lambda l: l.action_id == action_a)
        line_b = runtime.line_ids.filtered(lambda l: l.action_id == action_b)
        line_c = runtime.line_ids.filtered(lambda l: l.action_id == action_c)

        self.assertEqual(line_a.state, "ready")
        self.assertEqual(line_b.state, "waiting")
        self.assertEqual(line_c.state, "waiting")

        self.assertFalse(line_a.predecessor_ids)
        self.assertEqual(line_b.predecessor_ids, line_a)
        self.assertEqual(line_c.predecessor_ids, line_b)

    def test_runtime_without_partner_fails(self):
        """Test that runtime requires a partner."""
        _logger.info("Testing runtime partner requirement")

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": False,  # No partner
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        with self.assertRaises(UserError, msg="Should require partner"):
            runtime.action_start()

    def test_runtime_without_actions_fails(self):
        """Test that runtime requires automation to have actions."""
        _logger.info("Testing runtime action requirement")

        # Create automation with no actions
        empty_automation = self.Automation.create(
            {
                "name": "Empty Automation",
                "model_id": self.model_automation.id,
                "trigger": "on_hand",
                "use_workflow_dag": True,
            }
        )

        runtime = self.Runtime.create(
            {
                "automation_id": empty_automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        with self.assertRaises(UserError, msg="Should fail with no actions"):
            runtime.action_start()

    # =========================================================================
    # Test Runtime Progress Tracking
    # =========================================================================

    def test_progress_calculation(self):
        """Test that progress percentage is calculated correctly."""
        _logger.info("Testing progress calculation")

        # Create 3 actions
        action_a = self._create_runtime_action("A")
        action_b = self._create_runtime_action("B", predecessors=[action_a])
        action_c = self._create_runtime_action("C", predecessors=[action_b])

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        runtime.action_start()

        # Initial progress
        self.assertEqual(runtime.progress, 0)
        self.assertEqual(runtime.progress_display, "0/3 steps")

        # Complete first action
        line_a = runtime.line_ids.filtered(lambda l: l.action_id == action_a)
        line_a.action_mark_done()

        # Progress should be 33%
        self.assertEqual(runtime.progress, 33)
        self.assertEqual(runtime.progress_display, "1/3 steps")

        # Complete second action
        line_b = runtime.line_ids.filtered(lambda l: l.action_id == action_b)
        line_b.action_mark_done()

        # Progress should be 67%
        self.assertEqual(runtime.progress, 67)
        self.assertEqual(runtime.progress_display, "2/3 steps")

        # Complete third action
        line_c = runtime.line_ids.filtered(lambda l: l.action_id == action_c)
        line_c.action_mark_done()

        # Progress should be 100% and state = done
        self.assertEqual(runtime.progress, 100)
        self.assertEqual(runtime.progress_display, "3/3 steps")
        self.assertEqual(runtime.state, "done")

    def test_runtime_auto_completes(self):
        """Test that runtime auto-marks as done when all lines complete."""
        _logger.info("Testing runtime auto-completion")

        action = self._create_runtime_action("Single Action")

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        runtime.action_start()

        # Complete the line
        runtime.line_ids.action_mark_done()

        # Runtime should auto-complete
        self.assertEqual(runtime.state, "done")

    # =========================================================================
    # Test Runtime Action Execution
    # =========================================================================

    def test_runtime_next_step_execution(self):
        """Test executing next step in runtime."""
        _logger.info("Testing runtime next step execution")

        # Create action that logs execution
        execution_log = []
        action = self._create_runtime_action(
            "Log Action",
            code="execution_log.append('executed')",
        )

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        runtime.action_start()

        # Execute next step
        result = runtime.with_context(execution_log=execution_log).action_next_step()

        # Line should be done
        self.assertEqual(runtime.line_ids.state, "done")
        self.assertEqual(runtime.state, "done")

    def test_runtime_next_step_with_no_ready_actions(self):
        """Test next_step when no actions are ready."""
        _logger.info("Testing next_step with no ready actions")

        action_a = self._create_runtime_action("A")
        action_b = self._create_runtime_action("B", predecessors=[action_a])

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        runtime.action_start()

        # Mark first line as waiting (manually to simulate dependency block)
        runtime.line_ids[0].write({"state": "waiting"})

        # Try to execute next
        with self.assertRaises(UserError, msg="Should fail when no actions ready"):
            runtime.action_next_step()

    def test_runtime_not_in_progress_fails(self):
        """Test that next_step requires runtime to be in_progress."""
        _logger.info("Testing next_step state requirement")

        action = self._create_runtime_action("Action")

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        # Don't start - state is draft
        with self.assertRaises(UserError, msg="Should require in_progress state"):
            runtime.action_next_step()

    # =========================================================================
    # Test Runtime Cancellation
    # =========================================================================

    def test_runtime_cancel(self):
        """Test cancelling a runtime workflow."""
        _logger.info("Testing runtime cancellation")

        action_a = self._create_runtime_action("A")
        action_b = self._create_runtime_action("B", predecessors=[action_a])

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        runtime.action_start()

        # Cancel runtime
        runtime.action_cancel()

        # Check state
        self.assertEqual(runtime.state, "cancel")

        # Check all lines cancelled
        for line in runtime.line_ids:
            self.assertEqual(line.state, "cancel")

    def test_runtime_cancel_idempotent(self):
        """Test that cancelling already done/cancelled runtime is safe."""
        _logger.info("Testing cancel idempotency")

        action = self._create_runtime_action("Action")

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        runtime.action_start()
        runtime.line_ids.action_mark_done()

        # Runtime is done
        self.assertEqual(runtime.state, "done")

        # Cancel should be no-op
        runtime.action_cancel()
        self.assertEqual(runtime.state, "done")  # Stays done

    # =========================================================================
    # Test Context Propagation
    # =========================================================================

    def test_execution_context_passed_to_actions(self):
        """Test that runtime context is passed to action execution."""
        _logger.info("Testing context propagation")

        # Create action that uses runtime context
        action = self._create_runtime_action(
            "Context Action",
            code="""
# Access runtime context
partner_id = env.context.get('default_partner_id')
amount = env.context.get('default_amount')
date = env.context.get('default_date')

# Verify context exists
if not partner_id or not amount:
    raise Exception('Context not propagated')
""",
        )

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 2500.00,
                "date": "2025-10-20",
                "reference": "CTX-TEST",
            }
        )

        runtime.action_start()

        # Execute - should not raise exception if context is present
        runtime.action_next_step()

        # Should complete successfully
        self.assertEqual(runtime.state, "done")

    def test_multicompany_context(self):
        """Test multi-company context propagation."""
        _logger.info("Testing multi-company context")

        # Get current company
        current_company = self.env.company

        # Create action that checks multicompany
        action = self._create_runtime_action(
            "Multicompany Action",
            code="""
target_company_id = env.context.get('target_company_id')
if not target_company_id:
    raise Exception('Multicompany context missing')
""",
        )

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
                "multicompany_id": current_company.id,
            }
        )

        runtime.action_start()
        runtime.action_next_step()

        # Should complete successfully
        self.assertEqual(runtime.state, "done")

    # =========================================================================
    # Test Runtime Line Behavior
    # =========================================================================

    def test_runtime_line_dag_resolution(self):
        """Test that runtime lines resolve DAG correctly."""
        _logger.info("Testing runtime line DAG resolution")

        # Create diamond pattern
        action_a = self._create_runtime_action("A")
        action_b = self._create_runtime_action("B", predecessors=[action_a])
        action_c = self._create_runtime_action("C", predecessors=[action_a])
        action_d = self._create_runtime_action("D", predecessors=[action_b, action_c])

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        runtime.action_start()

        # Get lines
        line_a = runtime.line_ids.filtered(lambda l: l.action_id == action_a)
        line_b = runtime.line_ids.filtered(lambda l: l.action_id == action_b)
        line_c = runtime.line_ids.filtered(lambda l: l.action_id == action_c)
        line_d = runtime.line_ids.filtered(lambda l: l.action_id == action_d)

        # Check initial states
        self.assertEqual(line_a.state, "ready")
        self.assertEqual(line_b.state, "waiting")
        self.assertEqual(line_c.state, "waiting")
        self.assertEqual(line_d.state, "waiting")

        # Complete A
        line_a.action_mark_done()

        # B and C should be ready
        self.assertEqual(line_b.state, "ready")
        self.assertEqual(line_c.state, "ready")
        self.assertEqual(line_d.state, "waiting")

        # Complete B
        line_b.action_mark_done()

        # D still waiting for C
        self.assertEqual(line_d.state, "waiting")
        self.assertFalse(line_d.is_ready)

        # Complete C
        line_c.action_mark_done()

        # D now ready
        self.assertEqual(line_d.state, "ready")
        self.assertTrue(line_d.is_ready)

    def test_runtime_line_error_handling(self):
        """Test error handling in runtime line execution."""
        _logger.info("Testing runtime line error handling")

        # Create failing action
        action = self._create_runtime_action(
            "Failing Action",
            code="raise Exception('Test error message')",
        )

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        runtime.action_start()

        # Try to execute - should fail
        with self.assertRaises(Exception):
            runtime.action_next_step()

        # Line should be in error state
        line = runtime.line_ids[0]
        self.assertEqual(line.state, "error")
        self.assertIn("Test error message", line.error_message)

    # =========================================================================
    # Test Multiple Runtimes
    # =========================================================================

    def test_multiple_concurrent_runtimes(self):
        """Test multiple runtime instances can exist simultaneously."""
        _logger.info("Testing multiple concurrent runtimes")

        action = self._create_runtime_action("Action")

        # Create 3 runtimes
        runtime1 = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 1000.00,
                "date": "2025-10-20",
            }
        )

        runtime2 = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 2000.00,
                "date": "2025-10-21",
            }
        )

        runtime3 = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 3000.00,
                "date": "2025-10-22",
            }
        )

        # Start all
        runtime1.action_start()
        runtime2.action_start()
        runtime3.action_start()

        # All should be independent
        self.assertEqual(runtime1.state, "in_progress")
        self.assertEqual(runtime2.state, "in_progress")
        self.assertEqual(runtime3.state, "in_progress")

        # Complete runtime1
        runtime1.action_next_step()
        self.assertEqual(runtime1.state, "done")

        # Others should still be in progress
        self.assertEqual(runtime2.state, "in_progress")
        self.assertEqual(runtime3.state, "in_progress")

    # =========================================================================
    # Test Edge Cases
    # =========================================================================

    def test_runtime_with_single_action(self):
        """Test runtime with just one action."""
        _logger.info("Testing single-action runtime")

        action = self._create_runtime_action("Only Action")

        runtime = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 500.00,
                "date": "2025-10-20",
            }
        )

        runtime.action_start()

        self.assertEqual(len(runtime.line_ids), 1)
        self.assertEqual(runtime.line_ids.state, "ready")
        self.assertEqual(runtime.progress, 0)

        # Execute
        runtime.action_next_step()

        # Should complete
        self.assertEqual(runtime.state, "done")
        self.assertEqual(runtime.progress, 100)

    def test_runtime_sequence_generation(self):
        """Test that runtime names use sequence."""
        _logger.info("Testing runtime sequence")

        runtime1 = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 100.00,
                "date": "2025-10-20",
            }
        )

        runtime2 = self.Runtime.create(
            {
                "automation_id": self.automation.id,
                "partner_id": self.test_partner.id,
                "amount": 200.00,
                "date": "2025-10-20",
            }
        )

        # Both should have different sequence numbers
        self.assertNotEqual(runtime1.name, runtime2.name)
        self.assertNotEqual(runtime1.name, "New")
        self.assertNotEqual(runtime2.name, "New")
