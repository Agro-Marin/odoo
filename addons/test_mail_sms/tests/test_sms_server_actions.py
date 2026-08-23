# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.sms.tests.common import SMSCommon
from odoo.addons.test_mail_sms.tests.common import TestSMSRecipients


@tagged("ir_actions")
class TestServerAction(SMSCommon, TestSMSRecipients):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_record = (
            cls.env["mail.test.sms"]
            .with_context(**cls._test_context)
            .create(
                {
                    "name": "Test",
                    "customer_id": cls.partner_1.id,
                }
            )
        )
        cls.test_record_2 = (
            cls.env["mail.test.sms"]
            .with_context(**cls._test_context)
            .create(
                {
                    "name": "Test Record 2",
                    "customer_id": False,
                    "phone_nbr": cls.test_numbers[0],
                }
            )
        )

        cls.sms_template = cls._create_sms_template("mail.test.sms")
        cls.action = cls.env["ir.actions.server"].create(
            {
                "name": "Test SMS Action",
                "model_id": cls.env["ir.model"]._get("mail.test.sms").id,
                "state": "sms",
                "sms_method": "sms",
                "sms_template_id": cls.sms_template.id,
                "group_ids": cls.env.ref("base.group_user"),
            }
        )

    def test_action_sms(self):
        context = {
            "active_model": "mail.test.sms",
            "active_ids": (self.test_record | self.test_record_2).ids,
        }

        with self.with_user("employee"), self.mockSMSGateway():
            self.action.with_user(self.env.user).with_context(**context).run()

        self.assertSMSOutgoing(
            self.test_record.customer_id,
            None,
            content="Dear %s this is an SMS." % self.test_record.display_name,
        )
        self.assertSMSOutgoing(
            self.env["res.partner"],
            self.test_numbers_san[0],
            content="Dear %s this is an SMS." % self.test_record_2.display_name,
        )

    def test_action_sms_single(self):
        context = {
            "active_model": "mail.test.sms",
            "active_id": self.test_record.id,
        }

        with self.with_user("employee"), self.mockSMSGateway():
            self.action.with_user(self.env.user).with_context(**context).run()
        self.assertSMSOutgoing(
            self.test_record.customer_id,
            None,
            content="Dear %s this is an SMS." % self.test_record.display_name,
        )

    def test_action_sms_w_log(self):
        self.action.sms_method = "note"
        context = {
            "active_model": "mail.test.sms",
            "active_ids": (self.test_record | self.test_record_2).ids,
        }

        with self.with_user("employee"), self.mockSMSGateway():
            self.action.with_user(self.env.user).with_context(**context).run()

        self.assertSMSOutgoing(
            self.test_record.customer_id,
            None,
            content="Dear %s this is an SMS." % self.test_record.display_name,
        )
        self.assertSMSLogged(
            self.test_record, "Dear %s this is an SMS." % self.test_record.display_name
        )

        self.assertSMSOutgoing(
            self.env["res.partner"],
            self.test_numbers_san[0],
            content="Dear %s this is an SMS." % self.test_record_2.display_name,
        )
        self.assertSMSLogged(
            self.test_record_2,
            "Dear %s this is an SMS." % self.test_record_2.display_name,
        )

    @mute_logger("odoo.addons.sms.models.sms_sms")
    def test_action_sms_w_post(self):
        self.action.sms_method = "comment"
        context = {
            "active_model": "mail.test.sms",
            "active_ids": (self.test_record | self.test_record_2).ids,
        }

        with self.with_user("employee"), self.mockSMSGateway():
            self.action.with_user(self.env.user).with_context(**context).run()

        self.assertSMSNotification(
            [{"partner": self.test_record.customer_id}],
            "Dear %s this is an SMS." % self.test_record.display_name,
            messages=self.test_record.message_ids[-1],
        )
        self.assertSMSNotification(
            [{"partner": self.env["res.partner"], "number": self.test_numbers_san[0]}],
            "Dear %s this is an SMS." % self.test_record_2.display_name,
            messages=self.test_record_2.message_ids[-1],
        )

    def test_the_configured_method_survives_a_write_of_the_state(self):
        """`Note only` reverting to `SMS` starts sending messages for real.

        `_compute_sms_method` assigned its default on every pass, and the ORM
        marks a dependent modified on any write naming a dependency -- a write
        of the same value included. So an export and re-import of the action,
        which is how one is moved between databases and which resends every
        column whether it changed or not, turned an action configured to log a
        note into one that sends the SMS: to the customer, at the usual price.
        """
        self.action.sms_method = "note"
        self.action.write({"state": "sms"})
        self.assertEqual(
            self.action.sms_method,
            "note",
            "a write of the state it already has must not start sending SMS",
        )

        self.env["ir.model.data"]._update_xmlids(
            [
                {
                    "xml_id": "__test__.sms_round_trip",
                    "record": self.action,
                    "noupdate": False,
                },
            ]
        )
        fields = ["id", "name", "model_id/id", "state", "sms_template_id/id"]
        result = self.env["ir.actions.server"].load(
            fields,
            self.action.export_data(fields)["datas"],
        )
        self.assertFalse([m for m in result["messages"] if m.get("type") == "error"])
        self.action.invalidate_recordset()
        self.assertEqual(self.action.sms_method, "note")

    def test_leaving_and_re_entering_sms_seeds_the_method_again(self):
        """Preserving is not the same as never seeding."""
        action = self.env["ir.actions.server"].create(
            {
                "name": "Fresh",
                "model_id": self.env["ir.model"]._get("mail.test.sms").id,
                "state": "sms",
                "sms_template_id": self.sms_template.id,
            }
        )
        self.assertEqual(action.sms_method, "sms")
        action.state = "code"
        self.assertFalse(action.sms_method)
        action.state = "sms"
        self.assertEqual(action.sms_method, "sms")
