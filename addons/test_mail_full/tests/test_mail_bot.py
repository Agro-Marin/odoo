from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.mail.tests.common import MailCommon
from odoo.addons.test_mail.tests.common import TestRecipients


@tagged("odoobot")
class TestOdoobot(MailCommon, TestRecipients):
    """OdooBot seen from outside a discuss channel.

    The onboarding tour itself is `mail_bot/tests`, which drives every step and
    every retry branch directly. What is left here is the part that needs a
    non-channel thread: odoobot must stay silent on an ordinary record even when
    it is pinged, and must not become a follower of one.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_record = cls.env['mail.test.simple'].with_context(cls._test_context).create({'name': 'Test', 'email_from': 'ignasse@example.com'})
        cls.odoobot = cls.env.ref("base.partner_root")
        cls.message_post_default_kwargs = {
            'body': '',
            'attachment_ids': [],
            'message_type': 'comment',
            'partner_ids': [],
            'subtype_xmlid': 'mail.mt_comment'
        }
        cls.odoobot_ping_body = f'<a href="http://odoo.com/odoo/res.partner/{cls.odoobot.id}" class="o_mail_redirect" data-oe-id="{cls.odoobot.id}" data-oe-model="res.partner" target="_blank">@OdooBot</a>'
        cls.test_record_employe = cls.test_record.with_user(cls.user_employee)

    def assertNoAnswer(self, record, message):
        """No message was posted on `record` after `message`.

        Scoped to the thread and to "anything newer", rather than to the single
        id following the message: `mail.message` ids are global, so `id + 1`
        asserted against whatever the rest of the transaction happened to create
        next.
        """
        later = self.env['mail.message'].search([
            ('model', '=', record._name),
            ('res_id', '=', record.id),
            ('id', '>', message.id),
        ])
        self.assertFalse(later, f"odoobot answered on {record._name}: {later.mapped('body')}")

    @mute_logger('odoo.addons.mail.models.mail_mail')
    def test_fetch_listener(self):
        channel = self.user_employee.with_user(self.user_employee)._init_odoobot()
        odoobot_in_fetch_listeners = self.env['discuss.channel.member'].search([('channel_id', '=', channel.id), ('partner_id', '=', self.odoobot.id)])
        self.assertEqual(len(odoobot_in_fetch_listeners), 1, 'odoobot should appear only once in channel_fetch_listeners')

    @mute_logger('odoo.addons.mail.models.mail_mail')
    def test_odoobot_ping(self):
        kwargs = self.message_post_default_kwargs.copy()
        kwargs.update({'body': self.odoobot_ping_body, 'partner_ids': [self.odoobot.id, self.user_admin.partner_id.id]})

        message = self.test_record_employe.with_context({'mail_post_autofollow': True}).message_post(**kwargs)
        self.assertNoAnswer(self.test_record, message)
        # Odoobot should not be a follower but user_employee and user_admin should
        follower = self.test_record.message_follower_ids.mapped('partner_id')
        self.assertNotIn(self.odoobot, follower)
        self.assertIn(self.user_employee.partner_id, follower)
        self.assertIn(self.user_admin.partner_id, follower)

    @mute_logger('odoo.addons.mail.models.mail_mail')
    def test_odoobot_no_default_answer(self):
        kwargs = self.message_post_default_kwargs.copy()
        kwargs.update({'body': "I'm not talking to @odoobot right now", 'partner_ids': []})
        message = self.test_record_employe.message_post(**kwargs)
        self.assertNoAnswer(self.test_record, message)
