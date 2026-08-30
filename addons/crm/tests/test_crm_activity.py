from datetime import date, timedelta

from odoo.tests.common import tagged, users

from odoo.addons.crm.tests.common import TestCrmCommon


@tagged("mail_activity")
class TestCrmMailActivity(TestCrmCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.activity_type_1 = cls.env["mail.activity.type"].create(
            {
                "name": "Initial Contact",
                "delay_count": 5,
                "summary": "ACT 1 : Presentation, barbecue, ... ",
                "res_model": "crm.lead",
            }
        )
        cls.activity_type_2 = cls.env["mail.activity.type"].create(
            {
                "name": "Call for Demo",
                "delay_count": 6,
                "summary": "ACT 2 : I want to show you my ERP!",
                "res_model": "crm.lead",
            }
        )
        for activity_type in cls.activity_type_1 + cls.activity_type_2:
            cls.env["ir.model.data"].create(
                {
                    "name": activity_type.name.lower().replace(" ", "_"),
                    "module": "crm",
                    "model": activity_type._name,
                    "res_id": activity_type.id,
                }
            )

    @users("user_sales_leads")
    def test_crm_activity_ordering(self):
        default_order = self.env["crm.lead"]._order
        self.assertEqual(default_order, "priority desc, id desc")
        test_leads = self._create_leads_batch(
            count=10, partner_ids=[self.contact_1.id, self.contact_2.id, False]
        ).sorted("id")

        for lead in test_leads:
            self.assertFalse(lead.my_activity_date_deadline)
        search_res = self.env["crm.lead"].search(
            [("id", "in", test_leads.ids)], limit=5, offset=0, order="id ASC"
        )
        self.assertEqual(search_res.ids, test_leads[:5].ids)
        search_res = self.env["crm.lead"].search(
            [("id", "in", test_leads.ids)], limit=5, offset=5, order="id ASC"
        )
        self.assertEqual(search_res.ids, test_leads[5:10].ids)

        today = date.today()
        deadline_in2d, deadline_in1d = (
            today + timedelta(days=2),
            today + timedelta(days=1),
        )
        deadline_was2d, deadline_was1d = (
            today + timedelta(days=-2),
            today + timedelta(days=-1),
        )
        deadlines_my = [
            deadline_in2d,
            deadline_was1d,
            deadline_was2d,
            deadline_was1d,
            deadline_was2d,
            deadline_in2d,
            False,
            False,
            False,
            False,
        ]
        deadlines_gl = [
            deadline_in1d,
            deadline_was1d,
            deadline_was2d,
            deadline_was1d,
            deadline_was2d,
            deadline_in2d,
            False,
            False,
            False,
            False,
        ]

        test_leads[0:4].activity_schedule(
            act_type_xmlid="crm.call_for_demo",
            user_id=self.user_sales_manager.id,
            date_deadline=deadline_in1d,
        )
        test_leads[0:3].activity_schedule(
            act_type_xmlid="crm.initial_contact",
            user_id=self.user_sales_leads.id,
            date_deadline=deadline_in2d,
        )
        test_leads[5].activity_schedule(
            act_type_xmlid="crm.initial_contact",
            user_id=self.user_sales_leads.id,
            date_deadline=deadline_in2d,
        )
        (test_leads[1] | test_leads[3]).activity_schedule(
            act_type_xmlid="crm.initial_contact",
            user_id=self.user_sales_leads.id,
            date_deadline=deadline_was1d,
        )
        (test_leads[2] | test_leads[4]).activity_schedule(
            act_type_xmlid="crm.call_for_demo",
            user_id=self.user_sales_leads.id,
            date_deadline=deadline_was2d,
        )
        test_leads.invalidate_recordset()

        expected_ids_asc = [2, 4, 1, 3, 5, 0, 8, 7, 9, 6]
        expected_leads_asc = self.env["crm.lead"].browse(
            [test_leads[lid].id for lid in expected_ids_asc]
        )
        expected_ids_desc = [5, 0, 1, 3, 2, 4, 8, 7, 9, 6]
        expected_leads_desc = self.env["crm.lead"].browse(
            [test_leads[lid].id for lid in expected_ids_desc]
        )

        for idx, lead in enumerate(test_leads):
            self.assertEqual(lead.my_activity_date_deadline, deadlines_my[idx])
            self.assertEqual(
                lead.activity_date_deadline, deadlines_gl[idx], "Fail at %s" % idx
            )

        _order = "my_activity_date_deadline ASC, %s" % default_order
        _domain = [("id", "in", test_leads.ids)]

        search_res = self.env["crm.lead"].search(
            _domain, limit=None, offset=0, order=_order
        )
        self.assertEqual(expected_leads_asc.ids, search_res.ids)
        search_res = self.env["crm.lead"].search(
            _domain, limit=4, offset=0, order=_order
        )
        self.assertEqual(expected_leads_asc[:4].ids, search_res.ids)
        search_res = self.env["crm.lead"].search(
            _domain, limit=4, offset=3, order=_order
        )
        self.assertEqual(expected_leads_asc[3:7].ids, search_res.ids)
        search_res = self.env["crm.lead"].search(
            _domain, limit=None, offset=3, order=_order
        )
        self.assertEqual(expected_leads_asc[3:].ids, search_res.ids)

        _order = "my_activity_date_deadline DESC, %s" % default_order
        search_res = self.env["crm.lead"].search(
            _domain, limit=None, offset=0, order=_order
        )
        self.assertEqual(expected_leads_desc.ids, search_res.ids)
        search_res = self.env["crm.lead"].search(
            _domain, limit=4, offset=0, order=_order
        )
        self.assertEqual(expected_leads_desc[:4].ids, search_res.ids)
        search_res = self.env["crm.lead"].search(
            _domain, limit=4, offset=3, order=_order
        )
        self.assertEqual(expected_leads_desc[3:7].ids, search_res.ids)
        search_res = self.env["crm.lead"].search(
            _domain, limit=None, offset=3, order=_order
        )
        self.assertEqual(expected_leads_desc[3:].ids, search_res.ids)

    def test_crm_activity_recipients(self):
        self.lead_1.message_subscribe(partner_ids=[self.contact_1.id])

        internal_subtypes = (
            self.lead_1.message_follower_ids.filtered(
                lambda fol: fol.partner_id == self.contact_1
            )
            .mapped("subtype_ids")
            .filtered(lambda subtype: subtype.internal)
        )
        self.assertFalse(internal_subtypes)

        self.lead_1.message_subscribe(
            partner_ids=[self.user_sales_manager.partner_id.id],
            subtype_ids=[
                self.env.ref("mail.mt_activities").id,
                self.env.ref("mail.mt_comment").id,
            ],
        )

        activity = (
            self.env["mail.activity"]
            .with_user(self.user_sales_leads)
            .create(
                {
                    "activity_type_id": self.activity_type_1.id,
                    "note": "Content of the activity to log",
                    "res_id": self.lead_1.id,
                    "res_model_id": self.env.ref("crm.model_crm_lead").id,
                }
            )
        )
        activity._onchange_activity_type_id()
        self.assertEqual(self.lead_1.activity_type_id, self.activity_type_1)
        self.assertEqual(self.lead_1.activity_summary, self.activity_type_1.summary)

        activity.action_done()
        self.assertFalse(self.lead_1.activity_ids)
        self.lead_1.invalidate_recordset(fnames=["activity_type_id"])
        self.assertFalse(self.lead_1.activity_type_id)
        activity_message = self.lead_1.message_ids[0]
        self.assertEqual(
            activity_message.notified_partner_ids, self.user_sales_manager.partner_id
        )
        self.assertEqual(
            activity_message.subtype_id, self.env.ref("mail.mt_activities")
        )

    def test_crm_activity_next_action(self):
        test_lead = self.lead_1.with_user(self.user_sales_manager)
        lead_model_id = self.env["ir.model"]._get("crm.lead").id
        activity = (
            self.env["mail.activity"]
            .with_user(self.user_sales_manager)
            .create(
                {
                    "activity_type_id": self.activity_type_1.id,
                    "summary": "My Own Summary",
                    "res_id": test_lead.id,
                    "res_model_id": lead_model_id,
                }
            )
        )
        activity._onchange_activity_type_id()

        self.assertEqual(test_lead.activity_summary, activity.summary)
        self.assertEqual(test_lead.activity_type_id, activity.activity_type_id)

        activity.write(
            {
                "activity_type_id": self.activity_type_2.id,
                "summary": "",
                "note": "Content of the activity to log",
            }
        )
        activity._onchange_activity_type_id()

        self.assertEqual(test_lead.activity_summary, activity.activity_type_id.summary)
        self.assertEqual(test_lead.activity_type_id, activity.activity_type_id)

        self.assertEqual(test_lead.activity_ids, activity)
        activity.action_done()

        self.assertFalse(test_lead.activity_ids)
        test_lead.invalidate_recordset(fnames=["activity_type_id"])
        self.assertFalse(test_lead.activity_type_id)
