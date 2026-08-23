# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import UTC, datetime, timedelta

from odoo.tests import tagged

from odoo.addons.base.tests.test_ir_cron import CronMixinCase
from odoo.addons.sms.tests.common import SMSCommon
from odoo.addons.test_mail_sms.tests.common import TestSMSRecipients


@tagged('sms_post')
class TestSMSPost(SMSCommon, TestSMSRecipients, CronMixinCase):
    """ TODO

      * add tests for new mail.message and mixin.mail.thread fields;
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._test_body = 'VOID CONTENT'

        cls.test_record = cls.env['mail.test.sms'].with_context(**cls._test_context).create({
            'name': 'Test',
            'customer_id': cls.partner_1.id,
            'mobile_nbr': cls.test_numbers[0],
            'phone_nbr': cls.test_numbers[1],
        })
        cls.test_record = cls._reset_mail_context(cls.test_record)

    def test_sms_channel_survives_notify_skip_followers(self):
        """Skipping followers must not turn an SMS into an email.

        ``notify_skip_followers`` used to be expressed by handing
        ``_get_recipient_data`` the string ``user_notification`` in place of
        the real message type. That string is what the base method reads to
        drop followers -- and ``message_type`` is also what this addon reads to
        pick the delivery channel, so the flag silently rerouted it to email.
        """
        for skip_followers in (False, True):
            with self.subTest(skip_followers=skip_followers):
                record = self.env['mail.test.sms'].create({
                    'name': 'Skip %s' % skip_followers,
                    'customer_id': self.partner_1.id,
                    'phone_nbr': self.test_numbers[1],
                })
                with self.mockSMSGateway():
                    message = record.message_post(
                        body='hi', message_type='sms',
                        subtype_id=self.env.ref('mail.mt_note').id,
                        partner_ids=self.partner_1.ids,
                        notify_skip_followers=skip_followers,
                    )
                self.assertEqual(
                    message.sudo().notification_ids.notification_type, 'sms',
                    'an SMS is delivered by SMS whether or not followers are skipped',
                )

    def test_message_sms_marks_only_the_addressed_partners(self):
        """SMS goes to the partners the SMS names, not to whoever follows.

        `mail.followers._get_recipient_data` returns followers and explicit
        recipients in one dict; the `sms` override is what tells them apart, by
        setting `notif` to `sms` for the named partners only. It used to branch
        on `pids is None` vs `pids == []` as well, a distinction the base method
        erases with `list(pids or [])` before the override ever sees it.
        """
        Followers = self.env['mail.followers']
        test_record = self.env['mail.test.sms'].browse(self.test_record.id)
        test_record.message_subscribe(partner_ids=self.partner_2.ids)
        self.env.flush_all()
        # mt_comment, not mt_note: a note is internal and reaches no follower at
        # all, so under it the follower assertion below has no key to read and
        # the override's behaviour is never exercised.
        subtype_id = self.env.ref('mail.mt_comment').id

        addressed = Followers._get_recipient_data(
            test_record, 'sms', subtype_id, self.partner_1.ids)[test_record.id]
        self.assertEqual(addressed[self.partner_1.id]['notif'], 'sms')
        self.assertNotEqual(
            addressed[self.partner_2.id]['notif'], 'sms',
            'a follower who was not addressed does not get a text message')

        # no explicit recipients: nobody is upgraded to sms
        for pids in ([], None):
            with self.subTest(pids=pids):
                data = Followers._get_recipient_data(
                    test_record, 'sms', subtype_id, pids)[test_record.id]
                self.assertFalse(
                    [p for p, d in data.items() if d['notif'] == 'sms'],
                    'None and [] mean the same thing to the base method')

    def test_message_sms_internals_body(self):
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms('<p>Mega SMS<br/>Top moumoutte</p>', partner_ids=self.partner_1.ids)

        self.assertEqual(messages.body, '<p>&lt;p&gt;Mega SMS&lt;br/&gt;Top moumoutte&lt;/p&gt;</p>')  # html should not be interpreted
        self.assertEqual(messages.subtype_id, self.env.ref('mail.mt_note'))
        self.assertSMSNotification([{'partner': self.partner_1}], '<p>Mega SMS<br/>Top moumoutte</p>', messages)

    def test_message_sms_internals_sms_numbers(self):
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=self.partner_1.ids, sms_numbers=self.random_numbers)

        self.assertSMSNotification([{'partner': self.partner_1}, {'number': self.random_numbers_san[0]}, {'number': self.random_numbers_san[1]}], self._test_body, messages)

    def test_message_sms_internals_sms_numbers_duplicate(self):
        """ _message_sms ( which uses _notify_thread_by_sms) allows for specifying additional number to send sms to
            This test checks for situation where this additional number is the same as partner telephone number.
            In that case sms shall NOT be sent twice."""
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            additional_number_same_as_partner_number = self.partner_1.phone
            subtype_id = self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note')
            test_record._message_sms(
                body=self._test_body,
                partner_ids=self.partner_1.ids,
                subtype_id=subtype_id,
                sms_numbers=[additional_number_same_as_partner_number],
                number_field='phone'
            )
        self.assertEqual(len(self._new_sms.filtered(lambda s: s.number == self.partner_numbers[0])), 1,
            "There should be one message sent if additional number is the same as partner number")

    def test_message_sms_internals_subtype(self):
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms('<p>Mega SMS<br/>Top moumoutte</p>', subtype_id=self.env.ref('mail.mt_comment').id, partner_ids=self.partner_1.ids)

        self.assertEqual(messages.body, '<p>&lt;p&gt;Mega SMS&lt;br/&gt;Top moumoutte&lt;/p&gt;</p>')  # html should not be interpreted
        self.assertEqual(messages.subtype_id, self.env.ref('mail.mt_comment'))
        self.assertSMSNotification([{'partner': self.partner_1}], '<p>Mega SMS<br/>Top moumoutte</p>', messages)

    def test_message_sms_internals_pid_to_number(self):
        pid_to_number = {
            self.partner_1.id: self.random_numbers[0],
            self.partner_2.id: self.random_numbers[1],
        }
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=(self.partner_1 | self.partner_2).ids, sms_pid_to_number=pid_to_number)

        self.assertSMSNotification([
            {'partner': self.partner_1, 'number': self.random_numbers_san[0]},
            {'partner': self.partner_2, 'number': self.random_numbers_san[1]}],
            self._test_body, messages)

    def test_message_sms_model_partner(self):
        with self.with_user('employee'), self.mockSMSGateway():
            messages = self.partner_1._message_sms(self._test_body)
            messages |= self.partner_2._message_sms(self._test_body)
        self.assertSMSNotification([{'partner': self.partner_1}, {'partner': self.partner_2}], self._test_body, messages)

    def test_message_sms_model_partner_fallback(self):
        self.partner_1.write({'phone': self.random_numbers[0]})

        with self.mockSMSGateway():
            messages = self.partner_1._message_sms(self._test_body)
            messages |= self.partner_2._message_sms(self._test_body)

        self.assertSMSNotification([{'partner': self.partner_1, 'number': self.random_numbers_san[0]}, {'partner': self.partner_2}], self._test_body, messages)

    def test_message_sms_model_w_partner_only(self):
        with self.with_user('employee'):
            record = self.env['mail.test.sms.partner'].create({'customer_id': self.partner_1.id})

            with self.mockSMSGateway():
                messages = record._message_sms(self._test_body)

        self.assertSMSNotification([{'partner': self.partner_1}], self._test_body, messages)

    def test_message_sms_model_w_partner_only_void(self):
        with self.with_user('employee'):
            record = self.env['mail.test.sms.partner'].create({'customer_id': False})

            with self.mockSMSGateway():
                messages = record._message_sms(self._test_body)

        # should not crash but have a failed notification
        self.assertSMSNotification([{'partner': self.env['res.partner'], 'number': False, 'state': 'exception', 'failure_type': 'sms_number_missing'}], self._test_body, messages)

    def test_message_sms_model_w_partner_m2m_only(self):
        with self.with_user('employee'):
            record = self.env['mail.test.sms.partner.2many'].create({'customer_ids': [(4, self.partner_1.id)]})

            with self.mockSMSGateway():
                messages = record._message_sms(self._test_body)

        self.assertSMSNotification([{'partner': self.partner_1}], self._test_body, messages)

        # TDE: should take first found one according to partner ordering
        with self.with_user('employee'):
            record = self.env['mail.test.sms.partner.2many'].create({'customer_ids': [(4, self.partner_1.id), (4, self.partner_2.id)]})

            with self.mockSMSGateway():
                messages = record._message_sms(self._test_body)

        self.assertSMSNotification([{'partner': self.partner_2}], self._test_body, messages)

    def test_message_sms_on_field_w_partner(self):
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, number_field='mobile_nbr')

        self.assertSMSNotification([{'partner': self.partner_1, 'number': self.test_record.mobile_nbr}], self._test_body, messages)

    def test_message_sms_on_field_wo_partner(self):
        self.test_record.write({'customer_id': False})

        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, number_field='mobile_nbr')

        self.assertSMSNotification([{'number': self.test_record.mobile_nbr}], self._test_body, messages)

    def test_message_sms_on_field_wo_partner_wo_value(self):
        """ Test record without a partner and without phone values. """
        self.test_record.write({
            'customer_id': False,
            'phone_nbr': False,
            'mobile_nbr': False,
        })

        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body)

        # should not crash but have a failed notification
        self.assertSMSNotification([{'partner': self.env['res.partner'], 'number': False, 'state': 'exception', 'failure_type': 'sms_number_missing'}], self._test_body, messages)

    def test_message_sms_on_field_wo_partner_default_field(self):
        self.test_record.write({'customer_id': False})

        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body)

        self.assertSMSNotification([{'number': self.test_numbers_san[1]}], self._test_body, messages)

    def test_message_sms_on_field_wo_partner_default_field_2(self):
        self.test_record.write({'customer_id': False, 'phone_nbr': False})

        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body)

        self.assertSMSNotification([{'number': self.test_numbers_san[0]}], self._test_body, messages)

    def test_message_sms_on_numbers(self):
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, sms_numbers=self.random_numbers_san)
        self.assertSMSNotification([{'number': self.random_numbers_san[0]}, {'number': self.random_numbers_san[1]}], self._test_body, messages)

    def test_message_sms_on_numbers_sanitization(self):
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, sms_numbers=self.random_numbers)
        self.assertSMSNotification([{'number': self.random_numbers_san[0]}, {'number': self.random_numbers_san[1]}], self._test_body, messages)

    def test_message_sms_on_partner_ids(self):
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=(self.partner_1 | self.partner_2).ids)

        self.assertSMSNotification([{'partner': self.partner_1}, {'partner': self.partner_2}], self._test_body, messages)

    def test_message_sms_on_partner_ids_default(self):
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body)

        self.assertSMSNotification([{'partner': self.test_record.customer_id, 'number': self.test_numbers_san[1]}], self._test_body, messages)

    def test_message_sms_on_partner_ids_w_numbers(self):
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=self.partner_1.ids, sms_numbers=self.random_numbers[:1])

        self.assertSMSNotification([{'partner': self.partner_1}, {'number': self.random_numbers_san[0]}], self._test_body, messages)

    def test_message_sms_schedule(self):
        """ Test delaying notifications through scheduled_date usage """
        cron_id = self.env.ref('mail.ir_cron_send_scheduled_message').id
        # naive UTC: the ORM stores and returns Datetime fields naive (see
        # mail.tests.common.freeze_all_time), so an aware expected value would
        # never equal the naive call_at / scheduled_datetime read back below.
        now = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
        scheduled_datetime = now + timedelta(days=5)

        with self.mock_datetime_and_now(now), \
             self.with_user('employee'), \
             self.capture_triggers(cron_id) as capt, \
             self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(
                'Testing Scheduled Notifications',
                partner_ids=self.partner_1.ids,
                scheduled_date=scheduled_datetime,
            )

        self.assertEqual(capt.records.call_at, scheduled_datetime,
                         msg='Should have created a cron trigger for the scheduled sending')
        self.assertFalse(self._new_sms)
        self.assertFalse(self._sms)

        schedules = self.env['mail.message.schedule'].sudo().search([('mail_message_id', '=', messages.id)])
        self.assertEqual(len(schedules), 1, msg='Should have scheduled the message')
        self.assertEqual(schedules.scheduled_datetime, scheduled_datetime)

        # trigger cron now -> should not sent as in future
        with self.mock_datetime_and_now(now):
            self.env['mail.message.schedule'].sudo()._send_notifications_cron()
        self.assertTrue(schedules.exists(), msg='Should not have sent the message')

        # Send the scheduled message from the cron at right date
        with self.mock_datetime_and_now(now + timedelta(days=5)), self.mockSMSGateway():
            self.env['mail.message.schedule'].sudo()._send_notifications_cron()
        self.assertFalse(schedules.exists(), msg='Should have sent the message')
        # check notifications have been sent
        self.assertSMSNotification([{'partner': self.partner_1}], 'Testing Scheduled Notifications', messages)

    def test_message_sms_with_template(self):
        sms_template = self.env['sms.template'].create({
            'name': 'Test Template',
            'model_id': self.env['ir.model']._get('mail.test.sms').id,
            'body': 'Dear {{ object.display_name }} this is an SMS.',
        })

        with self.with_user('employee'):
            with self.mockSMSGateway():
                test_record = self.env['mail.test.sms'].browse(self.test_record.id)
                messages = test_record._message_sms_with_template(template=sms_template)

        self.assertSMSNotification([{'partner': self.partner_1, 'number': self.test_numbers_san[1]}], 'Dear %s this is an SMS.' % self.test_record.display_name, messages)

    def test_message_sms_with_template_fallback(self):
        with self.with_user('employee'):
            with self.mockSMSGateway():
                test_record = self.env['mail.test.sms'].browse(self.test_record.id)
                messages = test_record._message_sms_with_template(template_xmlid='test_mail_full.this_should_not_exists', template_fallback='Fallback for {{ object.id }}')

        self.assertSMSNotification([{'partner': self.partner_1, 'number': self.test_numbers_san[1]}], 'Fallback for %s' % self.test_record.id, messages)

    def test_message_sms_with_template_xmlid(self):
        sms_template = self.env['sms.template'].create({
            'name': 'Test Template',
            'model_id': self.env['ir.model']._get('mail.test.sms').id,
            'body': 'Dear {{ object.display_name }} this is an SMS.',
        })
        self.env['ir.model.data'].create({
            'name': 'this_should_exists',
            'module': 'test_mail_full',
            'model': sms_template._name,
            'res_id': sms_template.id,
        })

        with self.with_user('employee'):
            with self.mockSMSGateway():
                test_record = self.env['mail.test.sms'].browse(self.test_record.id)
                messages = test_record._message_sms_with_template(template_xmlid='test_mail_full.this_should_exists')

        self.assertSMSNotification([{'partner': self.partner_1, 'number': self.test_numbers_san[1]}], 'Dear %s this is an SMS.' % self.test_record.display_name, messages)


@tagged('sms_post')
class TestSMSPostException(SMSCommon, TestSMSRecipients):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._test_body = 'VOID CONTENT'

        cls.test_record = cls.env['mail.test.sms'].with_context(**cls._test_context).create({
            'name': 'Test',
            'customer_id': cls.partner_1.id,
        })
        cls.test_record = cls._reset_mail_context(cls.test_record)
        cls.partner_3 = cls.env['res.partner'].with_context({
            'mail_create_nolog': True,
            'mail_create_nosubscribe': True,
            'mail_notrack': True,
            'no_reset_password': True,
        }).create({
            'name': 'Ernestine Loubine',
            'email': 'ernestine.loubine@agrolait.com',
            'country_id': cls.env.ref('base.be').id,
            'phone': '0475556644',
        })

    def test_message_sms_w_numbers_invalid(self):
        random_numbers = self.random_numbers + ['6988754']
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, sms_numbers=random_numbers)

        # invalid numbers are still given to IAP currently as they are
        self.assertSMSNotification([{'number': self.random_numbers_san[0]}, {'number': self.random_numbers_san[1]}, {'number': random_numbers[2]}], self._test_body, messages)

    def test_message_sms_w_partners_nocountry(self):
        self.test_record.customer_id.write({
            'phone': self.random_numbers[1],
            'country_id': False,
        })
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=self.test_record.customer_id.ids)

        self.assertSMSNotification([{'partner': self.test_record.customer_id}], self._test_body, messages)

    def test_message_sms_w_partners_falsy(self):
        # TDE FIXME: currently sent to IAP
        self.test_record.customer_id.write({
            'phone': 'youpla',
        })
        with self.with_user('employee'), self.mockSMSGateway():
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=self.test_record.customer_id.ids)

        # self.assertSMSNotification({self.test_record.customer_id: {}}, {}, self._test_body, messages)

    def test_message_sms_w_numbers_sanitization_duplicate(self):
        pass
        # TDE FIXME: not sure
        # random_numbers = self.random_numbers + [self.random_numbers[1]]
        # random_numbers_san = self.random_numbers_san + [self.random_numbers_san[1]]
        # with self.with_user('employee'), self.mockSMSGateway():
        #     messages = self.test_record._message_sms(self._test_body, sms_numbers=random_numbers)
        # self.assertSMSNotification({}, {random_numbers_san[0]: {}, random_numbers_san[1]: {}, random_numbers_san[2]: {}}, self._test_body, messages)

    def test_message_sms_crash_credit(self):
        with self.with_user('employee'), self.mockSMSGateway(sim_error='credit'):
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=(self.partner_1 | self.partner_2).ids)

        self.assertSMSNotification([
            {'partner': self.partner_1, 'state': 'exception', 'failure_type': 'sms_credit'},
            {'partner': self.partner_2, 'state': 'exception', 'failure_type': 'sms_credit'},
        ], self._test_body, messages)

    def test_message_sms_crash_credit_single(self):
        with self.with_user('employee'), self.mockSMSGateway(nbr_t_error={self.partner_2._phone_format(): 'credit'}):
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=(self.partner_1 | self.partner_2 | self.partner_3).ids)

        self.assertSMSNotification([
            {'partner': self.partner_1, 'state': 'pending'},
            {'partner': self.partner_2, 'state': 'exception', 'failure_type': 'sms_credit'},
            {'partner': self.partner_3, 'state': 'pending'},
        ], self._test_body, messages)

    def test_message_sms_crash_server_crash(self):
        with self.with_user('employee'), self.mockSMSGateway(sim_error='jsonrpc_exception'):
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=(self.partner_1 | self.partner_2 | self.partner_3).ids)

        self.assertSMSNotification([
            {'partner': self.partner_1, 'state': 'exception', 'failure_type': 'sms_server'},
            {'partner': self.partner_2, 'state': 'exception', 'failure_type': 'sms_server'},
            {'partner': self.partner_3, 'state': 'exception', 'failure_type': 'sms_server'},
        ], self._test_body, messages)

    def test_message_sms_crash_unregistered(self):
        with self.with_user('employee'), self.mockSMSGateway(sim_error='unregistered'):
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=(self.partner_1 | self.partner_2).ids)

        self.assertSMSNotification([
            {'partner': self.partner_1, 'state': 'exception', 'failure_type': 'sms_acc'},
            {'partner': self.partner_2, 'state': 'exception', 'failure_type': 'sms_acc'},
        ], self._test_body, messages)

    def test_message_sms_crash_unregistered_single(self):
        with self.with_user('employee'), self.mockSMSGateway(nbr_t_error={self.partner_2._phone_format(): 'unregistered'}):
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=(self.partner_1 | self.partner_2 | self.partner_3).ids)

        self.assertSMSNotification([
            {'partner': self.partner_1, 'state': 'pending'},
            {'partner': self.partner_2, 'state': 'exception', 'failure_type': 'sms_acc'},
            {'partner': self.partner_3, 'state': 'pending'},
        ], self._test_body, messages)

    def test_message_sms_crash_wrong_number(self):
        with self.with_user('employee'), self.mockSMSGateway(sim_error='wrong_number_format'):
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=(self.partner_1 | self.partner_2).ids)

        self.assertSMSNotification([
            {'partner': self.partner_1, 'state': 'exception', 'failure_type': 'sms_number_format'},
            {'partner': self.partner_2, 'state': 'exception', 'failure_type': 'sms_number_format'},
        ], self._test_body, messages)

    def test_message_sms_crash_wrong_number_single(self):
        with self.with_user('employee'), self.mockSMSGateway(nbr_t_error={self.partner_2._phone_format(): 'wrong_number_format'}):
            test_record = self.env['mail.test.sms'].browse(self.test_record.id)
            messages = test_record._message_sms(self._test_body, partner_ids=(self.partner_1 | self.partner_2 | self.partner_3).ids)

        self.assertSMSNotification([
            {'partner': self.partner_1, 'state': 'pending'},
            {'partner': self.partner_2, 'state': 'exception', 'failure_type': 'sms_number_format'},
            {'partner': self.partner_3, 'state': 'pending'},
        ], self._test_body, messages)


class TestSMSApi(SMSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._test_body = 'Zizisse an SMS.'

        cls._create_records_for_batch('mail.test.sms', 3)
        cls.sms_template = cls._create_sms_template('mail.test.sms')

    def test_message_schedule_sms(self):
        with self.with_user('employee'):
            with self.mockSMSGateway():
                self.env['mail.test.sms'].browse(self.records.ids)._message_sms_schedule_mass(body=self._test_body, mass_keep_log=False)

        for record in self.records:
            self.assertSMSOutgoing(record.customer_id, None, content=self._test_body)

    def test_message_schedule_sms_w_log(self):
        with self.with_user('employee'):
            with self.mockSMSGateway():
                self.env['mail.test.sms'].browse(self.records.ids)._message_sms_schedule_mass(body=self._test_body, mass_keep_log=True)

        for record in self.records:
            self.assertSMSOutgoing(record.customer_id, None, content=self._test_body)
            self.assertSMSLogged(record, self._test_body)

    def test_message_schedule_sms_w_template(self):
        with self.with_user('employee'):
            with self.mockSMSGateway():
                self.env['mail.test.sms'].browse(self.records.ids)._message_sms_schedule_mass(template=self.sms_template, mass_keep_log=False)

        for record in self.records:
            self.assertSMSOutgoing(record.customer_id, None, content='Dear %s this is an SMS.' % record.display_name)

    def test_message_schedule_sms_w_template_and_log(self):
        with self.with_user('employee'):
            with self.mockSMSGateway():
                self.env['mail.test.sms'].browse(self.records.ids)._message_sms_schedule_mass(template=self.sms_template, mass_keep_log=True)

        for record in self.records:
            self.assertSMSOutgoing(record.customer_id, None, content='Dear %s this is an SMS.' % record.display_name)
            self.assertSMSLogged(record, 'Dear %s this is an SMS.' % record.display_name)
