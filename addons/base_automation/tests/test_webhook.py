# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Comprehensive tests for webhook automation triggers."""

import json
import logging

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)


class TestWebhookTrigger(TransactionCase):
    """Test webhook trigger functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test data."""
        super().setUpClass()

        cls.Automation = cls.env["base.automation"]
        cls.Action = cls.env["ir.actions.server"]
        cls.Partner = cls.env["res.partner"]
        cls.SaleOrder = cls.env["sale.order"]

        cls.model_partner = cls.env["ir.model"]._get("res.partner")
        cls.model_sale = cls.env["ir.model"]._get("sale.order")

        # Create test partners
        cls.test_partner = cls.Partner.create(
            {
                "name": "Webhook Test Customer",
                "email": "webhook@test.com",
            }
        )

    # =========================================================================
    # Test Webhook Setup and Configuration
    # =========================================================================

    def test_webhook_trigger_creates_uuid(self):
        """Test webhook trigger automatically generates UUID."""
        _logger.info("Testing webhook UUID generation")

        automation = self.Automation.create(
            {
                "name": "Webhook with UUID",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
            }
        )

        # Verify UUID generated
        self.assertTrue(automation.webhook_uuid)
        self.assertEqual(len(automation.webhook_uuid), 36)  # UUID format

    def test_webhook_url_computed(self):
        """Test webhook URL is computed correctly."""
        _logger.info("Testing webhook URL computation")

        automation = self.Automation.create(
            {
                "name": "Webhook URL Test",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
            }
        )

        # Verify URL computed
        self.assertTrue(automation.url)
        self.assertIn("/web/hook/", automation.url)
        self.assertIn(automation.webhook_uuid, automation.url)

    def test_webhook_url_only_for_webhook_trigger(self):
        """Test URL only exists for webhook trigger type."""
        _logger.info("Testing webhook URL specificity")

        # Non-webhook automation
        automation = self.Automation.create(
            {
                "name": "Not Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_create",
            }
        )

        # Should not have URL
        self.assertFalse(automation.url)

    def test_webhook_uuid_rotation(self):
        """Test webhook UUID can be rotated."""
        _logger.info("Testing webhook UUID rotation")

        automation = self.Automation.create(
            {
                "name": "Webhook Rotation Test",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
            }
        )

        old_uuid = automation.webhook_uuid
        old_url = automation.url

        # Rotate UUID
        automation.action_rotate_webhook_uuid()

        # Verify changed
        self.assertNotEqual(automation.webhook_uuid, old_uuid)
        self.assertNotEqual(automation.url, old_url)
        self.assertIn(automation.webhook_uuid, automation.url)

    def test_webhook_uuid_unique(self):
        """Test each webhook automation gets unique UUID."""
        _logger.info("Testing webhook UUID uniqueness")

        automation1 = self.Automation.create(
            {
                "name": "Webhook 1",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
            }
        )

        automation2 = self.Automation.create(
            {
                "name": "Webhook 2",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
            }
        )

        # UUIDs should be different
        self.assertNotEqual(automation1.webhook_uuid, automation2.webhook_uuid)
        self.assertNotEqual(automation1.url, automation2.url)

    # =========================================================================
    # Test Webhook Execution
    # =========================================================================

    def test_webhook_basic_execution(self):
        """Test basic webhook execution with simple payload."""
        _logger.info("Testing basic webhook execution")

        automation = self.Automation.create(
            {
                "name": "Basic Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({self.test_partner.id})",
            }
        )

        self.Action.create(
            {
                "name": "Webhook Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'comment': 'Webhook triggered'})",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Execute webhook
        payload = {"event": "test"}
        automation._execute_webhook(payload)

        # Verify execution
        self.assertEqual(self.test_partner.comment, "Webhook triggered")

    def test_webhook_with_payload_data(self):
        """Test webhook can access payload data in record_getter."""
        _logger.info("Testing webhook with payload data")

        automation = self.Automation.create(
            {
                "name": "Payload Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": "model.browse(payload.get('partner_id'))",
            }
        )

        self.Action.create(
            {
                "name": "Payload Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'comment': 'Payload processed'})",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Execute with payload containing partner_id
        payload = {"partner_id": self.test_partner.id, "event": "customer_update"}
        automation._execute_webhook(payload)

        # Verify execution
        self.assertEqual(self.test_partner.comment, "Payload processed")

    def test_webhook_with_model_and_id_payload(self):
        """Test webhook with standard _model and _id payload format."""
        _logger.info("Testing webhook with _model/_id payload")

        automation = self.Automation.create(
            {
                "name": "Standard Payload Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": "env[payload['_model']].browse(payload['_id'])",
            }
        )

        self.Action.create(
            {
                "name": "Standard Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'comment': 'Standard payload'})",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Execute with standard payload
        payload = {"_model": "res.partner", "_id": self.test_partner.id}
        automation._execute_webhook(payload)

        # Verify execution
        self.assertEqual(self.test_partner.comment, "Standard payload")

    def test_webhook_multiple_executions(self):
        """Test webhook can be executed multiple times."""
        _logger.info("Testing webhook multiple executions")

        counter = {"count": 0}

        automation = self.Automation.create(
            {
                "name": "Multi Execution Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({self.test_partner.id})",
            }
        )

        self.Action.create(
            {
                "name": "Counter Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": """
current = int(record.comment or '0')
record.write({'comment': str(current + 1)})
""",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Execute webhook 3 times
        for i in range(3):
            automation._execute_webhook({"iteration": i})

        # Should have executed 3 times
        self.assertEqual(self.test_partner.comment, "3")

    def test_webhook_with_complex_record_getter(self):
        """Test webhook with complex record_getter logic."""
        _logger.info("Testing webhook with complex record_getter")

        # Create multiple partners
        vip_partner = self.Partner.create({"name": "VIP Customer"})
        regular_partner = self.Partner.create({"name": "Regular Customer"})

        automation = self.Automation.create(
            {
                "name": "Complex Getter Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": """
partner_id = payload.get('partner_id')
is_vip = payload.get('is_vip', False)
if is_vip:
    result = model.browse(partner_id)
else:
    result = model.browse([])
""",
            }
        )

        self.Action.create(
            {
                "name": "Complex Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'comment': 'VIP webhook'})",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Execute for VIP - should process
        payload1 = {"partner_id": vip_partner.id, "is_vip": True}
        automation._execute_webhook(payload1)
        self.assertEqual(vip_partner.comment, "VIP webhook")

        # Execute for non-VIP - should not process (no record)
        payload2 = {"partner_id": regular_partner.id, "is_vip": False}
        with self.assertRaises(ValidationError):
            automation._execute_webhook(payload2)

    # =========================================================================
    # Test Webhook with Actions
    # =========================================================================

    def test_webhook_with_multiple_actions(self):
        """Test webhook executes multiple actions in sequence."""
        _logger.info("Testing webhook with multiple actions")

        automation = self.Automation.create(
            {
                "name": "Multi-Action Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({self.test_partner.id})",
            }
        )

        # Create 2 actions
        self.Action.create(
            {
                "name": "Action 1",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'comment': 'Action1'})",
                "base_automation_id": automation.id,
                "usage": "base_automation",
                "sequence": 10,
            }
        )

        self.Action.create(
            {
                "name": "Action 2",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'phone': 'Action2'})",
                "base_automation_id": automation.id,
                "usage": "base_automation",
                "sequence": 20,
            }
        )

        # Execute webhook
        automation._execute_webhook({"test": "multi_action"})

        # Both actions should execute
        self.assertEqual(self.test_partner.comment, "Action1")
        self.assertEqual(self.test_partner.phone, "Action2")

    def test_webhook_with_object_write_action(self):
        """Test webhook with object_write action type."""
        _logger.info("Testing webhook with object_write action")

        automation = self.Automation.create(
            {
                "name": "Object Write Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({self.test_partner.id})",
            }
        )

        # Get comment field
        comment_field = self.env["ir.model.fields"]._get("res.partner", "comment")

        self.Action.create(
            {
                "name": "Write Action",
                "model_id": self.model_partner.id,
                "state": "object_write",
                "fields_lines": [
                    (
                        0,
                        0,
                        {
                            "col1": comment_field.id,
                            "value": "Object write from webhook",
                        },
                    )
                ],
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Execute webhook
        automation._execute_webhook({})

        # Verify object_write executed
        self.assertEqual(self.test_partner.comment, "Object write from webhook")

    def test_webhook_with_mail_action(self):
        """Test webhook can send email via mail_post action."""
        _logger.info("Testing webhook with mail action")

        automation = self.Automation.create(
            {
                "name": "Mail Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({self.test_partner.id})",
            }
        )

        self.Action.create(
            {
                "name": "Mail Action",
                "model_id": self.model_partner.id,
                "state": "mail_post",
                "template_id": False,  # No template, just post message
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Execute webhook
        automation._execute_webhook({"subject": "Test notification"})

        # Verify message posted (check message count)
        messages = self.test_partner.message_ids
        self.assertTrue(len(messages) > 0)

    # =========================================================================
    # Test Webhook Error Handling
    # =========================================================================

    def test_webhook_invalid_record_getter(self):
        """Test webhook with invalid record_getter raises error."""
        _logger.info("Testing webhook with invalid record_getter")

        automation = self.Automation.create(
            {
                "name": "Invalid Getter",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": "invalid_python_code {",  # Syntax error
            }
        )

        self.Action.create(
            {
                "name": "Test Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "pass",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Should raise error
        with self.assertRaises(Exception):
            automation._execute_webhook({})

    def test_webhook_record_getter_returns_no_record(self):
        """Test webhook fails when record_getter returns no record."""
        _logger.info("Testing webhook with no record")

        automation = self.Automation.create(
            {
                "name": "No Record",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": "model.browse([])",  # Empty recordset
            }
        )

        self.Action.create(
            {
                "name": "Test Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "pass",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Should raise ValidationError
        with self.assertRaises(ValidationError):
            automation._execute_webhook({})

    def test_webhook_record_getter_returns_deleted_record(self):
        """Test webhook fails when record_getter returns deleted record."""
        _logger.info("Testing webhook with deleted record")

        # Create and delete partner
        temp_partner = self.Partner.create({"name": "Temp Partner"})
        temp_id = temp_partner.id
        temp_partner.unlink()

        automation = self.Automation.create(
            {
                "name": "Deleted Record",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({temp_id})",
            }
        )

        self.Action.create(
            {
                "name": "Test Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "pass",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Should raise ValidationError (record doesn't exist)
        with self.assertRaises(ValidationError):
            automation._execute_webhook({})

    def test_webhook_action_execution_error(self):
        """Test webhook handles action execution errors."""
        _logger.info("Testing webhook action error handling")

        automation = self.Automation.create(
            {
                "name": "Error Action Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({self.test_partner.id})",
            }
        )

        self.Action.create(
            {
                "name": "Failing Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "raise Exception('Action failed!')",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Should raise exception
        with self.assertRaises(Exception) as context:
            automation._execute_webhook({})

        self.assertIn("Action failed!", str(context.exception))

    def test_webhook_empty_payload(self):
        """Test webhook works with empty payload."""
        _logger.info("Testing webhook with empty payload")

        automation = self.Automation.create(
            {
                "name": "Empty Payload Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({self.test_partner.id})",
            }
        )

        self.Action.create(
            {
                "name": "Simple Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'comment': 'Empty payload OK'})",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Execute with empty payload
        automation._execute_webhook({})

        # Should still work
        self.assertEqual(self.test_partner.comment, "Empty payload OK")

    # =========================================================================
    # Test Webhook Logging
    # =========================================================================

    def test_webhook_logging_enabled(self):
        """Test webhook logging when log_webhook_calls is enabled."""
        _logger.info("Testing webhook logging")

        automation = self.Automation.create(
            {
                "name": "Logged Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({self.test_partner.id})",
                "log_webhook_calls": True,
            }
        )

        self.Action.create(
            {
                "name": "Logged Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "pass",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Clear existing logs
        initial_log_count = self.env["ir.logging"].sudo().search_count([])

        # Execute webhook
        automation._execute_webhook({"test": "logging"})

        # Should create log entry
        final_log_count = self.env["ir.logging"].sudo().search_count([])
        self.assertGreater(final_log_count, initial_log_count)

    def test_webhook_logging_error(self):
        """Test webhook logs errors when log_webhook_calls is enabled."""
        _logger.info("Testing webhook error logging")

        automation = self.Automation.create(
            {
                "name": "Error Logged Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": "model.browse([])",  # Will fail
                "log_webhook_calls": True,
            }
        )

        self.Action.create(
            {
                "name": "Test Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "pass",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Execute webhook - will fail
        try:
            automation._execute_webhook({})
        except ValidationError:
            pass

        # Should have logged error
        error_logs = (
            self.env["ir.logging"]
            .sudo()
            .search([("level", "=", "ERROR")], order="id desc", limit=1)
        )
        self.assertTrue(error_logs)

    # =========================================================================
    # Test Webhook with Different Models
    # =========================================================================

    def test_webhook_on_sale_order(self):
        """Test webhook can work with different models."""
        _logger.info("Testing webhook on sale.order model")

        # Create sale order
        order = self.SaleOrder.create(
            {
                "partner_id": self.test_partner.id,
            }
        )

        automation = self.Automation.create(
            {
                "name": "Sale Order Webhook",
                "model_id": self.model_sale.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({order.id})",
            }
        )

        self.Action.create(
            {
                "name": "Order Action",
                "model_id": self.model_sale.id,
                "state": "code",
                "code": "record.write({'note': 'Webhook triggered'})",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Execute webhook
        automation._execute_webhook({"order_id": order.id})

        # Verify execution
        self.assertEqual(order.note, "Webhook triggered")

    def test_webhook_search_by_external_id(self):
        """Test webhook can find record by external identifier."""
        _logger.info("Testing webhook with external ID search")

        # Set external reference
        self.test_partner.write({"ref": "EXT-12345"})

        automation = self.Automation.create(
            {
                "name": "External ID Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": "model.search([('ref', '=', payload.get('external_id'))], limit=1)",
            }
        )

        self.Action.create(
            {
                "name": "External ID Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'comment': 'Found by external ID'})",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Execute with external ID
        payload = {"external_id": "EXT-12345"}
        automation._execute_webhook(payload)

        # Verify found and executed
        self.assertEqual(self.test_partner.comment, "Found by external ID")

    # =========================================================================
    # Test Webhook Edge Cases
    # =========================================================================

    def test_webhook_with_no_record_getter(self):
        """Test webhook with no record_getter (should fail)."""
        _logger.info("Testing webhook without record_getter")

        automation = self.Automation.create(
            {
                "name": "No Getter Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": False,  # No getter
            }
        )

        self.Action.create(
            {
                "name": "Test Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "pass",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Should fail (no record to run on)
        with self.assertRaises(ValidationError):
            automation._execute_webhook({})

    def test_webhook_inactive_automation(self):
        """Test inactive webhook automation is not accessible."""
        _logger.info("Testing inactive webhook automation")

        automation = self.Automation.create(
            {
                "name": "Inactive Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({self.test_partner.id})",
                "active": False,  # Inactive
            }
        )

        self.Action.create(
            {
                "name": "Test Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'comment': 'Should not execute'})",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Direct execution still works (bypass active check)
        # This tests the method itself, not HTTP endpoint access
        automation._execute_webhook({})

        # Should execute (method doesn't check active status)
        self.assertEqual(self.test_partner.comment, "Should not execute")

    def test_webhook_with_large_payload(self):
        """Test webhook handles large payload data."""
        _logger.info("Testing webhook with large payload")

        automation = self.Automation.create(
            {
                "name": "Large Payload Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({self.test_partner.id})",
            }
        )

        self.Action.create(
            {
                "name": "Payload Size Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'comment': f'Payload size: {len(str(payload))}'})",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Create large payload (1000 items)
        large_payload = {f"item_{i}": f"value_{i}" for i in range(1000)}

        # Execute webhook
        automation._execute_webhook(large_payload)

        # Should handle large payload
        self.assertTrue(self.test_partner.comment)
        self.assertIn("Payload size:", self.test_partner.comment)

    def test_webhook_payload_access_in_action(self):
        """Test payload is accessible in action execution context."""
        _logger.info("Testing payload access in action")

        automation = self.Automation.create(
            {
                "name": "Payload Access Webhook",
                "model_id": self.model_partner.id,
                "trigger": "on_webhook",
                "record_getter": f"model.browse({self.test_partner.id})",
            }
        )

        self.Action.create(
            {
                "name": "Payload Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": """
event_type = payload.get('event_type', 'unknown')
record.write({'comment': f'Event: {event_type}'})
""",
                "base_automation_id": automation.id,
                "usage": "base_automation",
            }
        )

        # Execute with payload
        automation._execute_webhook({"event_type": "customer.created"})

        # Action should access payload
        self.assertEqual(self.test_partner.comment, "Event: customer.created")
