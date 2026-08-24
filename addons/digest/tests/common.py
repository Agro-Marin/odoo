import itertools
import random
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from odoo import SUPERUSER_ID, fields

from odoo.addons.mail.tests import common as mail_test


class TestDigestCommon(mail_test.MailCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_1 = cls.env.company
        cls.company_2 = cls.env['res.company'].create({'name': 'Digest Company 2'})

        context = {
            'start_datetime': datetime.now() - relativedelta(days=1),
            'end_datetime': datetime.now() + relativedelta(days=1),
        }

        cls.all_digests = cls.env['digest.digest'].with_context(context).create([{
            'name': 'Digest 1',
            'company_id': cls.env.company.id,
            'kpi_mail_message_total': True,
            'kpi_res_users_connected': True,
            'periodicity': 'daily',
        }, {
            'name': 'Digest 2',
            'company_id': cls.company_2.id,
        }, {
            'name': 'Digest 3',
            'company_id': False,
        }])

        cls.digest_1, cls.digest_2, cls.digest_3 = cls.all_digests

    @contextmanager
    def mock_datetime_and_now(self, mock_dt):
        """ Used when synchronization date (using env.cr.now()) is important
        in addition to standard datetime mocks. Used mainly to detect sync
        issues. """
        # cr.now() is contractually a datetime; coerce a string so consumers
        # doing datetime arithmetic on it (e.g. ir.cron._now) don't break.
        now_dt = fields.Datetime.to_datetime(mock_dt) if isinstance(mock_dt, str) else mock_dt
        # cr.now() is naive UTC in production; normalize a tz-aware freeze
        # point so it (and freeze_time) stay on that convention, else
        # naive/aware comparisons (e.g. ir.cron._now) crash. Mirrors mail
        # freeze_all_time.
        if now_dt.tzinfo is not None:
            now_dt = now_dt.astimezone(UTC).replace(tzinfo=None)
        with freeze_time(now_dt), \
             patch.object(self.env.cr, 'now', lambda: now_dt):
            yield

    @classmethod
    def _setup_logs_for_users(cls, res_users, log_dt):
        """Create one `res.users.log` per user, attributed to that user.

        `create_uid` in `create()` values is honoured only while the registry
        is still loading -- `_crud_common.bad_field_names` pops every
        LOG_ACCESS column unless `env.uid == SUPERUSER_ID and not pool.ready`.
        At install time that holds and the value sticks; **post_install it does
        not**, and every log silently lands on `__system__` instead. Nothing
        raises: the digest simply finds no log for its recipients, decides they
        are away, and the tone-down assertions flip in the direction that looks
        like a pass. Measured, same helper, same call:

            PROBE[at_install]   ready=False  asked_for=2  stored=2
            PROBE[post_install] ready=True   asked_for=2  stored=1

        So the attribution is forced afterwards and then asserted, rather than
        left to a condition the test's own tag decides.
        """
        with cls.mock_datetime_and_now(cls, log_dt):
            logs = cls.env['res.users.log'].with_user(SUPERUSER_ID).create([
                {'create_uid': user.id} for user in res_users
            ])
        cls.env.flush_all()
        for log, user in zip(logs, res_users, strict=True):
            if log.create_uid != user:
                cls.env.cr.execute(
                    'UPDATE res_users_log SET create_uid = %s WHERE id = %s',
                    (user.id, log.id),
                )
        cls.env.invalidate_all()
        stored = logs.mapped('create_uid')
        assert stored.ids == res_users.ids, (
            f'log attribution did not stick: asked {res_users.ids}, '
            f'stored {stored.ids}'
        )
        return logs

    @classmethod
    def _setup_messages(cls):
        """ Remove all existing messages, then create a bunch of them on random
        partners with the correct types in correct time-bucket:

        - 3 in the previous 24h
        - 5 more in the 6 days before that for a total of 8 in the previous week
        - 7 more in the 20 days before *that* (because digest doc lies and is
          based around weeks and months not days), for a total of 15 in the
          previous month
        """
        # regular employee can't necessarily access "private" addresses
        partners = cls.env['res.partner'].search([])
        messages = cls.env['mail.message']
        counter = itertools.count()

        now = fields.Datetime.now()
        for count, (low, high) in [
            (3, (0 * 24, 1 * 24)),
            (5, (1 * 24, 7 * 24)),
            (7, (7 * 24, 27 * 24)),
        ]:
            for __ in range(count):
                create_date = now - relativedelta(hours=random.randint(low + 1, high - 1))
                messages += random.choice(partners).message_post(
                    author_id=cls.partner_admin.id,
                    body=f"Awesome Partner! ({next(counter)})",
                    email_from=cls.partner_admin.email_formatted,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                    # adjust top and bottom by 1h to avoid overlapping with the
                    # range limit and dropping out of the digest's selection thing
                    create_date=create_date,
                )
        cls.env.flush_all()
