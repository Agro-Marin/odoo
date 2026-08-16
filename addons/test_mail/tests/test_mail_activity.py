# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import UTC, date, datetime, timedelta
from unittest.mock import DEFAULT, patch

from dateutil.relativedelta import relativedelta
from psycopg import IntegrityError

from odoo import exceptions, fields, tests
from odoo.libs.datetime import timezone
from odoo.tests import Form, HttpCase, users
from odoo.tests.common import freeze_time
from odoo.tools import mute_logger

from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.mail.tests.common_activity import ActivityScheduleCase
from odoo.addons.test_mail.models.test_mail_models import MailTestActivity


class TestActivityCommon(ActivityScheduleCase):

    @classmethod
    def setUpClass(cls):
        super(TestActivityCommon, cls).setUpClass()
        cls.test_record, cls.test_record_2 = cls.env['mail.test.activity'].create([
            {'name': 'Test'},
            {'name': 'Test_2'},
        ])


@tests.tagged('mail_activity')
class TestActivityRights(TestActivityCommon):

    def test_activity_action_open_document_no_access(self):
        def _employee_no_access(records, operation):
            """Simulates employee having no access to the document"""
            if records.env.uid == self.user_employee.id and not records.env.su:
                return records, lambda: exceptions.AccessError('Access denied to document')
            return DEFAULT

        test_activity = self.env['mail.activity'].with_user(self.user_admin).create({
            'activity_type_id': self.env.ref('test_mail.mail_act_test_todo').id,
            'res_model_id': self.env.ref('test_mail.model_mail_test_activity').id,
            'res_id': self.test_record.id,
            'user_id': self.user_employee.id,
            'summary': 'Test Activity',
        })

        action = test_activity.with_user(self.user_employee).action_open_document()
        self.assertEqual(action['res_model'], self.test_record._name)
        self.assertEqual(action['res_id'], self.test_record.id)

        # If user has no access to the record, should return activity view instead
        with patch.object(MailTestActivity, '_check_access', autospec=True, side_effect=_employee_no_access):
            self.assertFalse(self.test_record.with_user(self.user_employee).has_access('read'))

            action = test_activity.with_user(self.user_employee).action_open_document()
            self.assertEqual(action['res_model'], 'mail.activity')
            self.assertEqual(action['res_id'], test_activity.id)

    @mute_logger('odoo.addons.mail.models.mail_mail')
    def test_activity_security_user_access(self):
        """ Internal user can modify assigned or created or if write on document """
        def _employee_crash(records, operation):
            """ If employee is test employee, consider they have no access on document """
            if records.env.uid == self.user_employee.id and not records.env.su:
                return records, lambda: exceptions.AccessError('Hop hop hop Ernest, please step back.')
            return DEFAULT

        act_emp_for_adm = self.test_record.with_user(self.user_employee).activity_schedule(
            'test_mail.mail_act_test_todo',
            user_id=self.user_admin.id,
        )
        act_emp_for_emp = self.test_record.with_user(self.user_employee).activity_schedule(
            'test_mail.mail_act_test_todo',
            user_id=self.user_employee.id,
        )
        act_adm_for_adm = self.test_record.with_user(self.user_admin).activity_schedule(
            'test_mail.mail_act_test_todo',
            user_id=self.user_admin.id,
        )
        act_adm_for_emp = self.test_record.with_user(self.user_admin).activity_schedule(
            'test_mail.mail_act_test_todo',
            user_id=self.user_employee.id,
        )

        for activity, can_write in [
            (act_emp_for_adm, True), (act_emp_for_emp, True),
            (act_adm_for_adm, False), (act_adm_for_emp, True),
        ]:
            with self.subTest(user=activity.user_id.name, creator=activity.create_uid.name):
                # no document access -> based on create_uid / user_id
                with patch.object(MailTestActivity, '_check_access', autospec=True, side_effect=_employee_crash):
                    activity = activity.with_user(self.user_employee)
                    self.assertEqual(activity.can_write, can_write)
                    if can_write:
                        activity.write({'summary': 'Caramba'})
                    else:
                        with self.assertRaises(exceptions.AccessError):
                            activity.write({'summary': 'Caramba'})

                # document access -> ok bypass
                activity.write({'summary': 'Caramba caramba'})

    def test_activity_security_user_access_customized(self):
        """ Test '_mail_get_operation_for_mail_message_operation' support when scheduling activities. """
        access_open, access_ro, access_locked = self.env['mail.test.access.custo'].with_user(self.user_admin).create([
            {'name': 'Open'},
            {'name': 'Open RO', 'is_readonly': True},
            {'name': 'Locked', 'is_locked': True},
        ])
        admin_activities = self.env['mail.activity']
        for record in access_open + access_ro + access_locked:
            admin_activities += record.with_user(self.user_admin).activity_schedule(
                'test_mail.mail_act_test_todo_generic',
            )

        # sanity checks on rule implementation
        (access_open + access_ro + access_locked).with_user(self.user_employee).check_access('read')
        access_open.with_user(self.user_employee).check_access('write')
        with self.assertRaises(exceptions.AccessError):
            (access_ro + access_locked).with_user(self.user_employee).check_access('write')

        # '_mail_get_operation_for_mail_message_operation' allows to post, hence posting activities
        emp_new_1 = access_open.with_user(self.user_employee).activity_schedule(
            'test_mail.mail_act_test_todo_generic',
        )
        emp_new_2 = access_ro.with_user(self.user_employee).activity_schedule(
            'test_mail.mail_act_test_todo_generic',
        )

        with self.assertRaises(exceptions.AccessError):
            access_locked.with_user(self.user_employee).activity_schedule(
                'test_mail.mail_act_test_todo_generic',
            )

        self.env.invalidate_all()
        # check read access correctly uses '_mail_get_operation_for_mail_message_operation'
        admin_activities[0].with_user(self.user_employee).read(['summary'])
        admin_activities[1].with_user(self.user_employee).read(['summary'])

        self.env.invalidate_all()
        # check search correctly uses '_get_mail_message_access'
        found = self.env['mail.activity'].with_user(self.user_employee).search([('res_model', '=', 'mail.test.access.custo')])
        self.assertEqual(found, admin_activities[:2] + emp_new_1 + emp_new_2, 'Should respect _get_mail_message_access, reading non locked records')

    @mute_logger('odoo.addons.mail.models.mail_mail')
    def test_activity_security_user_noaccess_automated(self):
        def _employee_crash(records, operation):
            """ If employee is test employee, consider they have no access on document """
            if records.env.uid == self.user_employee.id and not records.env.su:
                return records, lambda: exceptions.AccessError('Hop hop hop Ernest, please step back.')
            return DEFAULT

        with patch.object(MailTestActivity, '_check_access', autospec=True, side_effect=_employee_crash):
            _activity = self.test_record.activity_schedule(
                'test_mail.mail_act_test_todo',
                user_id=self.user_employee.id)

            activity2 = self.test_record.activity_schedule('test_mail.mail_act_test_todo', user_id=self.user_admin.id)
            activity2.write({'user_id': self.user_employee.id})

    def test_activity_security_user_noaccess_manual(self):
        def _employee_crash(records, operation):
            """ If employee is test employee, consider they have no access on document """
            if records.env.uid == self.user_employee.id and not records.env.su:
                raise exceptions.AccessError('Hop hop hop Ernest, please step back.')
            return DEFAULT

        test_activity = self.env['mail.activity'].with_user(self.user_admin).create({
            'activity_type_id': self.env.ref('test_mail.mail_act_test_todo').id,
            'res_model_id': self.env.ref('test_mail.model_mail_test_activity').id,
            'res_id': self.test_record.id,
            'user_id': self.user_admin.id,
            'summary': 'Summary',
        })
        test_activity.flush_recordset()

        # can _search activities if access to the document
        self.env['mail.activity'].with_user(self.user_employee)._search(
            [('id', '=', test_activity.id)])

        # cannot _search activities if no access to the document
        with patch.object(MailTestActivity, '_check_access', autospec=True, side_effect=_employee_crash):
            with self.assertRaises(exceptions.AccessError):
                searched_activity = self.env['mail.activity'].with_user(self.user_employee)._search(
                    [('id', '=', test_activity.id)])

        # can formatted_read_group activities if access to the document
        read_group_result = self.env['mail.activity'].with_user(self.user_employee).formatted_read_group(
            [('id', '=', test_activity.id)],
            ['summary'],
            ['__count'],
        )
        self.assertEqual(1, read_group_result[0]['__count'])
        self.assertEqual('Summary', read_group_result[0]['summary'])

        # cannot read_group activities if no access to the document
        with patch.object(MailTestActivity, '_check_access', autospec=True, side_effect=_employee_crash):
            with self.assertRaises(exceptions.AccessError):
                self.env['mail.activity'].with_user(self.user_employee).formatted_read_group(
                    [('id', '=', test_activity.id)],
                    ['summary'],
                    ['__count'],
                )

        # cannot read activities if no access to the document
        with patch.object(MailTestActivity, '_check_access', autospec=True, side_effect=_employee_crash):
            with self.assertRaises(exceptions.AccessError):
                searched_activity = self.env['mail.activity'].with_user(self.user_employee).search(
                    [('id', '=', test_activity.id)])
                searched_activity.read(['summary'])

        # cannot search_read activities if no access to the document
        with patch.object(MailTestActivity, '_check_access', autospec=True, side_effect=_employee_crash):
            with self.assertRaises(exceptions.AccessError):
                self.env['mail.activity'].with_user(self.user_employee).search_read(
                    [('id', '=', test_activity.id)],
                    ['summary'])

        # can create activities for people that cannot access record
        with patch.object(MailTestActivity, '_check_access', autospec=True, side_effect=_employee_crash):
            self.env['mail.activity'].create({
                'activity_type_id': self.env.ref('test_mail.mail_act_test_todo').id,
                'res_model_id': self.env.ref('test_mail.model_mail_test_activity').id,
                'res_id': self.test_record.id,
                'user_id': self.user_employee.id,
            })

        # cannot create activities if no access to the document
        with patch.object(MailTestActivity, '_check_access', autospec=True, side_effect=_employee_crash):
            with self.assertRaises(exceptions.AccessError):
                activity = self.test_record.with_user(self.user_employee).activity_schedule(
                    'test_mail.mail_act_test_todo',
                    user_id=self.user_admin.id)

        test_activity.user_id = self.user_employee
        test_activity.flush_recordset()

        # user can read activities assigned to him even if he has no access to the document
        with patch.object(MailTestActivity, '_check_access', autospec=True, side_effect=_employee_crash):
            found = self.env['mail.activity'].with_user(self.user_employee).search(
                [('id', '=', test_activity.id)])
            self.assertEqual(found, test_activity)
            found.read(['summary'])

        # user can read_group activities assigned to him even if he has no access to the document
        with patch.object(MailTestActivity, '_check_access', autospec=True, side_effect=_employee_crash):
            read_group_result = self.env['mail.activity'].with_user(self.user_employee).formatted_read_group(
                [('id', '=', test_activity.id)],
                ['summary'],
                ['__count'],
            )
            self.assertEqual(1, read_group_result[0]['__count'])
            self.assertEqual('Summary', read_group_result[0]['summary'])


@tests.tagged('mail_activity')
class TestActivityFlow(TestActivityCommon):

    def test_activity_flow_employee(self):
        with self.with_user('employee'):
            test_record = self.env['mail.test.activity'].browse(self.test_record.id)
            self.assertEqual(test_record.activity_ids, self.env['mail.activity'])

            # employee record an activity and check the deadline
            activity = self.env['mail.activity'].create({
                'summary': 'Test Activity',
                'date_deadline': date.today() + relativedelta(days=1),
                'activity_type_id': self.env.ref('mail.mail_activity_data_email').id,
                'res_model_id': self.env['ir.model']._get(test_record._name).id,
                'res_id': test_record.id,
            })
            self.assertEqual(test_record.activity_summary, 'Test Activity')
            self.assertEqual(test_record.activity_state, 'planned')

            test_record.activity_ids.write({'date_deadline': date.today() - relativedelta(days=1)})
            self.assertEqual(test_record.activity_state, 'overdue')

            test_record.activity_ids.write({'date_deadline': date.today()})
            self.assertEqual(test_record.activity_state, 'today')

            # activity is done
            activity.action_feedback(feedback='So much feedback')
            self.assertEqual(activity.feedback, 'So much feedback')
            self.assertEqual(test_record.activity_ids, self.env['mail.activity'])
            self.assertEqual(test_record.message_ids[0].subtype_id, self.env.ref('mail.mt_activities'))

    @mute_logger('odoo.addons.mail.models.mail_mail')
    def test_activity_notify_other_user(self):
        self.user_admin.notification_type = 'email'
        rec = self.test_record.with_user(self.user_employee)
        with self.assertSinglePostNotifications(
                [{'partner': self.partner_admin, 'type': 'email'}],
                message_info={'content': 'assigned you the following activity', 'subtype': 'mail.mt_note', 'message_type': 'user_notification'}):
            activity = rec.activity_schedule(
                'test_mail.mail_act_test_todo',
                user_id=self.user_admin.id)
        self.assertEqual(activity.create_uid, self.user_employee)
        self.assertEqual(activity.user_id, self.user_admin)

    def test_activity_notify_same_user(self):
        self.user_employee.notification_type = 'email'
        rec = self.test_record.with_user(self.user_employee)
        with self.assertNoNotifications():
            activity = rec.activity_schedule(
                'test_mail.mail_act_test_todo',
                user_id=self.user_employee.id)
        self.assertEqual(activity.create_uid, self.user_employee)
        self.assertEqual(activity.user_id, self.user_employee)

    @mute_logger('odoo.addons.mail.models.mail_mail')
    def test_activity_dont_notify_no_user_change(self):
        self.user_employee.notification_type = 'email'
        activity = self.test_record.activity_schedule('test_mail.mail_act_test_todo', user_id=self.user_employee.id)
        with self.assertNoNotifications():
            activity.with_user(self.user_admin).write({'user_id': self.user_employee.id})
        self.assertEqual(activity.user_id, self.user_employee)

    def test_activity_summary_sync(self):
        """ Test summary from type is copied on activities if set (currently only in form-based onchange) """
        ActivityType = self.env['mail.activity.type']
        call_activity_type = ActivityType.create({'name': 'call', 'sequence': 1})
        email_activity_type = ActivityType.create({
            'name': 'email',
            'summary': 'Email Summary',
            'sequence': '30'
        })
        call_activity_type = ActivityType.create({'name': 'call', 'summary': False})
        with Form(
            self.env['mail.activity'].with_context(
                default_res_model_id=self.env['ir.model']._get_id('mail.test.activity'),
                default_res_id=self.test_record.id,
            )
        ) as ActivityForm:
            # coming from default activity type, which is to do
            self.assertEqual(ActivityForm.activity_type_id, self.env.ref("mail.mail_activity_data_todo"))
            self.assertEqual(ActivityForm.summary, "TodoSummary")
            # `res_model_id` and `res_id` are invisible, see view `mail.mail_activity_view_form_popup`
            # they must be set using defaults, see `action_feedback_schedule_next`
            ActivityForm.activity_type_id = call_activity_type
            # activity summary should be empty
            self.assertEqual(ActivityForm.summary, "TodoSummary", "Did not erase if void on type")

            ActivityForm.activity_type_id = email_activity_type
            # activity summary should be replaced with email's default summary
            self.assertEqual(ActivityForm.summary, email_activity_type.summary)

            ActivityForm.activity_type_id = call_activity_type
            # activity summary remains unchanged from change of activity type as call activity doesn't have default summary
            self.assertEqual(ActivityForm.summary, email_activity_type.summary)

    def test_activity_type_unlink(self):
        """ Removing type should allocate activities to Todo """
        email_activity_type = self.env['mail.activity.type'].create({
            'name': 'email',
            'summary': 'Email Summary',
        })
        temp_record = self.env['mail.test.activity'].create({'name': 'Test'})
        activity = temp_record.activity_schedule(
            activity_type_id=email_activity_type.id,
            user_id=self.user_employee.id,
        )
        self.assertEqual(activity.activity_type_id, email_activity_type)
        email_activity_type.unlink()
        self.assertEqual(activity.activity_type_id, self.env.ref('mail.mail_activity_data_todo'))

        # Todo is protected, niark niark
        with self.assertRaises(exceptions.UserError):
            self.env.ref('mail.mail_activity_data_todo').unlink()

    @mute_logger('odoo.db')
    def test_activity_values(self):
        """ Test activities are created with right model / res_id values linking
        to records without void values. 0 as res_id especially is not wanted. """
        # creating activities on a temporary record generates activities with res_id
        # being 0, which is annoying -> never create activities in transient mode
        temp_record = self.env['mail.test.activity'].new({'name': 'Test'})
        with self.assertRaises(IntegrityError):
            activity = temp_record.activity_schedule('test_mail.mail_act_test_todo', user_id=self.user_employee.id)

        test_record = self.env['mail.test.activity'].browse(self.test_record.ids)

        # document should be complete: both model and res_id
        with self.assertRaises(IntegrityError):
            self.env['mail.activity'].create({
                'res_model_id': self.env['ir.model']._get_id(test_record._name),
            })
        with self.assertRaises(IntegrityError):
            self.env['mail.activity'].create({
                'res_model_id': self.env['ir.model']._get_id(test_record._name),
                'res_id': False,
            })
        with self.assertRaises(IntegrityError):
            self.env['mail.activity'].create({
                'res_id': test_record.id,
            })
        # free activity is ok (no model, no res_id)
        self.env['mail.activity'].create({'user_id': self.env.uid})

        activity = self.env['mail.activity'].create({
            'res_id': test_record.id,
            'res_model_id': self.env['ir.model']._get_id(test_record._name),
        })
        with self.assertRaises(IntegrityError):
            activity.write({'res_model_id': False})
            self.env.flush_all()
        with self.assertRaises(IntegrityError):
            activity.write({'res_id': False})
            self.env.flush_all()
        with self.assertRaises(IntegrityError):
            activity.write({'res_id': 0})
            self.env.flush_all()


@tests.tagged("mail_activity", "post_install", "-at_install")
class TestActivitySystray(TestActivityCommon, HttpCase):
    """Test for systray_get_activities"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_lead_records = cls.env['mail.test.multi.company.with.activity'].create([
            {'name': 'Test Lead 1'},
            {'name': 'Test Lead 2'},
            {'name': 'Test Lead 3 (to remove)'},
            {'name': 'Test Lead 4 (Company2)', 'company_id': cls.company_2.id},
        ])
        cls.deleted_record = cls.test_lead_records[2]
        cls.dt_reference = datetime(2024, 1, 15, 8, 0, 0)

        # remove potential demo data on admin, to make test deterministic
        cls.env['mail.activity'].search([('user_id', '=', cls.user_admin.id)]).unlink()

        # records and leads and free activities
        # have 1 record (or activity) for today, one for tomorrow
        cls.test_activities = cls.env['mail.activity']
        for record, summary, dt, creator in (
            (cls.test_record, "Summary Today'", cls.dt_reference, cls.user_employee),
            (cls.test_record_2, "Summary Tomorrow'", cls.dt_reference + timedelta(days=1), cls.user_employee),
            (cls.test_lead_records[0], "Summary Today'", cls.dt_reference, cls.user_employee),
            (cls.test_lead_records[1], "Summary Tomorrow'", cls.dt_reference + timedelta(days=1), cls.user_employee),
            (cls.test_lead_records[2], "Summary Tomorrow'", cls.dt_reference + timedelta(days=1), cls.user_employee),
            (cls.test_lead_records[3], "Summary Tomorrow'", cls.dt_reference + timedelta(days=1), cls.user_admin),
        ):
            cls.test_activities += record.with_user(creator).activity_schedule(
                "test_mail.mail_act_test_todo_generic",
                date_deadline=dt.date(),
                summary=summary,
                user_id=cls.user_employee.id,
            )

        cls.test_lead_activities = cls.test_activities[2:]
        cls.test_activities_removed = cls.deleted_record.activity_ids
        cls.test_activities_company_2 = cls.test_lead_records[3].activity_ids

        # add atttachments on lead-like test records
        cls.lead_act_attachments = cls.env['ir.attachment'].create(
            cls._generate_attachments_data(1, 'mail.activity', cls.test_lead_activities[-4]) +
            cls._generate_attachments_data(1, 'mail.activity', cls.test_lead_activities[-3]) +
            cls._generate_attachments_data(1, 'mail.activity', cls.test_lead_activities[-2]) +
            cls._generate_attachments_data(1, 'mail.activity', cls.test_lead_activities[-1])
        )

        # free (no model) activities
        cls.test_activities_free = cls.env['mail.activity'].with_user(cls.user_employee).create([
            {
                'date_deadline': dt,
                'summary': "Summary",
                'user_id': cls.user_employee.id,
            }
            for dt in (cls.dt_reference, cls.dt_reference + timedelta(days=1))
        ])

        # In the mean time, some FK deletes the record where the message is
        # scheduled, skipping its unlink() override
        cls.env.cr.execute(
            f"DELETE FROM {cls.test_lead_records._table} WHERE id = %s", (cls.deleted_record.id,)
        )

        cls.env.invalidate_all()

    @users("employee")
    def test_systray_activities_for_various_records(self):
        """Check that activities made on archived or not archived records, as
        well as on removed record, to check systray activities behavior and
        robustness. """
        # archive record 1
        self.test_record.action_archive()
        self.assertTrue(self.test_activities[0].exists(), 'Archiving record keeps activities')

        self.authenticate(self.user_employee.login, self.user_employee.login)
        with freeze_time(self.dt_reference):
            groups_data = self.make_jsonrpc_request("/mail/data", {"fetch_params": ["systray_get_activities"]}).get('Store', {}).get('activityGroups', [])
        self.assertEqual(len(groups_data), 3, 'Should have activities for 2 test models + generic for non accessible')

        for model_name, msg, (exp_total, exp_today, exp_planned, exp_overdue), exp_domain in [
            ('mail.activity', '2 free + 2 linked to 1', (1, 1, 3, 0), []),
            (self.test_record._name, 'Archived keeps activities', (1, 1, 1, 0), [['active', 'in', [True, False]]]),
            (self.test_lead_records._name, 'Planned do not count in total', (1, 1, 1, 0), []),
        ]:
            with self.subTest(model_name=model_name, msg=msg):
                group_values = next(values for values in groups_data if values['model'] == model_name)
                self.assertEqual(group_values['total_count'], exp_total)
                self.assertEqual(group_values['today_count'], exp_today)
                self.assertEqual(group_values['planned_count'], exp_planned)
                self.assertEqual(group_values['overdue_count'], exp_overdue)
                self.assertEqual(group_values['domain'], exp_domain)

        # check search results with removed records
        self.env.invalidate_all()
        test_with_removed = self.env['mail.activity'].sudo().search([
            ('id', 'in', self.test_activities.ids),
            ('res_model', '=', self.test_lead_records._name),
        ])
        self.assertEqual(len(test_with_removed), 4, 'Without ACL check, activities linked to removed records are kept')

        self.env.invalidate_all()
        test_with_removed_as_admin = self.env['mail.activity'].with_user(self.user_admin).search([
            ('id', 'in', self.test_activities.ids),
            ('res_model', '=', self.test_lead_records._name),
        ])
        self.assertEqual(len(test_with_removed_as_admin), 3, 'With ACL check, activities linked to removed records are not kept is not assigned to the user')

        self.env.invalidate_all()
        self.assertFalse(
            self.test_activities_removed.with_user(self.user_admin).has_access('read'),
            'No access to an activity linked to someone and whose record has been removed '
            '(considered as no access to record); and should not crash (no MissingError)'
        )
        with self.assertRaises(exceptions.AccessError):  # should not raise a MissingError
            self.test_activities_removed.with_user(self.user_admin).read(['summary'])

        self.env.invalidate_all()
        test_with_removed = self.env['mail.activity'].search([
            ('id', 'in', self.test_activities.ids),
            ('res_model', '=', self.test_lead_records._name),
        ])
        self.assertEqual(len(test_with_removed), 4, 'Even with ACL check, activities linked to removed records are kept if assigned to the user (see odoo/odoo#112126)')

        # if not assigned -> should filter out
        self.env.invalidate_all()
        self.test_activities_removed.write({'user_id': self.user_admin.id})
        test_with_removed = self.env['mail.activity'].search([
            ('id', 'in', self.test_activities.ids),
            ('res_model', '=', self.test_lead_records._name),
        ])
        self.assertEqual(len(test_with_removed), 3, 'With ACL check, activities linked to removed records are not kept if assigned to the another user')
        self.test_activities_removed.write({'user_id': self.user_employee.id})

        # be sure activities on removed records do not crash when managed, and that
        # lost attachments are removed as well
        self.env.invalidate_all()
        lead_activities = self.test_lead_activities.with_user(self.user_employee)
        lead_act_attachments = self.lead_act_attachments.with_user(self.user_employee)
        self.assertEqual(len(lead_activities), 4, 'Simulate UI where activities are still displayed even if record removed')
        self.assertEqual(len(lead_act_attachments), 4, 'Simulate UI where activities are still displayed even if record removed')
        messages, _next_activities = lead_activities._action_done()
        self.assertEqual(len(messages), 3, 'Should have posted one message / live record')
        self.assertEqual(lead_activities.exists(), lead_activities - self.test_activities_removed, 'Mark done should unlink activities linked to removed records')
        self.assertEqual(lead_activities.exists().mapped('active'), [False] * 3)
        self.assertEqual(
            set(lead_act_attachments.exists().mapped('res_id')), set(messages.ids),
            'Mark done should clean up attachments linked to removed record, and linked other attachments to messages')
        self.assertEqual(
            set(lead_act_attachments.exists().mapped('res_model')), set(['mail.message'] * 2))

    @users("employee")
    def test_systray_activities_multi_company(self):
        """ Explicitly check MC support, as well as allowed_company_ids, that
        limits visible records in a given session, should impact systray activities. """
        self.user_employee.write({'company_ids': [(4, self.company_2.id)]})

        self.authenticate(self.user_employee.login, self.user_employee.login)
        with freeze_time(self.dt_reference):
            groups_data = self.make_jsonrpc_request("/mail/data", {"fetch_params": ["systray_get_activities"]}).get('Store', {}).get('activityGroups', [])

        for model_name, msg, (exp_total, exp_today, exp_planned, exp_overdue) in [
            ('mail.activity', 'Non accessible: deleted', (1, 1, 2, 0)),
            (self.test_record._name, 'Archiving removes activities', (1, 1, 1, 0)),
            (self.test_lead_records._name, 'Accessible (MC with all companies)', (1, 1, 2, 0)),
        ]:
            with self.subTest(model_name=model_name, msg=msg):
                group_values = next(values for values in groups_data if values['model'] == model_name)
                self.assertEqual(group_values['total_count'], exp_total)
                self.assertEqual(group_values['today_count'], exp_today)
                self.assertEqual(group_values['planned_count'], exp_planned)
                self.assertEqual(group_values['overdue_count'], exp_overdue)
                if model_name == 'mail.activity':  # for mail.activity, there is a key with activities we can check
                    self.assertEqual(sorted(group_values['activity_ids']), sorted((self.test_activities_removed + self.test_activities_free).ids))

        # when allowed companies restrict visible records, linked activities are
        # removed from systray, considering you have to log into the right company
        # to see them (change in 18+)
        with freeze_time(self.dt_reference):
            groups_data = self.make_jsonrpc_request("/mail/data", {
                "fetch_params": ["systray_get_activities"],
                "context": {"allowed_company_ids": self.company_admin.ids},
            }).get('Store', {}).get('activityGroups', [])

        for model_name, msg, (exp_total, exp_today, exp_planned, exp_overdue) in [
            ('mail.activity', 'Non accessible: deleted (MC ignored, stripped out like inaccessible records)', (1, 1, 2, 0)),
            (self.test_record._name, 'Archiving removes activities', (1, 1, 1, 0)),
            (self.test_lead_records._name, 'Accessible', (1, 1, 1, 0)),
        ]:
            with self.subTest(model_name=model_name, msg=msg):
                group_values = next(values for values in groups_data if values['model'] == model_name)
                self.assertEqual(group_values['total_count'], exp_total)
                self.assertEqual(group_values['today_count'], exp_today)
                self.assertEqual(group_values['planned_count'], exp_planned)
                self.assertEqual(group_values['overdue_count'], exp_overdue)
                if model_name == 'mail.activity':  # for mail.activity, there is a key with activities we can check
                    self.assertEqual(sorted(group_values['activity_ids']), sorted((self.test_activities_removed + self.test_activities_free).ids))

        # now not having accessible to company 2 records: tread like forbidden
        self.user_employee.write({'company_ids': [(3, self.company_2.id)]})
        with freeze_time(self.dt_reference):
            groups_data = self.make_jsonrpc_request("/mail/data", {
                "fetch_params": ["systray_get_activities"],
                "context": {"allowed_company_ids": self.company_admin.ids},
            }).get('Store', {}).get('activityGroups', [])

        for model_name, msg, (exp_total, exp_today, exp_planned, exp_overdue) in [
            ('mail.activity', 'Non accessible: deleted + company error managed like forbidden record', (1, 1, 3, 0)),
            (self.test_record._name, 'Archiving removes activities', (1, 1, 1, 0)),
            (self.test_lead_records._name, 'Accessible', (1, 1, 1, 0)),
        ]:
            with self.subTest(model_name=model_name, msg=msg):
                group_values = next(values for values in groups_data if values['model'] == model_name)
                self.assertEqual(group_values['total_count'], exp_total)
                self.assertEqual(group_values['today_count'], exp_today)
                self.assertEqual(group_values['planned_count'], exp_planned)
                self.assertEqual(group_values['overdue_count'], exp_overdue)
                if model_name == 'mail.activity':  # for mail.activity, there is a key with activities we can check
                    self.assertEqual(sorted(group_values['activity_ids']), sorted((self.test_activities_removed + self.test_activities_company_2 + self.test_activities_free).ids))


@tests.tagged('mail_activity')
@freeze_time("2024-01-01 09:00:00")
class TestActivitySystrayBusNotify(TestActivityCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_employee_2 = cls.user_employee.copy(default={'login': 'employee_2', 'email': 'user_employee_2@test.lan'})

        cls.activity_vals = [
            {
                'res_model_id': cls.env['ir.model']._get_id(cls.test_record._name),
                'res_id': cls.test_record.id,
                'date_deadline': dt,
                'user_id': cls.user_employee.id,
            } | extra
            for dt, extra in zip(
                (datetime(2023, 12, 31, 15, 0, 0), datetime(2023, 12, 31, 15, 0, 0), datetime(2024, 1, 1, 15, 0, 0), datetime(2024, 1, 2, 15, 0, 0)),
                ({'active': False}, {}, {}, {}),
            )
        ]

    def _systray_counter(self, user):
        """The number the systray badge shows on a reload, for `user`."""
        groups = self.env['res.users'].with_user(user)._get_activity_groups()
        return sum(group.get('total_count', 0) for group in groups)

    def _expect_employee_diff(self, count_diff):
        """One expected bus notification on the employee's channel."""
        partner = self.user_employee.partner_id
        return [
            ([(self.env.cr.dbname, partner._name, partner.id)], [{
                "type": "mail.activity/updated",
                "payload": {
                    "count_diff": count_diff,
                } | ({"activity_created": True} if count_diff > 0 else {"activity_deleted": True}),
            }])
        ]

    @users('employee')
    def test_notify_create_unlink_activities(self):
        """Creating and unlinking activities notifies the change in "to be done"
        count per user -- counted in the same unit as the badge it adjusts.

        ``activity_vals`` puts all four activities on ONE record, of which two
        are to-do. ``_get_activity_groups`` counts one unit per *record* holding
        at least one to-do activity, so the delta is 1, not 2: the counter used
        to be seeded in records and moved in activities, and a client that saw
        +2 here dropped back to 1 as soon as the systray was opened.
        """
        users = self.env.user + self.user_employee_2

        expected_create_notifs = [
            ([(self.env.cr.dbname, user.partner_id._name, user.partner_id.id)], [{
                "type": "mail.activity/updated",
                "payload": {
                    "activity_created": True,
                    "count_diff": 1,
                },
            }])
            for user in users
        ]
        expected_unlink_notifs = [
            ([(self.env.cr.dbname, user.partner_id._name, user.partner_id.id)], [{
                "type": "mail.activity/updated",
                "payload": {
                    "activity_deleted": True,
                    "count_diff": -1,
                },
            }])
            for user in users
        ]
        for (
            user,
            (expected_create_notif_channels, expected_create_notif_message_items),
            (expected_unlink_notif_channels, expected_unlink_notif_message_items),
        ) in zip(users, expected_create_notifs, expected_unlink_notifs):
            user_activity_vals = [vals | {'user_id': user.id} for vals in self.activity_vals]
            before = self._systray_counter(user)
            with self.assertBus(expected_create_notif_channels, expected_create_notif_message_items):
                activities = self.env['mail.activity'].create(user_activity_vals)
            # the invariant the payload exists to preserve: applying the delta to
            # the badge lands on the value a reload would compute
            self.assertEqual(self._systray_counter(user), before + 1)
            with self.assertBus(expected_unlink_notif_channels, expected_unlink_notif_message_items):
                activities.unlink()
            self.assertEqual(self._systray_counter(user), before)

    @users('employee')
    def test_notify_counts_records_not_activities(self):
        """Two activities on one record are one unit; on two records, two."""
        model_id = self.env['ir.model']._get_id(self.test_record._name)
        record_2 = self.env['mail.test.activity'].sudo().create({'name': 'second'})
        base = {
            'res_model_id': model_id,
            'date_deadline': datetime(2023, 12, 31, 15, 0, 0),
            'user_id': self.env.user.id,
        }
        channel = [(self.env.cr.dbname, self.env.user.partner_id._name, self.env.user.partner_id.id)]

        with self.assertBus(channel, [{
            "type": "mail.activity/updated",
            "payload": {"activity_created": True, "count_diff": 1},
        }]):
            same_record = self.env['mail.activity'].create([
                base | {'res_id': self.test_record.id},
                base | {'res_id': self.test_record.id},
            ])
        self.assertEqual(self._systray_counter(self.env.user), 1)

        # a third activity on the same record moves nothing: the record already counts
        self._reset_bus()
        third = self.env['mail.activity'].create(base | {'res_id': self.test_record.id})
        self.assertBusNotifications([], [])
        self.assertEqual(self._systray_counter(self.env.user), 1)

        # one on another record does move it
        self._reset_bus()
        with self.assertBus(channel, [{
            "type": "mail.activity/updated",
            "payload": {"activity_created": True, "count_diff": 1},
        }]):
            other_record = self.env['mail.activity'].create(base | {'res_id': record_2.id})
        self.assertEqual(self._systray_counter(self.env.user), 2)

        # removing one of three leaves the record counted -> no notification,
        # where a per-activity delta would have wrongly decremented the badge
        self._reset_bus()
        third.unlink()
        self.assertBusNotifications([], [])
        self.assertEqual(self._systray_counter(self.env.user), 2)

        (same_record + other_record).unlink()
        self.assertEqual(self._systray_counter(self.env.user), 0)

    @users('employee')
    def test_notify_counts_in_the_assignee_timezone(self):
        """The delta is decided on the assignee's own today, like ``state``.

        Frozen at 2024-01-01 09:00 UTC. For an assignee at UTC-11 it is still
        2023-12-31 there, so an activity due on the 1st is *planned* for them and
        the badge must not count it. Deciding on the server's date instead --
        ``date_deadline <= fields.Date.today()``, which is what create, write and
        unlink used to do -- would have pushed +1 against a badge that computes 0
        on reload, because the badge is built from ``state`` and ``state`` has
        always answered in the assignee's timezone.
        """
        self.env.user.tz = 'Pacific/Midway'  # UTC-11
        Activity = self.env['mail.activity']
        self.assertEqual(Activity._compute_today_for_tz(self.env.user.tz), date(2023, 12, 31))
        self.assertEqual(Activity._compute_today_for_tz(False), date(2024, 1, 1))
        vals = {
            'res_model_id': self.env['ir.model']._get_id(self.test_record._name),
            'res_id': self.test_record.id,
            'user_id': self.env.user.id,
        }

        self._reset_bus()
        planned = Activity.create(vals | {'date_deadline': datetime(2024, 1, 1, 15, 0, 0)})
        self.assertEqual(planned.state, 'planned', "today on the server, tomorrow for the assignee")
        self.assertBusNotifications([], [])
        self.assertEqual(self._systray_counter(self.env.user), 0)

        # their own today does count
        channel = [(self.env.cr.dbname, self.env.user.partner_id._name, self.env.user.partner_id.id)]
        with self.assertBus(channel, [{
            "type": "mail.activity/updated",
            "payload": {"activity_created": True, "count_diff": 1},
        }]):
            due = Activity.create(vals | {'date_deadline': datetime(2023, 12, 31, 15, 0, 0)})
        self.assertEqual(due.state, 'today')
        self.assertEqual(self._systray_counter(self.env.user), 1)

    @users('employee')
    def test_notify_update_activities(self):
        write_vals_all = [
            # added to counter for employee 2, removed from counter for current employee
            {'user_id': self.user_employee_2.id},
            {'user_id': self.user_employee_2.id, 'date_deadline': datetime(2023, 12, 31, 15, 0, 0), 'active': True},
            # just notify
            {'date_deadline': datetime(2024, 1, 2, 15, 0, 0)},  # everything is in the future -> all removed from counter
            {'date_deadline': datetime(2023, 12, 31, 15, 0, 0)},  # everything is in the past -> the one from the future is added
            {'active': False},  # everything is archived -> all removed from counter
            {'active': True},  # the archived one is unarchived -> added to counter
            {},  # no "to be done" count change -> no notif
            [{'date_deadline': datetime(2024, 1, 2, 15, 0, 0), 'active': True}, {}, {}, {}],
        ]

        # All four activities sit on ONE record, so the counter moves by at most
        # one unit per user: what changes is whether that record still carries a
        # to-do activity, not how many it carries.
        expected_notifs = [
            # transfer to the second employee: the record leaves one counter and
            # joins the other
            [
                ([(self.env.cr.dbname, user.partner_id._name, user.partner_id.id)], [{
                    "type": "mail.activity/updated",
                    "payload": {
                        "count_diff": count_diff,
                    } | ({"activity_created": True} if count_diff > 0 else {"activity_deleted": True}),
                }])
                for user, count_diff
                in zip(self.user_employee + self.user_employee_2, [-1, 1])
            ],
            # same transfer, also pulling every deadline into the past: still one
            # record either side
            [
                ([(self.env.cr.dbname, user.partner_id._name, user.partner_id.id)], [{
                    "type": "mail.activity/updated",
                    "payload": {
                        "count_diff": count_diff,
                    } | ({"activity_created": True} if count_diff > 0 else {"activity_deleted": True}),
                }])
                for user, count_diff
                in zip(self.user_employee + self.user_employee_2, [-1, 1])
            ],
        ] + [
            # every deadline in the future -> the record stops counting
            self._expect_employee_diff(-1),
            # every deadline in the past: the record already counted (the active
            # past one, and today's) and still does -> nothing to say
            [([], [])],
            # everything archived -> the record stops counting
            self._expect_employee_diff(-1),
            # unarchiving adds a third to-do activity to a record that already
            # counts -> nothing to say
            [([], [])],
            [([], [])],  # no change -> no notif
            [([], [])],  # no change in "todo" count -> no notif
        ]
        for write_vals, expected_notif_vals in zip(write_vals_all, expected_notifs):
            with self.subTest(vals=write_vals):
                _past_archived, _past_active, _today, _tomorrow = activities = self.env['mail.activity'].create(self.activity_vals)
                self._reset_bus()
                if isinstance(write_vals, list):
                    for activity, vals in zip(activities, write_vals):
                        activity.write(vals)
                else:
                    activities.write(write_vals)
                for (notif_channels, notif_messages) in expected_notif_vals:
                    self.assertBusNotifications(notif_channels, notif_messages)
                activities.unlink()


@tests.tagged('mail_activity')
class TestActivityViewHelpers(TestActivityCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.type_todo = cls.env.ref('test_mail.mail_act_test_todo')
        cls.type_call = cls.env.ref('test_mail.mail_act_test_call')
        cls.type_upload = cls.env.ref('test_mail.mail_act_test_upload_document')

        cls.user_employee_2 = mail_new_test_user(
            cls.env,
            name='Employee2',
            login='employee2',
        )
        cls.attachment_1, cls.attachment_2 = cls.env['ir.attachment'].create([{
            'name': f"Uploaded doc_{idx + 1}",
            'raw': b'bar',
            'res_model': cls.test_record_2._name,
            'res_id': cls.test_record_2.id,
        } for idx in range(2)])
        cls.user_employee.tz = cls.user_admin.tz

    @freeze_time("2023-10-18 06:00:00")
    def test_get_activity_data(self):
        get_activity_data = self.env['mail.activity'].get_activity_data

        with self.with_user('employee'):
            # Setup activities: 3 for the first record, 2 "done" and 2 ongoing for the second
            test_record, test_record_2 = self.env['mail.test.activity'].browse(
                (self.test_record + self.test_record_2).ids
            )
            now_utc = datetime.now(UTC)
            now_user = now_utc.astimezone(timezone(self.env.user.tz or 'UTC'))
            today_user = now_user.date()

            for days, user_id in ((-1, self.user_employee_2), (0, self.user_employee), (1, self.user_admin)):
                test_record.activity_schedule(
                    'test_mail.mail_act_test_upload_document',
                    today_user + relativedelta(days=days),
                    user_id=user_id.id)
            for days, user_id in ((-2, self.user_admin), (0, self.user_employee), (2, self.user_employee_2),
                                  (3, self.user_admin), (4, self.env['res.users'])):
                test_record_2.activity_schedule(
                    'test_mail.mail_act_test_upload_document',
                    today_user + relativedelta(days=days),
                    user_id=user_id.id)
            record_activities = test_record.activity_ids
            record_2_activities = test_record_2.activity_ids
            record_2_activities[0].action_feedback(feedback='Done', attachment_ids=self.attachment_1.ids)
            record_2_activities[1].action_feedback(feedback='Done', attachment_ids=self.attachment_2.ids)

            # Check get activity data
            activity_data = get_activity_data('mail.test.activity', None, fetch_done=True)
            self.assertEqual(activity_data['activity_res_ids'], [test_record.id, test_record_2.id])
            self.assertDictEqual(
                next((t for t in activity_data['activity_types'] if t['id'] == self.type_upload.id), {}),
                {
                    'id': self.type_upload.id,
                    'name': 'Document',
                    'template_ids': [],
                })

            grouped = activity_data['grouped_activities'][test_record.id][self.type_upload.id]
            grouped['ids'] = set(grouped['ids'])  # ids order doesn't matter
            self.assertDictEqual(grouped, {
                'state': 'overdue',
                'count_by_state': {'overdue': 1, 'planned': 1, 'today': 1},
                'ids': set(record_activities.ids),
                'reporting_date': record_activities[0].date_deadline,
                'user_assigned_ids': record_activities.user_id.ids,
                'summaries': [act.summary for act in record_activities],
            })

            grouped = activity_data['grouped_activities'][test_record_2.id][self.type_upload.id]
            grouped['ids'] = set(grouped['ids'])
            self.assertDictEqual(grouped, {
                'state': 'planned',
                'count_by_state': {'done': 2, 'planned': 3},  # free user is planned
                'ids': set(record_2_activities.ids),
                'reporting_date': record_2_activities[2].date_deadline,
                'user_assigned_ids': record_2_activities[2:].user_id.ids,
                'attachments_info': {
                    'count': 2, 'most_recent_id': self.attachment_2.id, 'most_recent_name': 'Uploaded doc_2'},
                'summaries': [act.summary for act in record_2_activities],
            })

            # Mark all first record activities as "done" and check activity data
            record_activities.action_feedback(feedback='Done', attachment_ids=self.attachment_1.ids)
            self.assertEqual(record_activities[2].date_done, date.today())  # Thanks to freeze_time
            activity_data = get_activity_data('mail.test.activity', None, fetch_done=True)
            grouped = activity_data['grouped_activities'][test_record.id][self.type_upload.id]
            grouped['ids'] = set(grouped['ids'])
            self.assertDictEqual(grouped, {
                'state': 'done',
                'count_by_state': {'done': 3},
                'ids': set(record_activities.ids),
                'reporting_date': record_activities[2].date_done,
                'user_assigned_ids': [],
                'attachments_info': {
                    'count': 1,  # 1 instead of 3 because all attachments are the same one
                    'most_recent_id': self.attachment_1.id,
                    'most_recent_name': self.attachment_1.name,
                },
                'summaries': [act.summary for act in record_activities],
            })
            self.assertEqual(activity_data['activity_res_ids'], [test_record_2.id, test_record.id])

            # Check filters (domain, pagination and fetch_done)
            self.assertEqual(
                get_activity_data('mail.test.activity', domain=[('id', 'in', test_record.ids)],
                                  fetch_done=True)['activity_res_ids'],
                [test_record.id])
            self.assertEqual(get_activity_data('mail.test.activity', None, fetch_done=False)['activity_res_ids'],
                             [test_record_2.id])
            # Note that the records are ordered by ids not by deadline (so we get the "wrong" order)
            self.assertEqual(
                get_activity_data('mail.test.activity', None, offset=1, fetch_done=True)['activity_res_ids'],
                [test_record_2.id])
            self.assertEqual(
                get_activity_data('mail.test.activity', None, limit=1, fetch_done=True)['activity_res_ids'],
                [test_record.id])

            # Unarchiving activities should restore the activity
            record_activities.action_unarchive()
            self.assertFalse(any(act.date_done for act in record_activities))
            self.assertTrue(all(act.date_deadline for act in record_activities))
            activity_data = get_activity_data('mail.test.activity', None, fetch_done=True)
            grouped = activity_data['grouped_activities'][test_record.id][self.type_upload.id]
            self.assertEqual(grouped['state'], 'overdue')
            self.assertEqual(grouped['count_by_state'], {'overdue': 1, 'planned': 1, 'today': 1})
            self.assertEqual(grouped['reporting_date'], record_activities[0].date_deadline)
            self.assertEqual(activity_data['activity_res_ids'], [test_record.id, test_record_2.id])
            grouped['ids'] = set(grouped['ids'])
            self.assertDictEqual(grouped, {
                'state': 'overdue',
                'count_by_state': {'overdue': 1, 'planned': 1, 'today': 1},
                'ids': set(record_activities.ids),
                'reporting_date': record_activities[0].date_deadline,
                'user_assigned_ids': record_activities.user_id.ids,
                'summaries': [act.summary for act in record_activities],
            })


@tests.tagged('post_install', '-at_install')
class TestTours(HttpCase):

    def test_activity_view_data_with_offset(self):
        self.patch(MailTestActivity, '_order', 'date desc, id desc')
        MailTestActivityModel = self.env['mail.test.activity']
        MailTestActivityCtx = MailTestActivityModel.with_context({"lang": "en_US"})
        MailTestActivityModel.create({
            'date': '2021-05-02',
            'name': "Task 1",
        }).activity_schedule(
            'test_mail.mail_act_test_todo',
            summary="Activity 1",
            date_deadline=fields.Date.context_today(MailTestActivityCtx) - timedelta(days=7),
            user_id=self.env.uid,
        )
        MailTestActivityModel.create({
            'date': '2021-05-16',
            'name': "Task 1 without activity",
        })
        MailTestActivityModel.create({
            'date': '2021-05-09',
            'name': "Task 2",
        }).activity_schedule(
            'test_mail.mail_act_test_todo',
            summary="Activity 2",
            date_deadline=fields.Date.context_today(MailTestActivityCtx),
            user_id=self.env.uid,
        )
        MailTestActivityModel.create({
            'date': '2021-05-16',
            'name': "Task 3",
        }).activity_schedule(
            'test_mail.mail_act_test_todo',
            summary="Activity 3",
            date_deadline=fields.Date.context_today(MailTestActivityCtx) + timedelta(days=7),
            user_id=self.env.uid,
        )
        MailTestActivityModel.create({
            'date': '2021-05-16',
            'name': "Task 2 without activity",
        })

        self.env["ir.ui.view"].create({
            "name": "Test Activity View",
            "model": "mail.test.activity",
            "type": 'activity',
            "arch": """
                <activity string="OrderedMailTestActivity">
                    <templates>
                        <div t-name="activity-box">
                            <field name="name"/>
                        </div>
                    </templates>
                </activity>
            """,
        })
        self.start_tour(
            "/odoo?debug=1",
            "mail_activity_view",
            login="admin",
        )


@tests.tagged('post_install', '-at_install')
class TestActivityResName(ActivityScheduleCase):
    """``res_name`` resolves the linked document without probing for it.

    The probe (``exists()``) used to run on every read -- including every
    notification template that renders ``res_name`` -- to guard a state that
    only arises when a record is cascade-deleted in the database, skipping the
    unlink override that would have removed its activities.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env['mail.test.activity'].create({'name': 'Doc'})
        cls.activity = cls.env['mail.activity'].create({
            'activity_type_id': cls.env.ref('mail.mail_activity_data_todo').id,
            'res_id': cls.record.id,
            'res_model_id': cls.env.ref('test_mail.model_mail_test_activity').id,
            'summary': 'Act',
        })

    def _recompute_res_name(self):
        self.env.invalidate_all()
        self.env['mail.activity'].browse(self.activity.id)._compute_res_name()
        return self.activity.res_name

    def test_res_name_follows_the_document(self):
        self.assertEqual(self._recompute_res_name(), 'Doc')
        self.record.name = 'Renamed'
        self.assertEqual(self._recompute_res_name(), 'Renamed')

    def test_res_name_costs_one_query_for_the_document(self):
        """The happy path reads the document; it must not also probe for it."""
        self.env.invalidate_all()
        activity = self.env['mail.activity'].browse(self.activity.id)
        with self.assertQueryCount(__system__=2):
            activity._compute_res_name()

    def test_cascade_deleted_document_leaves_a_blank_name(self):
        """The row is removed behind the ORM's back, as a DB-level cascade does."""
        self.env.cr.execute('DELETE FROM mail_test_activity WHERE id = %s', (self.record.id,))
        self.assertFalse(self._recompute_res_name())

    def test_one_missing_document_does_not_blank_its_siblings(self):
        survivor = self.env['mail.test.activity'].create({'name': 'Survivor'})
        sibling = self.env['mail.activity'].create({
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'res_id': survivor.id,
            'res_model_id': self.env.ref('test_mail.model_mail_test_activity').id,
            'summary': 'Act 2',
        })
        self.env.cr.execute('DELETE FROM mail_test_activity WHERE id = %s', (self.record.id,))
        self.env.invalidate_all()
        (self.activity + sibling)._compute_res_name()
        self.assertFalse(self.activity.res_name)
        self.assertEqual(sibling.res_name, 'Survivor')


@tests.tagged('mail_activity')
class TestActivityAccessAndState(ActivityScheduleCase):
    """Access, cache and idempotence properties of mail.activity."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env['mail.test.activity'].create({'name': 'Doc'})
        cls.model_id = cls.env['ir.model']._get_id('mail.test.activity')
        cls.other_user = mail_new_test_user(
            cls.env, name='Colleague', login='colleague', groups='base.group_user',
        )

    def _new_activity(self, **vals):
        return self.env['mail.activity'].create({
            'res_model_id': self.model_id,
            'res_id': self.record.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            **vals,
        })

    def test_can_write_is_per_reader(self):
        """``can_write`` answers for the reader, whichever identity read first.

        It is a pure function of ``env.uid`` and ships to the client in
        ``_to_store_defaults``, where it decides which buttons the chatter draws.
        Without ``@api.depends_context("uid")`` its cache key was ``()``, so one
        slot was shared by every environment in the transaction and a ``sudo()``
        read anywhere earlier in the request handed its own verdict to the user.
        """
        activity = self._new_activity(user_id=self.user_admin.id)
        self.env.flush_all()
        self.assertIn(
            'uid',
            self.env.registry.field_depends_context[
                self.env['mail.activity']._fields['can_write']
            ],
        )

        as_employee = activity.with_user(self.user_employee)
        self.env.invalidate_all()
        employee_verdict = as_employee.can_write
        self.env.invalidate_all()
        sudo_verdict = activity.sudo().can_write
        self.assertTrue(sudo_verdict, "the superuser may always write")

        # whichever order they are read in, each identity gets its own answer
        self.env.invalidate_all()
        self.assertEqual(activity.sudo().can_write, sudo_verdict)
        self.assertEqual(as_employee.can_write, employee_verdict)
        self.env.invalidate_all()
        self.assertEqual(as_employee.can_write, employee_verdict)
        self.assertEqual(activity.sudo().can_write, sudo_verdict)

    def test_can_write_reaches_the_client_per_reader(self):
        """The same, through the RPC the chatter popover actually calls."""
        activity = self._new_activity(user_id=self.user_admin.id)
        self.env.flush_all()
        as_employee = activity.with_user(self.user_employee)

        self.env.invalidate_all()
        clean = as_employee.activity_format()['mail.activity'][0]['can_write']
        self.env.invalidate_all()
        activity.sudo().can_write  # any sudo() touch earlier in the request
        polluted = as_employee.activity_format()['mail.activity'][0]['can_write']
        self.assertEqual(clean, polluted)

    def test_schedule_for_another_user_on_a_read_post_document(self):
        """A read-only document that opts into ``_mail_post_access = 'read'``
        accepts an activity scheduled for somebody else.

        ``_check_access`` states create access as "``mail_post_access`` on the
        related document", and posting a message on such a record works. The
        follower side effect used the public ``message_subscribe``, which
        re-checks *write* for any partner but the caller's own, so a user could
        schedule for themselves and not for a colleague -- failing with an
        AccessError naming the document.
        """
        record = self.env['mail.test.container'].create({'name': 'Read-post doc'})
        self.assertEqual(record._mail_post_access, 'read')
        model_id = self.env['ir.model']._get_id(record._name)
        as_employee = record.with_user(self.user_employee)
        self.assertTrue(as_employee.has_access('read'))

        # the policy the model states, exercised directly
        as_employee.message_post(body='hello', message_type='comment',
                                 subtype_xmlid='mail.mt_comment')

        with self.with_user('employee'):
            Activity = self.env['mail.activity']
            for assignee, label in (
                (self.env.user, 'themselves'),
                (self.other_user, 'a colleague'),
            ):
                with self.subTest(assignee=label):
                    activity = Activity.create({
                        'res_model_id': model_id,
                        'res_id': record.id,
                        'user_id': assignee.id,
                        'summary': f'for {label}',
                    })
                    self.assertEqual(activity.user_id, assignee)
            # and reassigning one is the same operation from the other side
            mine = Activity.search([('res_id', '=', record.id),
                                    ('user_id', '=', self.env.uid)], limit=1)
            mine.write({'user_id': self.other_user.id})
            self.assertEqual(mine.user_id, self.other_user)

    def test_action_feedback_is_not_replayed(self):
        """Marking a done activity done again neither posts nor rewrites.

        ``action_done`` filtered on ``active``; ``action_feedback`` -- the public
        API, and the one the web client calls without disabling its button while
        the RPC is in flight -- did not, so a double click posted a second "done"
        message and overwrote the feedback.
        """
        activity = self._new_activity(user_id=self.env.uid, summary='Once')
        self.env.flush_all()
        activity.action_feedback(feedback='first')
        self.env.flush_all()
        messages = self.record.message_ids
        date_done = activity.date_done

        activity.action_feedback(feedback='second')
        self.env.flush_all()
        self.assertEqual(self.record.message_ids, messages, "no second done message")
        self.assertEqual(activity.feedback, 'first', "the first feedback stands")
        self.assertEqual(activity.date_done, date_done)

    def test_feedback_and_archive_are_one_write(self):
        """Marking done writes once, not once to archive and once for feedback."""
        activities = self.env['mail.activity'].create([{
            'res_model_id': self.model_id,
            'res_id': self.record.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'user_id': self.env.uid,
            'summary': f'act {idx}',
        } for idx in range(3)])
        self.env.flush_all()

        writes = []
        origin = type(self.env['mail.activity']).write

        def counting_write(records, vals):
            writes.append(sorted(vals))
            return origin(records, vals)

        with patch.object(type(self.env['mail.activity']), 'write', counting_write):
            activities.action_feedback(feedback='done')
        self.assertEqual(writes, [['active', 'feedback']])

    def test_state_survives_a_missing_deadline(self):
        """``state`` is assigned even with no deadline, as onchange can produce."""
        virtual = self.env['mail.activity'].new({
            'res_model_id': self.model_id,
            'res_id': self.record.id,
            'user_id': self.env.uid,
        })
        virtual.date_deadline = False
        self.assertFalse(virtual.state)

    def test_date_done_is_the_assignee_date(self):
        """``date_done`` records the assignee's own day, not the server's UTC one."""
        user_ahead = mail_new_test_user(
            self.env, name='Ahead', login='ahead', groups='base.group_user',
            tz='Pacific/Kiritimati',  # UTC+14
        )
        activity = self._new_activity(user_id=user_ahead.id)
        self.env.flush_all()
        with freeze_time('2024-01-01 15:00:00'):  # 2024-01-02 05:00 for the assignee
            activity.action_archive()
            self.env.flush_all()
            self.assertEqual(activity.date_done, date(2024, 1, 2))

    def test_action_cancel_unlinks_once(self):
        activities = self.env['mail.activity'].create([{
            'res_model_id': self.model_id,
            'res_id': self.record.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'user_id': self.env.uid,
            'summary': f'act {idx}',
        } for idx in range(5)])
        self.env.flush_all()

        calls = []
        origin = type(self.env['mail.activity']).unlink

        def counting_unlink(records):
            calls.append(len(records))
            return origin(records)

        with patch.object(type(self.env['mail.activity']), 'unlink', counting_unlink):
            activities.action_cancel()
        # empty calls come from cascades; what matters is that the five records
        # are removed by one call and not one call each
        self.assertEqual([count for count in calls if count], [5])
        self.assertFalse(activities.exists())

    def test_activity_on_a_model_without_a_chatter(self):
        """A model with no followers still carries activities, it just gets no
        chatter side effect.

        ``res_model_id`` is a plain m2o to ir.model -- only the activity *type*
        restricts itself to ``is_mail_thread`` -- so an activity may sit on a
        model that has neither ``_message_subscribe`` nor
        ``message_post_with_source``. Scheduling one for somebody else used to
        die on the first and marking it done would have died on the second.
        """
        target = self.env["res.users"]
        self.assertFalse(hasattr(target, "_message_subscribe"),
                         "the vehicle for this test must really lack a chatter")
        activity = self.env["mail.activity"].create({
            "res_model_id": self.env["ir.model"]._get_id(target._name),
            "res_id": self.user_admin.id,
            "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
            "user_id": self.other_user.id,
            "summary": "no chatter here",
        })
        self.env.flush_all()
        self.assertEqual(activity.user_id, self.other_user)

        # reassignment goes through the same side effect
        activity.write({"user_id": self.user_employee.id})
        self.assertEqual(activity.user_id, self.user_employee)

        # and so does notifying, and marking done
        activity.action_notify()
        messages, _next = activity._action_done(feedback="done")
        self.assertFalse(messages, "nowhere to post it")
        self.assertFalse(activity.active)
        self.assertEqual(activity.feedback, "done")

    def test_feedback_schedule_next_wants_one_activity(self):
        activities = self.env['mail.activity'].create([{
            'res_model_id': self.model_id,
            'res_id': self.record.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'user_id': self.env.uid,
            'summary': f'act {idx}',
        } for idx in range(2)])
        with self.assertRaises(ValueError):
            activities.action_feedback_schedule_next()


@tests.tagged('mail_activity')
class TestActivitySearchPaging(ActivityScheduleCase):
    """``_search`` filters access in Python; pagination must survive that."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env['mail.test.activity'].create({'name': 'Doc'})
        cls.activities = cls.env['mail.activity'].create([{
            'res_model_id': cls.env['ir.model']._get_id('mail.test.activity'),
            'res_id': cls.record.id,
            'activity_type_id': cls.env.ref('mail.mail_activity_data_todo').id,
            'user_id': cls.user_employee.id,
            'summary': f'act {idx:02d}',
            'date_deadline': date(2024, 1, 1) + timedelta(days=idx),
        } for idx in range(25)])

    def test_pages_are_full_and_contiguous(self):
        Activity = self.env['mail.activity'].with_user(self.user_employee)
        domain = [('id', 'in', self.activities.ids)]
        order = 'date_deadline ASC, id ASC'
        everything = Activity.search(domain, order=order)
        self.assertEqual(len(everything), 25)

        for size in (1, 4, 10):
            with self.subTest(page_size=size):
                paged = self.env['mail.activity']
                for offset in range(0, 25, size):
                    page = Activity.search(domain, offset=offset, limit=size, order=order)
                    self.assertLessEqual(len(page), size)
                    paged |= page
                    self.assertEqual(
                        page.ids, everything[offset:offset + size].ids,
                        "each page holds exactly the slice of the full result",
                    )
                self.assertEqual(paged.ids, everything.ids)

    def test_falsy_limit_means_no_limit(self):
        """``limit=0`` is "no limit" everywhere in the ORM (Query emits the
        clause only ``if self.limit``), so it must not read as an empty page."""
        Activity = self.env['mail.activity'].with_user(self.user_employee)
        domain = [('id', 'in', self.activities.ids)]
        self.assertEqual(len(Activity.search(domain, limit=0)), 25)
        self.assertEqual(Activity.search_count(domain), 25)
        self.assertEqual(len(Activity.sudo().search(domain, limit=0)), 25,
                         "and the superuser branch agrees")

    def test_inaccessible_activities_do_not_shorten_a_page(self):
        """A page is filled with accessible rows, not truncated by hidden ones."""
        # Activities attached to no document are readable by their assignee
        # alone, so these are invisible to the employee whatever they can read.
        hidden = self.env['mail.activity'].create([{
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'user_id': self.user_admin.id,
            'summary': f'hidden {idx}',
            'date_deadline': date(2024, 1, 1),
        } for idx in range(10)])
        self.env.flush_all()

        Activity = self.env['mail.activity'].with_user(self.user_employee)
        domain = [('id', 'in', (self.activities + hidden).ids)]
        visible = Activity.search(domain)
        self.assertFalse(visible & hidden.with_user(self.user_employee),
                         "the employee is not the assignee of the hidden ones")
        page = Activity.search(domain, limit=5, order='date_deadline ASC, id ASC')
        self.assertEqual(len(page), 5, "the page is full despite the hidden rows")
        self.assertEqual(page.ids, visible[:5].ids)


@tests.tagged('mail_activity')
class TestActivityGarbageCollect(ActivityScheduleCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env['mail.test.activity'].create({'name': 'Doc'})
        cls.model_id = cls.env['ir.model']._get_id('mail.test.activity')

    def setUp(self):
        super().setUp()
        # ir.config_parameter reads go through an ormcache the transaction
        # rollback does not clear, so state both knobs explicitly per test.
        for parameter in ('delete_overdue_years', 'delete_done_years'):
            self.env['ir.config_parameter'].sudo().set_param(
                f'mail.activity.gc.{parameter}', '0')

    def _activity(self, deadline, done=False):
        activity = self.env['mail.activity'].create({
            'res_model_id': self.model_id,
            'res_id': self.record.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'user_id': self.env.uid,
            'date_deadline': deadline,
        })
        if done:
            activity.action_archive()
        return activity

    def test_gc_is_off_by_default_and_reports_the_contract(self):
        Activity = self.env['mail.activity']
        old = self._activity(date(2000, 1, 1))
        self.assertEqual(Activity._gc_delete_old_overdue_activities(), (0, False))
        self.assertEqual(Activity._gc_delete_old_done_activities(), (0, False))
        self.assertTrue(old.exists())

    def test_gc_overdue_reports_removed_and_more(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'mail.activity.gc.delete_overdue_years', '5')
        old = self._activity(date(2000, 1, 1))
        recent = self._activity(date.today())
        removed, more = self.env['mail.activity']._gc_delete_old_overdue_activities()
        self.assertEqual((removed, more), (1, False))
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_gc_done_activities_are_collected_too(self):
        """Completed activities are archived, so the overdue routine -- which
        searches with the default ``active_test`` -- never saw them and nothing
        aged them out."""
        Activity = self.env['mail.activity']
        with freeze_time('2000-01-01'):
            done = self._activity(date(2000, 1, 1), done=True)
            self.env.flush_all()
        self.assertFalse(done.active)
        self.assertEqual(done.date_done, date(2000, 1, 1))

        self.env['ir.config_parameter'].sudo().set_param(
            'mail.activity.gc.delete_overdue_years', '5')
        Activity._gc_delete_old_overdue_activities()
        self.assertTrue(done.exists(), "the overdue routine does not see archived rows")

        self.env['ir.config_parameter'].sudo().set_param(
            'mail.activity.gc.delete_done_years', '5')
        removed, more = Activity._gc_delete_old_done_activities()
        self.assertEqual((removed, more), (1, False))
        self.assertFalse(done.exists())

    def test_gc_refuses_a_negative_retention(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'mail.activity.gc.delete_overdue_years', '-1')
        old = self._activity(date(2000, 1, 1))
        with self.assertLogs('odoo.addons.mail.models.mail_activity', 'WARNING'):
            self.assertEqual(
                self.env['mail.activity']._gc_delete_old_overdue_activities(), (0, False))
        self.assertTrue(old.exists())


@tests.tagged('mail_activity')
class TestActivityStrandedModel(ActivityScheduleCase):
    """An activity whose ``res_model`` names a model the registry does not have.

    ``res_model_id`` is a plain m2o to ``ir.model``, and an addon installed in
    the database but absent from ``addons_path`` leaves exactly that: the
    ``ir.model`` row and the stored ``res_model`` string survive, the model does
    not. Reproduced end to end by installing ``knowledge`` and re-booting
    without ``enterprise/`` on the path; ``UPDATE`` is the cheap stand-in.

    Every reader must carry such an activity like a document-less one. Before,
    each site below raised a bare ``KeyError`` -- and ``_search`` is on the read
    path of every user who is not the assignee, so one row took the whole list
    down.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env['mail.test.activity'].create({'name': 'Doc'})
        cls.other_user = mail_new_test_user(
            cls.env, login='stranded_reader', groups='base.group_user')
        cls.activity = cls.env['mail.activity'].create({
            'activity_type_id': cls.env.ref('mail.mail_activity_data_todo').id,
            'res_id': cls.record.id,
            'res_model_id': cls.env.ref('test_mail.model_mail_test_activity').id,
            'user_id': cls.user_employee.id,
            'summary': 'Act',
        })

    def _strand(self):
        """Point the activity at a model no registry entry answers for."""
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE mail_activity SET res_model = %s WHERE id = %s",
            ('gone.module.model', self.activity.id))
        self.env.invalidate_all()
        self.assertNotIn('gone.module.model', self.env)

    def test_search_survives_for_a_reader_who_is_not_the_assignee(self):
        self._strand()
        Activity = self.env['mail.activity'].with_user(self.other_user)
        self.assertNotIn(self.activity.id, Activity.search([]).ids)
        self.assertFalse(Activity.browse(self.activity.id).has_access('read'))
        Activity.search_count([])

    def test_the_assignee_still_sees_it(self):
        """It stays theirs: only the document half is unreachable."""
        self._strand()
        Activity = self.env['mail.activity'].with_user(self.user_employee)
        self.assertIn(self.activity.id, Activity.search([]).ids)
        self.assertTrue(Activity.browse(self.activity.id).has_access('read'))

    def test_the_systray_still_loads_for_the_assignee(self):
        self._strand()
        groups = self.env['res.users'].with_user(self.user_employee)._get_activity_groups()
        models = {group['model'] for group in groups}
        self.assertIn('mail.activity', models,
                      'a stranded activity falls into the "Other activities" bucket')

    def test_action_open_document_falls_back(self):
        self._strand()
        action = self.env['mail.activity'].with_user(
            self.user_employee).browse(self.activity.id).action_open_document()
        self.assertEqual(action['res_model'], 'mail.activity')
        self.assertEqual(action['res_id'], self.activity.id)

    def test_the_chatter_side_effects_skip_it(self):
        self._strand()
        activity = self.env['mail.activity'].browse(self.activity.id)
        self.assertFalse(activity._document_backed())
        self.assertFalse(activity._thread_backed())
        self.assertFalse(activity._filtered_postable())
        activity.action_notify()
        self.assertFalse(activity.action_feedback())

    def test_it_can_still_be_written_and_unlinked(self):
        self._strand()
        activity = self.env['mail.activity'].with_user(self.user_employee).browse(
            self.activity.id)
        activity.write({'summary': 'Renamed'})
        activity.unlink()
        self.assertFalse(activity.exists())


@tests.tagged('mail_activity')
class TestActivityOnAnActivity(TestActivityCommon):
    """``_todo_key`` spells two shapes the same way, and the decode must too.

    A document-less activity is keyed ``('mail.activity', its own id)``; an
    activity filed *against* a ``mail.activity`` record is keyed
    ``('mail.activity', that record's id)``. Both name the same record and both
    must count once -- which is what ``_get_activity_groups`` does. But
    ``_todo_keys_elsewhere`` used to decode the key only as the document-less
    shape, so it never saw the other activity holding it, and the badge was
    decremented twice for one record going quiet.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.activity_model_id = cls.env['ir.model']._get_id('mail.activity')

    def _systray_counter(self):
        groups = self.env['res.users'].with_user(
            self.user_employee)._get_activity_groups()
        return sum(group.get('total_count', 0) for group in groups)

    def _due_activity(self, **vals):
        return self.env['mail.activity'].create({
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'date_deadline': fields.Date.context_today(
                self.env['mail.activity'].with_user(self.user_employee)),
            'user_id': self.user_employee.id,
            **vals,
        })

    def _bus_total(self, func):
        """Sum of the count_diff the bus carried while `func` ran."""
        seen = []
        origin = type(self.env['res.users'])._bus_send

        def spy(records, notification_type, message, /, **kwargs):
            if notification_type == 'mail.activity/updated':
                seen.append(message.get('count_diff', 0))
            return origin(records, notification_type, message, **kwargs)

        with patch.object(type(self.env['res.users']), '_bus_send', spy):
            func()
            self.env.flush_all()
        return sum(seen)

    def test_the_bus_delta_tracks_the_badge_through_a_nested_activity(self):
        free = self._due_activity(summary='Free')
        self.env.flush_all()
        nested = self._due_activity(
            summary='On the free one',
            res_model_id=self.activity_model_id,
            res_id=free.id,
        )
        self.env.flush_all()

        before = self._systray_counter()
        delta = self._bus_total(free.unlink)
        after = self._systray_counter()
        self.assertEqual(
            delta, after - before,
            'the bus must move the badge by exactly what a reload would show')
        self.assertFalse(nested.exists(),
                         'deleting the record cascades to activities filed on it')

    def test_two_activities_on_one_record_count_once(self):
        free = self._due_activity(summary='Free')
        self.env.flush_all()
        before = self._systray_counter()
        delta = self._bus_total(lambda: self._due_activity(
            summary='On the free one',
            res_model_id=self.activity_model_id,
            res_id=free.id,
        ))
        self.assertEqual(self._systray_counter(), before,
                         'both activities make the same record busy')
        self.assertEqual(delta, 0)


@tests.tagged('mail_activity')
class TestActivityNotifyCost(TestActivityCommon):
    """``action_notify`` must not work for activities it will not notify.

    Every query-count pin in this file exercises a single activity, so a per
    record cost in a batch path is invisible to all of them; these assert the
    shape at N > 1.
    """

    def _schedule(self, count, user):
        """Create `count` activities without notifying.

        `create` notifies an assignee that is not the actor, which is the thing
        under test here -- so the fixture stays quiet and each test triggers the
        one round it means to measure.
        """
        records = self.env['mail.test.activity'].create(
            [{'name': f'Doc {index}'} for index in range(count)])
        return self.env['mail.activity'].with_context(
            mail_activity_quick_update=True).create([{
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                'res_id': record.id,
                'res_model_id': self.env['ir.model']._get_id('mail.test.activity'),
                'user_id': user.id if user else False,
                'summary': 'Act',
            } for record in records])

    def test_unassigned_activities_render_nothing(self):
        activities = self._schedule(5, user=None)
        self.env.invalidate_all()
        with patch.object(
            type(self.env['ir.qweb']), '_render',
            side_effect=AssertionError('rendered a notification with no assignee'),
        ):
            activities.action_notify()

    def test_notifying_does_not_re_derive_the_document_per_activity(self):
        """The reply-to follows the document, so it is resolved for the batch
        rather than once per activity.

        The guarantee is "not per record", not "exactly one call": a future
        cache could reach zero, and reading an exact count as a verdict is what
        cost two sessions an afternoon here (`coding_guidelines.rst` §6.4). So
        bound the derivations, then assert the mechanism actually delivered.
        """
        activities = self._schedule(5, user=self.user_employee)
        self.env.invalidate_all()
        with patch.object(
            type(self.env['mail.test.activity']), '_notify_get_reply_to',
            autospec=True, side_effect=lambda records, **kwargs: dict.fromkeys(
                records.ids, 'reply@test.lan'),
        ) as reply_to:
            activities.action_notify()

        self.assertLessEqual(reply_to.call_count, 1,
                             'derived for the batch, never once per activity')
        if reply_to.call_count:
            self.assertEqual(len(reply_to.call_args[0][0]), 5,
                             'the one derivation covers all five documents')
        messages = self.env['mail.message'].search(
            [('model', '=', 'mail.test.activity'),
             ('res_id', 'in', activities.mapped('res_id')),
             ('message_type', '=', 'user_notification')])
        self.assertEqual(len(messages), 5)
        self.assertEqual(set(messages.mapped('reply_to')), {'reply@test.lan'},
                         'every notification still carries the resolved reply-to')

    def test_the_model_description_is_in_the_assignees_language(self):
        """The assignee reads the notification, so the model's translated name
        must resolve in *their* language, not in the actor's.

        Hoisting `model_description` out of the per-assignee language context is
        the easy way to lose this, and it costs nothing visible until somebody
        runs a database with two languages.
        """
        self.env['res.lang']._activate_lang('fr_FR')
        model = self.env['ir.model']._get('mail.test.activity')
        model.with_context(lang='fr_FR').name = 'Modele De Test'
        self.env.flush_all()
        french_user = mail_new_test_user(
            self.env, login='activity_fr', groups='base.group_user', lang='fr_FR')
        record = self.env['mail.test.activity'].create({'name': 'Doc'})
        activity = self.env['mail.activity'].with_context(
            mail_activity_quick_update=True).create({
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                'res_id': record.id,
                'res_model_id': self.env['ir.model']._get_id('mail.test.activity'),
                'summary': 'Act',
                'user_id': french_user.id,
            })
        activity.action_notify()
        message = self.env['mail.message'].search(
            [('model', '=', 'mail.test.activity'), ('res_id', '=', record.id),
             ('message_type', '=', 'user_notification')], limit=1, order='id desc')
        self.assertIn('Modele De Test', str(message.body))

    def test_two_activities_on_one_record_each_get_their_notification(self):
        """`_message_notify_batch` keys bodies by record, so two activities on
        one record cannot share a batch entry -- they must go in successive
        rounds rather than one overwriting the other."""
        record = self.env['mail.test.activity'].create({'name': 'Doc'})
        common = {
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'date_deadline': fields.Date.context_today(self.env['mail.activity']),
            'res_id': record.id,
            'res_model_id': self.env['ir.model']._get_id('mail.test.activity'),
            'user_id': self.user_employee.id,
        }
        activities = self.env['mail.activity'].with_context(
            mail_activity_quick_update=True).create([
                {**common, 'summary': 'First'}, {**common, 'summary': 'Second'}])
        activities.action_notify()
        messages = self.env['mail.message'].search(
            [('model', '=', 'mail.test.activity'), ('res_id', '=', record.id),
             ('message_type', '=', 'user_notification')])
        self.assertEqual(len(messages), 2, 'one notification per activity')
        bodies = ' '.join(str(message.body) for message in messages)
        self.assertIn('First', bodies)
        self.assertIn('Second', bodies)

    def test_one_batch_keeps_each_document_its_own_company(self):
        """A batch spans documents; the company, alias domain and reply-to do not.

        This works only because `action_notify` does NOT pre-resolve them:
        `_message_notify_batch` derives them itself, per record. Passing them as
        kwargs would write one value across the whole batch.
        """
        second_company = self.env['res.company'].create({'name': 'Second Co'})
        domains = self.env['mail.alias.domain'].create([
            {'name': 'one.test', 'bounce_alias': 'b1', 'catchall_alias': 'c1'},
            {'name': 'two.test', 'bounce_alias': 'b2', 'catchall_alias': 'c2'},
        ])
        self.env.company.alias_domain_id = domains[0]
        second_company.alias_domain_id = domains[1]
        records = self.env['res.partner'].create([
            {'name': 'in co1', 'company_id': self.env.company.id},
            {'name': 'in co2', 'company_id': second_company.id},
        ])
        # same assignee, type and deadline: exactly one batch
        self.env['mail.activity'].with_context(mail_activity_quick_update=True).create([
            {
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                'date_deadline': date(2026, 9, 1),
                'res_id': record.id,
                'res_model_id': self.env['ir.model']._get_id('res.partner'),
                'summary': 'Act',
                'user_id': self.user_employee.id,
            } for record in records
        ]).action_notify()
        messages = self.env['mail.message'].search(
            [('model', '=', 'res.partner'), ('res_id', 'in', records.ids),
             ('message_type', '=', 'user_notification')], order='res_id')
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages.mapped('record_company_id'),
                         self.env.company + second_company)
        self.assertEqual(messages.mapped('record_alias_domain_id'), domains)

    def test_two_types_sharing_a_name_are_not_merged(self):
        """The grouping key carries the activity type as a record, not as its name.

        The name is translated, so keying on it would merge two types that
        collide in the actor's language and hand one of them the other's
        subtitle in the assignee's.
        """
        self.env['res.lang']._activate_lang('fr_FR')
        types = self.env['mail.activity.type'].create([
            {'name': 'Same Name'}, {'name': 'Same Name'}])
        types[0].with_context(lang='fr_FR').name = 'Premier'
        types[1].with_context(lang='fr_FR').name = 'Second'
        french_user = mail_new_test_user(
            self.env, login='activity_fr_types', groups='base.group_user', lang='fr_FR')
        records = self.env['mail.test.activity'].create(
            [{'name': 'A'}, {'name': 'B'}])
        activities = self.env['mail.activity'].with_context(
            mail_activity_quick_update=True).create([
                {
                    'activity_type_id': activity_type.id,
                    'date_deadline': date(2026, 9, 1),
                    'res_id': record.id,
                    'res_model_id': self.env['ir.model']._get_id('mail.test.activity'),
                    'user_id': french_user.id,
                } for activity_type, record in zip(types, records, strict=True)
            ])
        seen = []
        Thread = type(self.env['mail.test.activity'])
        origin = Thread._message_notify_batch

        def spy(records, bodies, **kwargs):
            seen.append(kwargs.get('subtitles'))
            return origin(records, bodies, **kwargs)

        with patch.object(Thread, '_message_notify_batch', spy):
            activities.action_notify()
        self.assertEqual(len(seen), 2, 'two types, two batches')
        self.assertIn('Activity: Premier', seen[0] + seen[1])
        self.assertIn('Activity: Second', seen[0] + seen[1])


@tests.tagged('mail_activity')
class TestActivityUnlinkBookkeeping(ActivityScheduleCase):
    """Unlinking activities that owe nothing must not go looking for keys."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env['mail.test.activity'].create({'name': 'Doc'})
        cls.model_id = cls.env['ir.model']._get_id('mail.test.activity')

    def _activity(self, **vals):
        return self.env['mail.activity'].create({
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'res_id': self.record.id,
            'res_model_id': self.model_id,
            'user_id': self.env.uid,
            **vals,
        })

    def test_unlinking_archived_activities_says_nothing(self):
        activities = self._activity() + self._activity()
        activities.action_archive()
        self.env.flush_all()
        self._reset_bus()
        activities.with_context(active_test=False).unlink()
        self.assertBusNotifications([], [])

    def test_unlinking_a_due_activity_still_says_so(self):
        activity = self._activity(date_deadline=date(2000, 1, 1))
        self.env.flush_all()
        self._reset_bus()
        with self.assertBus(
            [(self.env.cr.dbname, 'res.partner', self.env.user.partner_id.id)],
            [{
                'type': 'mail.activity/updated',
                'payload': {'activity_deleted': True, 'count_diff': -1},
            }],
        ):
            activity.unlink()
