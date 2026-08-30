import base64
from datetime import timedelta

from odoo.fields import Datetime
from odoo.tests.common import tagged, users
from odoo.tools import mute_logger

from odoo.addons.crm.tests.common import TestLeadConvertMassCommon


class TestLeadMergeCommon(TestLeadConvertMassCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.leads = (
            cls.lead_1
            + cls.lead_w_partner
            + cls.lead_w_contact
            + cls.lead_w_email
            + cls.lead_w_partner_company
            + cls.lead_w_email_lost
        )
        (cls.lead_w_partner | cls.lead_w_email_lost).write(
            {
                "user_id": False,
            }
        )
        cls.lead_w_partner.write({"stage_id": False})

        cls.lead_w_contact.write({"description": "lead_w_contact"})
        cls.lead_w_email.write({"description": "lead_w_email"})
        cls.lead_1.write({"description": "lead_1"})
        cls.lead_w_partner.write({"description": "lead_w_partner"})

        cls.assign_users = (
            cls.user_sales_manager
            + cls.user_sales_leads_convert
            + cls.user_sales_salesman
        )


@tagged("lead_manage")
class TestLeadMerge(TestLeadMergeCommon):
    def _run_merge_wizard(self, leads):
        res = (
            self.env["crm.merge.opportunity"]
            .with_context(
                {
                    "active_model": "crm.lead",
                    "active_ids": leads.ids,
                    "active_id": False,
                }
            )
            .create(
                {
                    "team_id": False,
                    "user_id": False,
                }
            )
            .action_merge()
        )
        return self.env["crm.lead"].browse(res["res_id"])

    def test_initial_data(self):
        self.assertFalse(self.lead_1.date_conversion)
        self.assertEqual(
            self.lead_1.date_open, Datetime.from_string("2020-01-15 11:30:00")
        )
        self.assertEqual(self.lead_1.user_id, self.user_sales_leads)
        self.assertEqual(self.lead_1.team_id, self.sales_team_1)
        self.assertEqual(self.lead_1.stage_id, self.stage_team1_1)
        self.assertEqual(self.lead_1.probability, 20)
        self.assertTrue(self.lead_1.automated_probability > 0)
        self.assertFalse(self.lead_1.is_automated_probability)

        self.assertEqual(self.lead_w_partner.stage_id, self.env["crm.stage"])
        self.assertEqual(self.lead_w_partner.user_id, self.env["res.users"])
        self.assertEqual(self.lead_w_partner.team_id, self.sales_team_1)

        self.assertEqual(self.lead_w_partner_company.stage_id, self.stage_team1_1)
        self.assertEqual(self.lead_w_partner_company.user_id, self.user_sales_manager)
        self.assertEqual(self.lead_w_partner_company.team_id, self.sales_team_1)

        self.assertEqual(self.lead_w_contact.stage_id, self.stage_gen_1)
        self.assertEqual(self.lead_w_contact.user_id, self.user_sales_salesman)
        self.assertEqual(self.lead_w_contact.team_id, self.sales_team_convert)

        self.assertEqual(self.lead_w_email.stage_id, self.stage_gen_1)
        self.assertEqual(self.lead_w_email.user_id, self.user_sales_salesman)
        self.assertEqual(self.lead_w_email.team_id, self.sales_team_convert)

        self.assertEqual(self.lead_w_email_lost.stage_id, self.stage_team1_2)
        self.assertEqual(self.lead_w_email_lost.user_id, self.env["res.users"])
        self.assertEqual(self.lead_w_email_lost.team_id, self.sales_team_1)

    @users("user_sales_manager")
    @mute_logger("odoo.models.unlink")
    def test_lead_merge_address_not_propagated(self):
        initial_address = {
            "street": "Test street",
            "street2": "Test street2",
            "city": "Test City",
            "zip": "5000",
            "state_id": False,
            "country_id": self.env.ref("base.be"),
        }
        self.lead_w_contact.write(initial_address)

        (self.leads - self.lead_w_contact).write(
            {
                "street": "Other street",
                "street2": "Other street2",
                "city": "Other City",
                "zip": "6666",
                "state_id": self.env.ref("base.state_us_1"),
                "country_id": False,
            }
        )

        leads = (
            self.env["crm.lead"]
            .browse(self.leads.ids)
            ._sort_by_confidence_level(reverse=True)
        )
        with self.assertLeadMerged(self.lead_w_contact, leads, **initial_address):
            leads._merge_opportunity(auto_unlink=False, max_length=None)

    @users("user_sales_manager")
    @mute_logger("odoo.models.unlink")
    def test_lead_merge_address_propagated(self):
        self.leads.write(
            {
                "street": "Original street",
                "street2": False,
                "city": False,
                "zip": False,
                "state_id": False,
                "country_id": False,
            }
        )
        new_address = {
            "street": "New street",
            "street2": False,
            "city": "New City",
            "zip": False,
            "state_id": False,
            "country_id": False,
        }
        self.lead_w_partner.write(new_address)
        self.lead_w_email_lost.write(
            {
                "street": "Other street",
                "street2": False,
                "city": "Other City",
                "zip": False,
                "state_id": False,
                "country_id": False,
            }
        )

        leads = (
            self.env["crm.lead"]
            .browse(self.leads.ids)
            ._sort_by_confidence_level(reverse=True)
        )

        with self.assertLeadMerged(self.lead_w_contact, leads, **new_address):
            leads._merge_opportunity(auto_unlink=False, max_length=None)

    @users("user_sales_manager")
    @mute_logger("odoo.models.unlink")
    def test_lead_merge_internals(self):
        self.lead_w_partner_company.action_set_won()

        merge = (
            self.env["crm.merge.opportunity"]
            .with_context(
                {
                    "active_model": "crm.lead",
                    "active_ids": self.leads.ids,
                    "active_id": False,
                }
            )
            .create(
                {
                    "user_id": self.user_sales_leads_convert.id,
                }
            )
        )
        self.assertEqual(merge.team_id, self.sales_team_convert)

        self.assertEqual(
            merge.opportunity_ids,
            self.leads - self.lead_w_partner_company,
            "Should not keep won opps",
        )
        ordered_merge = (
            self.lead_w_contact + self.lead_w_email + self.lead_1 + self.lead_w_partner
        )
        ordered_merge_description = "<br><br>".join(
            l.description for l in ordered_merge
        )

        result = merge.action_merge()
        merge_opportunity = self.env["crm.lead"].browse(result["res_id"])
        self.assertFalse((ordered_merge - merge_opportunity).exists())
        self.assertEqual(merge_opportunity, self.lead_w_contact)
        self.assertEqual(merge_opportunity.type, "lead")
        self.assertEqual(merge_opportunity.description, ordered_merge_description)
        self.assertEqual(merge_opportunity.user_id, self.user_sales_leads_convert)
        self.assertEqual(merge_opportunity.team_id, self.sales_team_convert)
        self.assertEqual(merge_opportunity.stage_id, self.stage_gen_1)

    @users("user_sales_manager")
    @mute_logger("odoo.models.unlink")
    def test_lead_merge_mixed(self):
        (self.lead_w_partner_company | self.lead_1).write({"type": "opportunity"})
        self.lead_1.write({"probability": 60})

        self.assertEqual(self.lead_w_partner_company.stage_id.sequence, 1)
        self.assertEqual(self.lead_1.stage_id.sequence, 1)

        merge = (
            self.env["crm.merge.opportunity"]
            .with_context(
                {
                    "active_model": "crm.lead",
                    "active_ids": self.leads.ids,
                    "active_id": False,
                }
            )
            .create(
                {
                    "team_id": self.sales_team_convert.id,
                    "user_id": False,
                }
            )
        )
        merge.write({"team_id": self.sales_team_convert.id})

        self.assertEqual(
            merge.opportunity_ids, self.leads, "Even lost are included if asked by user"
        )
        merge.write({"opportunity_ids": [(3, self.lead_w_email_lost.id)]})
        self.assertEqual(merge.opportunity_ids, self.leads - self.lead_w_email_lost)
        ordered_merge = (
            self.lead_w_partner_company
            + self.lead_w_contact
            + self.lead_w_email
            + self.lead_w_partner
        )

        result = merge.action_merge()
        merge_opportunity = self.env["crm.lead"].browse(result["res_id"])
        self.assertFalse((ordered_merge - merge_opportunity).exists())
        self.assertEqual(merge_opportunity, self.lead_1)
        self.assertEqual(merge_opportunity.type, "opportunity")

        self.assertEqual(merge_opportunity.user_id, self.user_sales_leads)
        self.assertEqual(merge_opportunity.team_id, self.sales_team_convert)
        self.assertEqual(merge_opportunity.stage_id, self.stage_team_convert_1)

    @users("user_sales_manager")
    @mute_logger("odoo.models.unlink")
    def test_lead_merge_probability_auto(self):
        self.lead_1.write(
            {"type": "opportunity", "probability": self.lead_1.automated_probability}
        )
        self.assertTrue(self.lead_1.is_automated_probability)
        leads = self.env["crm.lead"].browse(
            (self.lead_1 + self.lead_w_partner + self.lead_w_partner_company).ids
        )
        merged_lead = self._run_merge_wizard(leads)
        self.assertEqual(merged_lead, self.lead_1)
        self.assertTrue(
            merged_lead.is_automated_probability,
            "lead with Auto proba should remain with auto probability",
        )

    @users("user_sales_manager")
    @mute_logger("odoo.models.unlink")
    def test_lead_merge_probability_auto_empty(self):
        self.lead_1.write(
            {"type": "opportunity", "probability": 0, "automated_probability": 0}
        )
        self.assertTrue(self.lead_1.is_automated_probability)
        leads = self.env["crm.lead"].browse(
            (self.lead_1 + self.lead_w_partner + self.lead_w_partner_company).ids
        )
        merged_lead = self._run_merge_wizard(leads)
        self.assertEqual(merged_lead, self.lead_1)
        self.assertTrue(
            merged_lead.is_automated_probability,
            "lead with Auto proba should remain with auto probability",
        )

    @users("user_sales_manager")
    @mute_logger("odoo.models.unlink")
    def test_lead_merge_probability_manual(self):
        self.lead_1.write({"probability": 60})
        self.assertFalse(self.lead_1.is_automated_probability)
        leads = self.env["crm.lead"].browse(
            (self.lead_1 + self.lead_w_partner + self.lead_w_partner_company).ids
        )
        merged_lead = self._run_merge_wizard(leads)
        self.assertEqual(merged_lead, self.lead_1)
        self.assertEqual(
            merged_lead.probability,
            60,
            "Manual Probability should remain the same after the merge",
        )
        self.assertFalse(merged_lead.is_automated_probability)

    @users("user_sales_manager")
    @mute_logger("odoo.models.unlink")
    def test_lead_merge_probability_manual_empty(self):
        self.lead_1.write({"type": "opportunity", "probability": 0})
        leads = self.env["crm.lead"].browse(
            (self.lead_1 + self.lead_w_partner + self.lead_w_partner_company).ids
        )
        merged_lead = self._run_merge_wizard(leads)
        self.assertEqual(merged_lead, self.lead_1)
        self.assertTrue(self.lead_1.automated_probability > 0)
        self.assertEqual(
            merged_lead.probability,
            0,
            "Manual Probability should remain the same after the merge",
        )
        self.assertFalse(merged_lead.is_automated_probability)

    @users("user_sales_manager")
    @mute_logger("odoo.models.unlink")
    def test_merge_method(self):
        (self.lead_w_partner_company | self.lead_1).write(
            {"type": "opportunity", "probability": 50}
        )
        leads = (
            self.env["crm.lead"]
            .browse(self.leads.ids)
            ._sort_by_confidence_level(reverse=True)
        )

        lost_reason = self.env["crm.lost.reason"].create({"name": "Test Reason"})
        self.lead_w_partner.write(
            {
                "lost_reason_id": lost_reason,
                "probability": 0,
            }
        )

        all_tags = self.leads.mapped("tag_ids")

        with self.assertLeadMerged(
            self.lead_1,
            leads,
            name="Nibbler Spacecraft Request",
            partner_id=self.contact_company_1,
            priority="2",
            lost_reason_id=False,
            tag_ids=all_tags,
        ):
            leads._merge_opportunity(auto_unlink=False, max_length=None)

    @users("user_sales_manager")
    @mute_logger("odoo.models.unlink")
    def test_merge_method_propagate_lost_reason(self):
        self.leads.write(
            {
                "probability": 0,
                "automated_probability": 50,
            }
        )

        lost_reason = self.env["crm.lost.reason"].create({"name": "Test Reason"})
        self.lead_w_partner.lost_reason_id = lost_reason

        leads = (
            self.env["crm.lead"]
            .browse(self.leads.ids)
            ._sort_by_confidence_level(reverse=True)
        )

        with self.assertLeadMerged(leads[0], leads, lost_reason_id=lost_reason):
            leads._merge_opportunity(auto_unlink=False, max_length=None)

    @users("user_sales_manager")
    def test_lead_merge_properties_formatting(self):
        lead = self.lead_1
        partners = self.env["res.partner"].create([{"name": "Alice"}, {"name": "Bob"}])

        lead.lead_properties = [
            {
                "type": "many2one",
                "comodel": "res.partner",
                "name": "test_many2one",
                "string": "My Partner",
                "value": partners[0].id,
                "definition_changed": True,
            },
            {
                "type": "many2many",
                "comodel": "res.partner",
                "name": "test_many2many",
                "string": "My Partners",
                "value": partners.ids,
            },
            {
                "type": "selection",
                "selection": [["a", "A"], ["b", "B"]],
                "name": "test_selection",
                "string": "My Selection",
                "value": "a",
            },
            {
                "type": "tags",
                "tags": [["a", "A", 1], ["b", "B", 2], ["c", "C", 3]],
                "name": "test_tags",
                "string": "My Tags",
                "value": ["a", "c"],
            },
            {
                "type": "boolean",
                "name": "test_boolean",
                "string": "My Boolean",
                "value": True,
            },
            {
                "type": "integer",
                "name": "test_integer",
                "string": "My Integer",
                "value": 1337,
            },
            {
                "type": "datetime",
                "name": "test_datetime",
                "string": "My Datetime",
                "value": "2022-02-21 16:11:42",
            },
        ]

        expected = [
            {
                "label": "My Partner",
                "value": "Alice",
            },
            {
                "label": "My Partners",
                "values": [
                    {"name": "Alice"},
                    {"name": "Bob"},
                ],
            },
            {
                "label": "My Selection",
                "value": "A",
            },
            {
                "label": "My Tags",
                "values": [
                    {"name": "A", "color": 1},
                    {"name": "C", "color": 3},
                ],
            },
            {
                "label": "My Boolean",
                "value": "Yes",
            },
            {
                "label": "My Integer",
                "value": 1337,
            },
            {
                "label": "My Datetime",
                "value": "2022-02-21 16:11:42",
            },
        ]

        self.assertEqual(expected, lead._format_properties())

        result = self.env["ir.qweb"]._render(
            "crm.crm_lead_merge_summary",
            {"opportunities": lead, "is_html_empty": lambda x: True},
        )
        self.assertIn("o_tag_color_1", result)
        self.assertIn("Alice", result)
        self.assertIn("Bob", result)

    @users("user_sales_manager")
    def test_merge_method_dependencies(self):
        self.env["crm.lead"].browse(self.lead_w_partner_company.ids).write(
            {"type": "opportunity"}
        )

        attachments = self.env["ir.attachment"].create(
            [
                {
                    "name": "%02d.txt" % idx,
                    "datas": base64.b64encode(b"Att%02d" % idx),
                    "res_model": "crm.lead",
                    "res_id": self.lead_w_email.id,
                }
                for idx in range(4)
            ]
        )
        lead_1 = self.env["crm.lead"].browse(self.lead_1.ids)
        activity = lead_1.activity_schedule(
            "crm.lead_test_activity_1", user_id=self.user_sales_manager.id
        )
        calendar_event = self.env["calendar.event"].create(
            {
                "name": "Meeting with partner",
                "activity_ids": [(4, activity.id)],
                "start": "2021-06-12 21:00:00",
                "stop": "2021-06-13 00:00:00",
                "res_model_id": self.env["ir.model"]._get("crm.crm_lead").id,
                "res_id": lead_1.id,
                "opportunity_id": lead_1.id,
            }
        )

        merge = (
            self.env["crm.merge.opportunity"]
            .with_context(
                {
                    "active_model": "crm.lead",
                    "active_ids": (self.leads - self.lead_w_email_lost).ids,
                    "active_id": False,
                }
            )
            .create(
                {
                    "team_id": self.sales_team_convert.id,
                    "user_id": False,
                }
            )
        )
        result = merge.action_merge()
        master_lead = self.leads.filtered(lambda lead: lead.id == result["res_id"])

        self.assertEqual(master_lead, self.lead_w_partner_company)
        self.assertEqual(calendar_event.opportunity_id, master_lead)
        self.assertEqual(calendar_event.res_id, master_lead.id)
        self.assertTrue(all(att.res_id == master_lead.id for att in attachments))
        self.assertEqual(master_lead.activity_ids, activity)
        self.assertEqual(master_lead.calendar_event_ids, calendar_event)

    @users("user_sales_manager")
    @mute_logger("odoo.models.unlink")
    def test_merge_method_followers(self):
        self.leads.message_follower_ids.unlink()
        self.leads.message_ids.unlink()

        self.lead_w_contact.message_subscribe([self.contact_1.id])
        self.lead_w_email.message_subscribe(
            [self.contact_1.id, self.contact_2.id, self.contact_company.id]
        )
        self.lead_w_partner.message_subscribe([self.contact_2.id])

        self.env["mail.message"].create(
            [
                {
                    "author_id": self.contact_1.id,
                    "model": "crm.lead",
                    "res_id": self.lead_w_contact.id,
                    "date": Datetime.now() - timedelta(days=1),
                    "subtype_id": self.ref("mail.mt_comment"),
                    "reply_to": False,
                    "body": "Test follower",
                },
                {
                    "author_id": self.contact_1.id,
                    "model": "crm.lead",
                    "res_id": self.lead_w_email.id,
                    "date": Datetime.now() - timedelta(days=20),
                    "subtype_id": self.ref("mail.mt_comment"),
                    "reply_to": False,
                    "body": "Test follower",
                },
                {
                    "author_id": self.contact_2.id,
                    "model": "crm.lead",
                    "res_id": self.lead_w_email.id,
                    "date": Datetime.now() - timedelta(days=15),
                    "subtype_id": self.ref("mail.mt_comment"),
                    "reply_to": False,
                    "body": "Test follower",
                },
                {
                    "author_id": self.contact_2.id,
                    "model": "crm.lead",
                    "res_id": self.lead_w_partner.id,
                    "date": Datetime.now() - timedelta(days=29),
                    "subtype_id": self.ref("mail.mt_comment"),
                    "reply_to": False,
                    "body": "Test follower",
                },
                {
                    "author_id": self.contact_company.id,
                    "model": "crm.lead",
                    "res_id": self.lead_w_email.id,
                    "date": Datetime.now() - timedelta(days=35),
                    "subtype_id": self.ref("mail.mt_comment"),
                    "reply_to": False,
                    "body": "Test follower",
                },
                {
                    "author_id": self.contact_company.id,
                    "model": "crm.lead",
                    "res_id": self.lead_w_partner.id,
                    "date": Datetime.now(),
                    "subtype_id": self.ref("mail.mt_comment"),
                    "reply_to": False,
                    "body": "Test follower",
                },
            ]
        )
        initial_followers = self.lead_w_contact.message_follower_ids

        leads = (
            self.env["crm.lead"]
            .browse(self.leads.ids)
            ._sort_by_confidence_level(reverse=True)
        )
        master_lead = leads._merge_opportunity(max_length=None)

        self.assertEqual(master_lead, self.lead_w_contact)

        new_partner_followers = (
            master_lead.message_follower_ids - initial_followers
        ).partner_id
        self.assertIn(
            self.contact_2,
            new_partner_followers,
            "The partner must follow the destination lead",
        )
        self.assertNotIn(
            self.contact_company,
            new_partner_followers,
            "The partner was not active on the lead",
        )
        self.assertIn(
            self.contact_1,
            master_lead.message_follower_ids.partner_id,
            "Should not have removed follower of the destination lead",
        )


@tagged("lead_manage", "crm_access")
class TestLeadMergeAccess(TestLeadMergeCommon):
    @users("user_sales_salesman")
    def test_merge_stays_available_to_a_salesperson(self):
        self.assertFalse(
            self.env["crm.lead"].browse().has_access("unlink"),
            "Precondition: a salesperson may not delete leads",
        )

        leads = self.env["crm.lead"].create(
            [
                {
                    "email_from": "duplicate@test.example.com",
                    "name": f"Duplicate {index}",
                    "team_id": self.sales_team_1.id,
                    "type": "opportunity",
                    "user_id": self.env.user.id,
                }
                for index in range(2)
            ]
        )
        self.env.flush_all()

        head = leads.merge_opportunity()
        self.assertIn(head, leads)
        self.assertFalse((leads - head).exists(), "The tail is consolidated away")
        self.assertTrue(head.exists())
