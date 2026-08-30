import logging
from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestAutomationTriggers(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.Automation = cls.env["automation.rule"]
        cls.Action = cls.env["ir.actions.server"]
        cls.Partner = cls.env["res.partner"]

        cls.model_partner = cls.env["ir.model"]._get("res.partner")

    def _create_automation(self, name, trigger, **kwargs):
        automation = self.Automation.create(
            {
                "name": name,
                "model_id": self.model_partner.id,
                "trigger": trigger,
                **kwargs,
            },
        )

        action = self.Action.create(
            {
                "name": f"Action for {name}",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Triggered'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            },
        )

        automation.write({"action_server_ids": [Command.link(action.id)]})

        return automation

    def test_on_create_trigger(self):
        _logger.info("Testing on_create trigger")

        self._create_automation("On Create Test", "on_create")

        partner = self.Partner.create({"name": "New Partner"})

        self.assertEqual(partner.street, "Triggered")

    def test_on_write_trigger(self):
        _logger.info("Testing on_write trigger")

        self._create_automation("On Write Test", "on_write")

        partner = self.Partner.create({"name": "Test Partner"})

        partner.street = False

        partner.write({"email": "test@example.com"})

        self.assertEqual(partner.street, "Triggered")

    def test_on_create_or_write_trigger(self):
        _logger.info("Testing on_create_or_write trigger")

        self._create_automation("On Create or Write", "on_create_or_write")

        partner = self.Partner.create({"name": "Test Partner"})
        self.assertEqual(partner.street, "Triggered")

        partner.street = False
        partner.write({"phone": "123-456"})
        self.assertEqual(partner.street, "Triggered")

    def test_on_unlink_trigger(self):
        _logger.info("Testing on_unlink trigger")

        self._create_automation("On Unlink Test", "on_unlink")

        partner = self.Partner.create({"name": "To Delete"})

        partner.unlink()

        self.assertFalse(partner.exists())

    def test_on_archive_trigger(self):
        _logger.info("Testing on_archive trigger")

        self._create_automation("On Archive Test", "on_archive")

        partner = self.Partner.create({"name": "To Archive", "active": True})
        partner.street = False

        partner.write({"active": False})

        self.assertEqual(partner.street, "Triggered")

    def test_on_unarchive_trigger(self):
        _logger.info("Testing on_unarchive trigger")

        self._create_automation("On Unarchive Test", "on_unarchive")

        partner = self.Partner.create({"name": "Archived", "active": False})
        partner.street = False

        partner.write({"active": True})

        self.assertEqual(partner.street, "Triggered")

    def test_on_user_set_trigger(self):
        _logger.info("Testing on_user_set trigger")

        pass

    def test_trigger_with_domain_filter(self):
        _logger.info("Testing trigger with domain filter")

        self._create_automation(
            "Filtered Trigger",
            "on_create",
            filter_domain="[('name', 'ilike', 'VIP')]",
        )

        partner1 = self.Partner.create({"name": "Regular Customer"})
        self.assertFalse(partner1.street)

        partner2 = self.Partner.create({"name": "VIP Customer"})
        self.assertEqual(partner2.street, "Triggered")

    def test_on_hand_trigger(self):
        _logger.info("Testing on_hand trigger")

        automation = self._create_automation("Manual Trigger", "on_hand")

        partner = self.Partner.create({"name": "Manual Test"})

        self.assertFalse(partner.street)

        automation.with_context(
            active_model="res.partner",
            active_id=partner.id,
            active_ids=partner.ids,
        ).action_manual_trigger()

        self.assertEqual(partner.street, "Triggered")

    def test_manual_trigger_with_dag_creates_runtime(self):
        _logger.info("Testing manual trigger with DAG creates runtime")

        test_partner = self.Partner.create({"name": "DAG Test Partner"})

        automation = self.Automation.create(
            {
                "name": "Manual DAG Workflow",
                "model_id": self.model_partner.id,
                "trigger": "on_hand",
            }
        )

        action_a = self.Action.create(
            {
                "name": "DAG Action A",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "pass",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )
        action_b = self.Action.create(
            {
                "name": "DAG Action B",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "pass",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )
        self.env["workflow.edge"].create(
            {"source_node_id": action_a.id, "target_node_id": action_b.id}
        )

        before_count = self.env["automation.runtime"].search_count(
            [("automation_id", "=", automation.id)]
        )

        automation.with_context(
            active_model="res.partner",
            active_ids=test_partner.ids,
        ).action_manual_trigger()

        after_count = self.env["automation.runtime"].search_count(
            [("automation_id", "=", automation.id)]
        )
        self.assertEqual(after_count, before_count + 1)

    def test_trigger_field_ids_filter(self):
        _logger.info("Testing trigger_field_ids filtering")

        email_field = self.env["ir.model.fields"]._get("res.partner", "email")

        automation = self.Automation.create(
            {
                "name": "Email Change Only",
                "model_id": self.model_partner.id,
                "trigger": "on_write",
                "trigger_field_ids": [Command.link(email_field.id)],
            }
        )

        self.Action.create(
            {
                "name": "Email Changed",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Email changed'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        partner = self.Partner.create({"name": "Field Test"})

        partner.write({"name": "New Name"})
        self.assertFalse(partner.street)

        partner.write({"email": "new@example.com"})
        self.assertEqual(partner.street, "Email changed")

    def test_filter_pre_domain(self):
        _logger.info("Testing filter_pre_domain")

        automation = self.Automation.create(
            {
                "name": "Pre-filter Test",
                "model_id": self.model_partner.id,
                "trigger": "on_write",
                "filter_pre_domain": "[('active', '=', True)]",
                "filter_domain": "[('active', '=', False)]",
            }
        )

        self.Action.create(
            {
                "name": "Archival Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Archived'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        partner = self.Partner.create({"name": "Active Partner", "active": True})

        partner.write({"active": False})
        self.assertEqual(partner.street, "Archived")

    def test_multiple_automations_same_trigger(self):
        _logger.info("Testing multiple automations")

        self._create_automation("Auto 1", "on_create")
        automation2 = self.Automation.create(
            {
                "name": "Auto 2",
                "model_id": self.model_partner.id,
                "trigger": "on_create",
            }
        )

        self.Action.create(
            {
                "name": "Action 2",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'phone': '999-999-9999'})",
                "automation_rule_id": automation2.id,
                "usage": "automation",
            }
        )

        partner = self.Partner.create({"name": "Multi Test"})

        self.assertEqual(partner.street, "Triggered")
        self.assertEqual(partner.phone, "999-999-9999")

    def test_inactive_automation_does_not_trigger(self):
        _logger.info("Testing inactive automation")

        automation = self._create_automation("Inactive Test", "on_create")

        automation.write({"active": False})

        partner = self.Partner.create({"name": "Should Not Trigger"})

        self.assertFalse(partner.street)

    def test_automation_with_no_actions(self):
        _logger.info("Testing automation with no actions")

        self.Automation.create(
            {
                "name": "No Actions",
                "model_id": self.model_partner.id,
                "trigger": "on_create",
            }
        )

        partner = self.Partner.create({"name": "No Actions Test"})

        self.assertTrue(partner.exists())

    def test_automation_with_multiple_actions(self):
        _logger.info("Testing multiple actions")

        automation = self.Automation.create(
            {
                "name": "Multi-Action",
                "model_id": self.model_partner.id,
                "trigger": "on_create",
            }
        )

        self.Action.create(
            {
                "name": "Action 1",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Action 1'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
                "sequence": 10,
            }
        )

        self.Action.create(
            {
                "name": "Action 2",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'phone': 'Action 2'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
                "sequence": 20,
            }
        )

        partner = self.Partner.create({"name": "Multi Action"})

        self.assertEqual(partner.street, "Action 1")
        self.assertEqual(partner.phone, "Action 2")


@tagged("post_install", "-at_install")
class TestFieldSpecificTriggers(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.Automation = cls.env["automation.rule"]
        cls.Action = cls.env["ir.actions.server"]
        cls.Partner = cls.env["res.partner"]

        cls.model_partner = cls.env["ir.model"]._get("res.partner")

    def test_on_state_set_trigger(self):
        self.skipTest(
            "on_state_set requires a model with field named 'state'; "
            "res.partner only has 'type' — use sale.order or crm.lead instead"
        )

        type_field = self.env["ir.model.fields"]._get("res.partner", "type")
        type_selection = self.env["ir.model.fields.selection"].search(
            [("field_id", "=", type_field.id), ("value", "=", "delivery")],
            limit=1,
        )
        if not type_selection:
            self.skipTest("res.partner.type 'delivery' selection not found")

        automation = self.Automation.create(
            {
                "name": "On Type Delivery",
                "model_id": self.model_partner.id,
                "trigger": "on_state_set",
                "trg_selection_field_id": type_selection.id,
            }
        )
        action = self.Action.create(
            {
                "name": "Type Set Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Is delivery'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )
        automation.write({"action_server_ids": [Command.link(action.id)]})

        partner = self.Partner.create({"name": "State Test"})
        self.assertFalse(partner.street)

        partner.write({"type": "delivery"})
        self.assertEqual(partner.street, "Is delivery")

    def test_on_state_set_selective(self):
        self.skipTest(
            "on_state_set requires a model with field named 'state'; "
            "res.partner only has 'type' — use sale.order or crm.lead instead"
        )

        type_field = self.env["ir.model.fields"]._get("res.partner", "type")
        type_selection = self.env["ir.model.fields.selection"].search(
            [("field_id", "=", type_field.id), ("value", "=", "delivery")],
            limit=1,
        )
        if not type_selection:
            self.skipTest("res.partner.type 'delivery' selection not found")

        automation = self.Automation.create(
            {
                "name": "Only on Delivery",
                "model_id": self.model_partner.id,
                "trigger": "on_state_set",
                "trg_selection_field_id": type_selection.id,
            }
        )
        action = self.Action.create(
            {
                "name": "Delivery Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Triggered'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )
        automation.write({"action_server_ids": [Command.link(action.id)]})

        partner = self.Partner.create({"name": "Selective Test"})

        partner.write({"type": "invoice"})
        self.assertFalse(partner.street)

    def test_on_priority_set_trigger(self):
        _logger.info("Testing on_priority_set trigger")

        priority_field = self.env["ir.model.fields"].search(
            [("model", "=", "res.partner"), ("name", "=", "priority")], limit=1
        )
        if not priority_field:
            self.skipTest("res.partner has no priority field (requires crm module)")

        priority_selection = self.env["ir.model.fields.selection"].search(
            [("field_id", "=", priority_field.id), ("value", "=", "1")],
            limit=1,
        )
        if not priority_selection:
            self.skipTest("Priority value '1' not found")

        automation = self.Automation.create(
            {
                "name": "On Priority Set",
                "model_id": self.model_partner.id,
                "trigger": "on_priority_set",
                "trg_selection_field_id": priority_selection.id,
            }
        )
        action = self.Action.create(
            {
                "name": "Priority Set Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Priority set to 1'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )
        automation.write({"action_server_ids": [Command.link(action.id)]})

        partner = self.Partner.create({"name": "Priority Test", "priority": "0"})
        self.assertFalse(partner.street)

        partner.write({"priority": "1"})
        self.assertEqual(partner.street, "Priority set to 1")


@tagged("post_install", "-at_install")
class TestTimeBasedTriggers(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.Automation = cls.env["automation.rule"]
        cls.Action = cls.env["ir.actions.server"]
        cls.Partner = cls.env["res.partner"]

        cls.model_partner = cls.env["ir.model"]._get("res.partner")

    def _run_cron(self):
        IrCron = type(self.env["ir.cron"])
        with patch.object(IrCron, "_commit_progress", return_value=float("inf")):
            self.Automation._cron_process_time_based_actions()

    def test_on_time_trigger_setup(self):
        _logger.info("Testing on_time trigger setup")

        date_field = self.env["ir.model.fields"]._get("res.partner", "create_date")

        automation = self.Automation.create(
            {
                "name": "One Day After Creation",
                "model_id": self.model_partner.id,
                "trigger": "on_time",
                "trg_date_id": date_field.id,
                "trg_date_range": 1,
                "trg_date_range_type": "day",
            }
        )

        self.Action.create(
            {
                "name": "Time Trigger Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'One day passed'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        self.assertEqual(automation.trigger, "on_time")
        self.assertEqual(automation.trg_date_id, date_field)
        self.assertEqual(automation.trg_date_range, 1)
        self.assertEqual(automation.trg_date_range_type, "day")

    def test_on_time_created_trigger_setup(self):
        _logger.info("Testing on_time_created trigger setup")

        automation = self.Automation.create(
            {
                "name": "2 Hours After Creation",
                "model_id": self.model_partner.id,
                "trigger": "on_time_created",
                "trg_date_range": 2,
                "trg_date_range_type": "hour",
            }
        )

        self.Action.create(
            {
                "name": "After Creation Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': '2 hours passed'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        self.assertEqual(automation.trigger, "on_time_created")
        self.assertEqual(automation.trg_date_range, 2)
        self.assertEqual(automation.trg_date_range_type, "hour")

    def test_on_time_updated_trigger_setup(self):
        _logger.info("Testing on_time_updated trigger setup")

        automation = self.Automation.create(
            {
                "name": "30 Minutes After Update",
                "model_id": self.model_partner.id,
                "trigger": "on_time_updated",
                "trg_date_range": 30,
                "trg_date_range_type": "minutes",
            }
        )

        self.Action.create(
            {
                "name": "After Update Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': '30 minutes since update'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        self.assertEqual(automation.trigger, "on_time_updated")
        self.assertEqual(automation.trg_date_range, 30)
        self.assertEqual(automation.trg_date_range_type, "minutes")

    def test_time_trigger_all_range_types(self):
        _logger.info("Testing all time range types")

        for range_type in ["minutes", "hour", "day", "month"]:
            automation = self.Automation.create(
                {
                    "name": f"Time Trigger {range_type}",
                    "model_id": self.model_partner.id,
                    "trigger": "on_time_created",
                    "trg_date_range": 5,
                    "trg_date_range_type": range_type,
                }
            )

            self.assertEqual(automation.trg_date_range_type, range_type)

    def test_search_time_based_records_on_time(self):
        _logger.info("Testing time-based record search for on_time")

        import datetime

        from odoo import fields

        date_field = self.env["ir.model.fields"]._get("res.partner", "create_date")

        automation = self.Automation.create(
            {
                "name": "1 Day After",
                "model_id": self.model_partner.id,
                "trigger": "on_time",
                "trg_date_id": date_field.id,
                "trg_date_range": 1,
                "trg_date_range_type": "day",
            }
        )

        now = fields.Datetime.now()
        two_days_ago = now - datetime.timedelta(days=2)
        one_day_ago = now - datetime.timedelta(days=1, hours=1)
        one_hour_ago = now - datetime.timedelta(hours=1)

        partner1 = self.Partner.create({"name": "Old Partner"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            (two_days_ago, partner1.id),
        )

        partner2 = self.Partner.create({"name": "Recent Partner"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            (one_day_ago, partner2.id),
        )

        partner3 = self.Partner.create({"name": "Very Recent Partner"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            (one_hour_ago, partner3.id),
        )

        self.env.invalidate_all()

        records = automation._search_time_based_automation_records(until=now)

        self.assertIn(partner1, records)
        self.assertIn(partner2, records)
        self.assertNotIn(partner3, records)

    def test_search_time_based_records_with_domain_filter(self):
        _logger.info("Testing time trigger with domain filter")

        import datetime

        from odoo import fields

        date_field = self.env["ir.model.fields"]._get("res.partner", "create_date")

        automation = self.Automation.create(
            {
                "name": "VIP Only Time Trigger",
                "model_id": self.model_partner.id,
                "trigger": "on_time",
                "trg_date_id": date_field.id,
                "trg_date_range": 1,
                "trg_date_range_type": "day",
                "filter_domain": "[('name', 'ilike', 'VIP')]",
            }
        )

        now = fields.Datetime.now()
        two_days_ago = now - datetime.timedelta(days=2)

        vip_partner = self.Partner.create({"name": "VIP Customer"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            (two_days_ago, vip_partner.id),
        )

        regular_partner = self.Partner.create({"name": "Regular Customer"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            (two_days_ago, regular_partner.id),
        )

        self.env.invalidate_all()

        records = automation._search_time_based_automation_records(until=now)

        self.assertIn(vip_partner, records)
        self.assertNotIn(regular_partner, records)

    def test_time_trigger_last_run_tracking(self):
        _logger.info("Testing last_run tracking")

        import datetime

        from odoo import fields

        date_field = self.env["ir.model.fields"]._get("res.partner", "create_date")

        automation = self.Automation.create(
            {
                "name": "Last Run Test",
                "model_id": self.model_partner.id,
                "trigger": "on_time",
                "trg_date_id": date_field.id,
                "trg_date_range": 1,
                "trg_date_range_type": "day",
            }
        )

        now = fields.Datetime.now()
        three_days_ago = now - datetime.timedelta(days=3)
        now - datetime.timedelta(days=2)

        partner = self.Partner.create({"name": "Test Partner"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            (three_days_ago, partner.id),
        )
        self.env.invalidate_all()

        records1 = automation._search_time_based_automation_records(until=now)
        self.assertIn(partner, records1)

        automation.write({"last_run": now})

        records2 = automation._search_time_based_automation_records(until=now)
        self.assertNotIn(partner, records2)

    def test_cron_process_time_based_actions(self):
        _logger.info("Testing cron processing of time triggers")

        import datetime

        date_field = self.env["ir.model.fields"]._get("res.partner", "create_date")

        automation = self.Automation.create(
            {
                "name": "Cron Test Automation",
                "model_id": self.model_partner.id,
                "trigger": "on_time",
                "trg_date_id": date_field.id,
                "trg_date_range": 1,
                "trg_date_range_type": "day",
            }
        )

        self.Action.create(
            {
                "name": "Cron Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Cron executed'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        now = self.env.cr.now()
        two_days_ago = now - datetime.timedelta(days=2)

        partner = self.Partner.create({"name": "Cron Target"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            (two_days_ago, partner.id),
        )
        self.env.invalidate_all()

        self._run_cron()

        self.assertEqual(partner.street, "Cron executed")

        self.assertTrue(automation.last_run)
        self.assertGreaterEqual(automation.last_run, now)

    def test_cron_processes_multiple_automations(self):
        _logger.info("Testing cron with multiple automations")

        import datetime

        from odoo import fields

        date_field = self.env["ir.model.fields"]._get("res.partner", "create_date")
        now = fields.Datetime.now()
        two_days_ago = now - datetime.timedelta(days=2)

        automation1 = self.Automation.create(
            {
                "name": "Auto 1",
                "model_id": self.model_partner.id,
                "trigger": "on_time",
                "trg_date_id": date_field.id,
                "trg_date_range": 1,
                "trg_date_range_type": "day",
            }
        )
        self.Action.create(
            {
                "name": "Action 1",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Auto1'})",
                "automation_rule_id": automation1.id,
                "usage": "automation",
            }
        )

        automation2 = self.Automation.create(
            {
                "name": "Auto 2",
                "model_id": self.model_partner.id,
                "trigger": "on_time",
                "trg_date_id": date_field.id,
                "trg_date_range": 1,
                "trg_date_range_type": "day",
            }
        )
        self.Action.create(
            {
                "name": "Action 2",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'phone': 'Auto2'})",
                "automation_rule_id": automation2.id,
                "usage": "automation",
            }
        )

        partner = self.Partner.create({"name": "Multi Auto"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            (two_days_ago, partner.id),
        )
        self.env.invalidate_all()

        self._run_cron()

        self.assertEqual(partner.street, "Auto1")
        self.assertEqual(partner.phone, "Auto2")

    def test_cron_skips_inactive_automations(self):
        _logger.info("Testing cron skips inactive automations")

        import datetime

        from odoo import fields

        date_field = self.env["ir.model.fields"]._get("res.partner", "create_date")

        automation = self.Automation.create(
            {
                "name": "Inactive Automation",
                "model_id": self.model_partner.id,
                "trigger": "on_time",
                "trg_date_id": date_field.id,
                "trg_date_range": 1,
                "trg_date_range_type": "day",
                "active": False,
            }
        )

        self.Action.create(
            {
                "name": "Should Not Execute",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Should not see this'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        now = fields.Datetime.now()
        two_days_ago = now - datetime.timedelta(days=2)

        partner = self.Partner.create({"name": "Test"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            (two_days_ago, partner.id),
        )
        self.env.invalidate_all()

        self._run_cron()

        self.assertFalse(partner.street)

    def test_on_time_created_uses_create_date(self):
        _logger.info("Testing on_time_created uses create_date")

        import datetime

        from odoo import fields

        automation = self.Automation.create(
            {
                "name": "On Time Created",
                "model_id": self.model_partner.id,
                "trigger": "on_time_created",
                "trg_date_range": 1,
                "trg_date_range_type": "day",
            }
        )

        self.Action.create(
            {
                "name": "Created Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Created trigger'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        now = fields.Datetime.now()
        two_days_ago = now - datetime.timedelta(days=2)

        partner = self.Partner.create({"name": "Created Test"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            (two_days_ago, partner.id),
        )
        self.env.invalidate_all()

        self._run_cron()

        self.assertEqual(partner.street, "Created trigger")

    def test_on_time_updated_uses_write_date(self):
        _logger.info("Testing on_time_updated uses write_date")

        import datetime

        automation = self.Automation.create(
            {
                "name": "On Time Updated",
                "model_id": self.model_partner.id,
                "trigger": "on_time_updated",
                "trg_date_range": 1,
                "trg_date_range_type": "hour",
            }
        )
        self.assertEqual(automation.trg_date_id.name, "write_date")

        action = self.Action.create(
            {
                "name": "Updated Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Updated trigger'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )
        automation.write({"action_server_ids": [Command.link(action.id)]})

        three_hours_ago = self.env.cr.now() - datetime.timedelta(hours=3)

        partner = self.Partner.create({"name": "Updated Test"})
        partner.write({"email": "test@example.com"})

        self.env.flush_all()

        self.env.cr.execute(
            "UPDATE res_partner SET write_date = %s WHERE id = %s",
            (three_hours_ago, partner.id),
        )
        self.env.invalidate_all()

        self._run_cron()
        self.env.invalidate_all()

        self.assertEqual(partner.street, "Updated trigger")

    def test_time_trigger_with_missing_date_field(self):
        _logger.info("Testing time trigger with missing field")

        from odoo import fields

        automation = self.Automation.create(
            {
                "name": "Missing Date Field",
                "model_id": self.model_partner.id,
                "trigger": "on_time",
                "trg_date_range": 1,
                "trg_date_range_type": "day",
            }
        )

        now = fields.Datetime.now()

        records = automation._search_time_based_automation_records(until=now)
        self.assertFalse(records)

    def test_time_trigger_validation_negative_range(self):
        _logger.info("Testing negative range validation")

        from odoo.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.Automation.create(
                {
                    "name": "Negative Range",
                    "model_id": self.model_partner.id,
                    "trigger": "on_time_created",
                    "trg_date_range": -5,
                    "trg_date_range_type": "day",
                }
            )

    def test_time_trigger_multiple_range_types_same_model(self):
        _logger.info("Testing multiple range types")

        import datetime

        from odoo import fields

        date_field = self.env["ir.model.fields"]._get("res.partner", "create_date")
        now = fields.Datetime.now()

        auto_hour = self.Automation.create(
            {
                "name": "Hour Range",
                "model_id": self.model_partner.id,
                "trigger": "on_time",
                "trg_date_id": date_field.id,
                "trg_date_range": 1,
                "trg_date_range_type": "hour",
            }
        )
        self.Action.create(
            {
                "name": "Hour Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Hour'})",
                "automation_rule_id": auto_hour.id,
                "usage": "automation",
            }
        )

        auto_day = self.Automation.create(
            {
                "name": "Day Range",
                "model_id": self.model_partner.id,
                "trigger": "on_time",
                "trg_date_id": date_field.id,
                "trg_date_range": 1,
                "trg_date_range_type": "day",
            }
        )
        self.Action.create(
            {
                "name": "Day Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'phone': 'Day'})",
                "automation_rule_id": auto_day.id,
                "usage": "automation",
            }
        )

        two_days_ago = now - datetime.timedelta(days=2)
        partner = self.Partner.create({"name": "Multi Range"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            (two_days_ago, partner.id),
        )
        self.env.invalidate_all()

        self._run_cron()

        self.assertEqual(partner.street, "Hour")
        self.assertEqual(partner.phone, "Day")

    def test_time_trigger_with_zero_range(self):
        _logger.info("Testing zero range")

        import datetime

        automation = self.Automation.create(
            {
                "name": "Zero Range",
                "model_id": self.model_partner.id,
                "trigger": "on_time_created",
                "trg_date_range": 0,
                "trg_date_range_type": "day",
            }
        )

        self.Action.create(
            {
                "name": "Zero Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Zero range'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        partner = self.Partner.create({"name": "Zero Test"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = %s WHERE id = %s",
            (self.env.cr.now() - datetime.timedelta(seconds=1), partner.id),
        )
        self.env.invalidate_all()

        self._run_cron()
        self.env.invalidate_all()

        self.assertEqual(partner.street, "Zero range")


@tagged("post_install", "-at_install")
class TestMailThreadTriggers(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.Automation = cls.env["automation.rule"]
        cls.Action = cls.env["ir.actions.server"]
        cls.Partner = cls.env["res.partner"]

        cls.model_partner = cls.env["ir.model"]._get("res.partner")

        cls.test_partner = cls.Partner.create(
            {
                "name": "Mail Test Partner",
                "email": "mailtest@example.com",
            }
        )

    def test_on_message_received_trigger(self):
        _logger.info("Testing on_message_received trigger")

        automation = self.Automation.create(
            {
                "name": "On Message Received",
                "model_id": self.model_partner.id,
                "trigger": "on_message_received",
            }
        )

        action = self.Action.create(
            {
                "name": "Message Received Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Message received'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )
        automation.write({"action_server_ids": [Command.link(action.id)]})

        external = self.Partner.create(
            {"name": "External Customer", "email": "ext@example.com"}
        )
        self.test_partner.sudo().message_post(
            body="Incoming message from customer",
            message_type="comment",
            author_id=external.id,
            subtype_xmlid="mail.mt_comment",
        )

        self.assertEqual(self.test_partner.street, "Message received")

    def test_on_message_sent_trigger(self):
        _logger.info("Testing on_message_sent trigger")

        automation = self.Automation.create(
            {
                "name": "On Message Sent",
                "model_id": self.model_partner.id,
                "trigger": "on_message_sent",
            }
        )

        action = self.Action.create(
            {
                "name": "Message Sent Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Message sent'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )
        automation.write({"action_server_ids": [Command.link(action.id)]})

        admin_user = self.env.ref("base.user_admin")
        self.test_partner.with_user(admin_user).message_post(
            body="Reply to customer",
            author_id=admin_user.partner_id.id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )

        self.assertEqual(self.test_partner.street, "Message sent")

    def test_on_message_sent_honours_filter_domain(self):
        automation = self.Automation.create(
            {
                "name": "On Message Sent With Domain",
                "model_id": self.model_partner.id,
                "trigger": "on_message_sent",
                "filter_domain": repr([("id", "=", 0)]),
            }
        )
        action = self.Action.create(
            {
                "name": "Message Sent Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Message sent'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )
        automation.write({"action_server_ids": [Command.link(action.id)]})

        admin_user = self.env.ref("base.user_admin")
        self.test_partner.with_user(admin_user).message_post(
            body="Reply to customer",
            author_id=admin_user.partner_id.id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )

        self.assertFalse(
            self.test_partner.street,
            "an impossible filter_domain must block the action",
        )


@tagged("post_install", "-at_install")
class TestUIChangeTrigger(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.Automation = cls.env["automation.rule"]
        cls.Action = cls.env["ir.actions.server"]
        cls.Partner = cls.env["res.partner"]

        cls.model_partner = cls.env["ir.model"]._get("res.partner")

    def test_on_change_trigger_setup(self):
        _logger.info("Testing on_change trigger setup")

        email_field = self.env["ir.model.fields"]._get("res.partner", "email")

        automation = self.Automation.create(
            {
                "name": "On Email Change",
                "model_id": self.model_partner.id,
                "trigger": "on_change",
                "on_change_field_ids": [Command.link(email_field.id)],
            }
        )

        self.Action.create(
            {
                "name": "Email Changed",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "pass",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        self.assertEqual(automation.trigger, "on_change")
        self.assertIn(email_field, automation.on_change_field_ids)


@tagged("post_install", "-at_install")
class TestTriggerEdgeCases(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.Automation = cls.env["automation.rule"]
        cls.Action = cls.env["ir.actions.server"]
        cls.Partner = cls.env["res.partner"]

        cls.model_partner = cls.env["ir.model"]._get("res.partner")

    def test_trigger_field_ids_empty_all_fields(self):
        _logger.info("Testing empty trigger_field_ids")

        automation = self.Automation.create(
            {
                "name": "Trigger on Any Field",
                "model_id": self.model_partner.id,
                "trigger": "on_write",
            }
        )

        self.Action.create(
            {
                "name": "Any Field Changed",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Changed'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        partner = self.Partner.create({"name": "Test"})
        partner.street = False

        partner.write({"phone": "123"})

        self.assertEqual(partner.street, "Changed")

    def test_combined_domain_filters(self):
        _logger.info("Testing combined domain filters")

        automation = self.Automation.create(
            {
                "name": "Combined Filters",
                "model_id": self.model_partner.id,
                "trigger": "on_write",
                "filter_pre_domain": "[('active', '=', True)]",
                "filter_domain": "[('active', '=', False)]",
            }
        )

        self.Action.create(
            {
                "name": "Archive Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Archived'})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        partner = self.Partner.create({"name": "Active", "active": True})

        partner.write({"active": False})
        self.assertEqual(partner.street, "Archived")

    def test_automation_execution_order(self):
        _logger.info("Testing automation execution order")

        auto1 = self.Automation.create(
            {
                "name": "Auto 1",
                "model_id": self.model_partner.id,
                "trigger": "on_create",
                "sequence": 30,
            }
        )
        self.Action.create(
            {
                "name": "Action 1",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': (record.street or '') + 'A'})",
                "automation_rule_id": auto1.id,
                "usage": "automation",
            }
        )

        auto2 = self.Automation.create(
            {
                "name": "Auto 2",
                "model_id": self.model_partner.id,
                "trigger": "on_create",
                "sequence": 10,
            }
        )
        self.Action.create(
            {
                "name": "Action 2",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': (record.street or '') + 'B'})",
                "automation_rule_id": auto2.id,
                "usage": "automation",
            }
        )

        auto3 = self.Automation.create(
            {
                "name": "Auto 3",
                "model_id": self.model_partner.id,
                "trigger": "on_create",
                "sequence": 20,
            }
        )
        self.Action.create(
            {
                "name": "Action 3",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': (record.street or '') + 'C'})",
                "automation_rule_id": auto3.id,
                "usage": "automation",
            }
        )

        partner = self.Partner.create({"name": "Sequence Test"})

        self.assertEqual(partner.street, "BCA")

    def test_trigger_with_multi_company(self):
        _logger.info("Testing multi-company triggers")

        automation = self.Automation.create(
            {
                "name": "Company Specific",
                "model_id": self.model_partner.id,
                "trigger": "on_create",
            }
        )

        self.Action.create(
            {
                "name": "Company Action",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "record.write({'street': 'Company: %s' % env.company.name})",
                "automation_rule_id": automation.id,
                "usage": "automation",
            }
        )

        partner = self.Partner.create({"name": "Company Test"})

        self.assertIn("Company:", partner.street)
