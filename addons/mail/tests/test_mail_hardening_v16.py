"""Regression tests for the sixteenth mail hardening audit.

This audit swept a single class of defect: a computed field whose ``@api.depends``
does not cover everything its compute actually reads. Such a field is correct on
first read and silently stale for the rest of the transaction -- which, for a web
request, is exactly the window in which ``web_save`` reads the record back and
returns it to the client.

Each test writes a dependency, reads the field, and compares against the value an
``invalidate_recordset()`` produces. They are written so that they fail on the
pre-fix code rather than merely asserting the fixed behaviour.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo import tools
from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCommon


@tagged("mail_activity", "post_install", "-at_install")
class TestActivityStateFollowsAssigneeV16(MailCommon):
    """``mail.activity.state`` is resolved in the *assignee's* timezone.

    The compute read that timezone through ``record.user_id.sudo().tz`` while
    declaring only ``('active', 'date_deadline')``. Reassigning an activity
    therefore left ``state`` -- and the ``activity_state`` clock computed from it
    -- showing the previous assignee's verdict for the rest of the transaction.

    ``mail.activity`` already stores ``user_tz`` (related to ``user_id.tz``), and
    ``_search_activity_state`` evaluates that very column in SQL. Depending on it
    both fixes the invalidation and makes the Python compute and the SQL search
    read the same value.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model_id = cls.env["ir.model"]._get("res.partner").id
        cls.document = cls.env["res.partner"].create({"name": "V16 Document"})
        cls.activity_type = cls.env["mail.activity.type"].create({"name": "V16 Todo"})
        # UTC vs UTC+14: on 2024-06-01 12:00 UTC it is already 2024-06-02 in
        # Kiritimati, so a deadline of 2024-06-01 is "today" for one assignee and
        # "overdue" for the other.
        cls.user_utc, cls.user_ahead = cls.env["res.users"].create(
            [
                {"name": "V16 UTC", "login": "v16_utc", "tz": "UTC"},
                {"name": "V16 Ahead", "login": "v16_ahead", "tz": "Pacific/Kiritimati"},
            ]
        )

    def _activity(self, user):
        return self.env["mail.activity"].create(
            {
                "res_model_id": self.partner_model_id,
                "res_id": self.document.id,
                "activity_type_id": self.activity_type.id,
                "user_id": user.id,
                "date_deadline": "2024-06-01",
            }
        )

    @freeze_time("2024-06-01 12:00:00")
    def test_state_follows_a_reassignment(self):
        activity = self._activity(self.user_utc)
        self.assertEqual(activity.state, "today", "sanity: UTC assignee is on time")

        activity.user_id = self.user_ahead
        self.assertEqual(
            activity.state,
            "overdue",
            "state must follow the new assignee's timezone without an explicit "
            "invalidation; it used to keep the previous assignee's verdict",
        )

    @freeze_time("2024-06-01 12:00:00")
    def test_state_follows_the_assignee_changing_timezone(self):
        activity = self._activity(self.user_utc)
        self.assertEqual(activity.state, "today")

        self.user_utc.tz = "Pacific/Kiritimati"
        self.assertEqual(
            activity.state,
            "overdue",
            "the assignee moving timezone must invalidate the state too",
        )

    @freeze_time("2024-06-01 12:00:00")
    def test_compute_agrees_with_the_sql_search_after_a_reassignment(self):
        """The compute and ``_search_activity_state`` must not disagree.

        The search reads ``mail_activity.user_tz`` in SQL, so it was always
        right; only the cached compute was stale. That divergence is what makes
        a stale state visible as a list view whose clock contradicts its own
        "Overdue" filter.
        """
        activity = self._activity(self.user_utc)
        self.assertEqual(activity.state, "today")

        activity.user_id = self.user_ahead
        self.env.flush_all()
        overdue_docs = self.env["res.partner"].search(
            [
                ("id", "=", self.document.id),
                ("activity_state", "=", "overdue"),
            ]
        )
        self.assertEqual(
            overdue_docs, self.document, "sanity: SQL search sees it as overdue"
        )
        self.assertEqual(
            activity.state, "overdue", "the compute must agree with the search"
        )

    @freeze_time("2024-06-01 12:00:00")
    def test_state_reads_no_res_users_row(self):
        """Resolving the timezone must not cost a read of res.users.

        ``user_tz`` is stored on mail_activity, so the state of a page of
        activities is answerable from rows already loaded. The previous spelling
        went through ``user_id.sudo().tz`` and pulled res.users in.
        """
        activities = self.env["mail.activity"].concat(
            *[self._activity(user) for user in (self.user_utc, self.user_ahead)]
        )
        self.env.flush_all()
        activities.invalidate_recordset()
        self.env["res.users"].invalidate_model()

        with self.assertQueryCount(1):
            # one read of mail_activity, none of res.users
            activities.mapped("state")

    @freeze_time("2024-06-01 12:00:00")
    def test_unassigned_activity_still_falls_back_to_utc(self):
        activity = self._activity(self.user_utc)
        activity.user_id = False
        self.assertEqual(
            activity.state, "today", "no assignee must still mean UTC, not a crash"
        )


@tagged("mail_activity", "post_install", "-at_install")
class TestRecommendedActivitiesInvalidateV16(MailCommon):
    """``has_recommended_activities`` backed a compute with no ``@api.depends``.

    The method carried ``@api.onchange('previous_activity_type_id')`` only, so
    the field refreshed in a form and nowhere else: computed once, then cached
    forever against a ``previous_activity_type_id`` that had since changed.
    """

    def test_field_follows_previous_activity_type(self):
        next_type = self.env["mail.activity.type"].create({"name": "V16 Next"})
        plain = self.env["mail.activity.type"].create({"name": "V16 Plain"})
        with_suggestions = self.env["mail.activity.type"].create(
            {
                "name": "V16 Suggesting",
                "suggested_next_type_ids": [(6, 0, next_type.ids)],
            }
        )
        document = self.env["res.partner"].create({"name": "V16 Rec Document"})
        activity = self.env["mail.activity"].create(
            {
                "res_model_id": self.env["ir.model"]._get("res.partner").id,
                "res_id": document.id,
                "activity_type_id": plain.id,
                "user_id": self.env.user.id,
            }
        )
        self.assertFalse(activity.has_recommended_activities)

        activity.previous_activity_type_id = with_suggestions
        self.assertTrue(
            activity.has_recommended_activities,
            "the field must follow previous_activity_type_id outside a form too",
        )


@tagged("mail_mail", "post_install", "-at_install")
class TestMailMailDerivedFieldsInvalidateV16(MailCommon):
    """``mail.mail`` carried two mirror fields with no ``@api.depends`` at all."""

    def _mail(self, **values):
        message = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": self.env.user.partner_id.id,
                "body": "<p>V16</p>",
            }
        )
        return self.env["mail.mail"].create({"mail_message_id": message.id, **values})

    def test_body_content_follows_body_html(self):
        mail = self._mail(body_html="<p>one</p>")
        self.assertEqual(mail.body_content, "<p>one</p>")

        mail.body_html = "<p>two</p>"
        self.assertEqual(
            mail.body_content, "<p>two</p>", "body_content mirrors body_html"
        )

    def test_mail_message_id_int_follows_mail_message_id(self):
        mail = self._mail(body_html="<p>one</p>")
        self.assertEqual(mail.mail_message_id_int, mail.mail_message_id.id)

        other = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": self.env.user.partner_id.id,
                "body": "<p>other</p>",
            }
        )
        mail.mail_message_id = other
        self.assertEqual(
            mail.mail_message_id_int,
            other.id,
            "mail_message_id_int mirrors mail_message_id",
        )


@tagged("mail_notify", "post_install", "-at_install")
class TestScheduledNotificationQueueIsFifoV16(MailCommon):
    """The scheduled-notification queue must drain oldest-due first.

    ``mail.message.schedule`` sets ``_order = 'scheduled_datetime DESC, id DESC'``
    -- sensible for the list view, wrong for a queue -- and
    ``_send_notifications_cron`` searched without an explicit ``order``. With a
    backlog larger than one batch (500 by default), every tick therefore re-picked
    the *newest* due schedules and the oldest were never reached.

    ``mail.mail.process_email_queue`` already forces ``order="id"`` against the
    same hazard; this is the sibling queue that was missed.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.document = cls.env["res.partner"].create({"name": "V16 Queue Document"})
        cls.env["ir.config_parameter"].sudo().set_param(
            "mail.scheduled_notification.batch.size", "2"
        )

    def _schedule(self, minutes_ago):
        """A due schedule, older the larger ``minutes_ago`` is."""
        message = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": self.document.id,
                "body": f"<p>V16 queue {minutes_ago}</p>",
            }
        )
        return self.env["mail.message.schedule"].create(
            {
                "mail_message_id": message.id,
                "scheduled_datetime": datetime.now(UTC).replace(tzinfo=None)
                - timedelta(minutes=minutes_ago),
            }
        )

    def test_cron_drains_the_oldest_due_schedules_first(self):
        # created newest-first so that insertion order cannot be what saves us
        newest, middle, oldest = (self._schedule(m) for m in (1, 10, 100))
        self.env.flush_all()

        sent = []
        Schedule = type(self.env["mail.message.schedule"])
        real_unlink = Schedule.unlink

        def fake_send(records, default_notify_kwargs=None):
            sent.extend(records.ids)
            return real_unlink(records)

        with patch.object(Schedule, "_send_notifications", fake_send):
            self.env["mail.message.schedule"]._send_notifications_cron()

        self.assertEqual(
            sent,
            [oldest.id, middle.id],
            "the two oldest due schedules must be taken, in oldest-first order; "
            "the queue used to serve the newest and starve the backlog",
        )
        self.assertTrue(
            newest.exists(), "the newest schedule waits its turn on the next tick"
        )


@tagged("mail_alias", "post_install", "-at_install")
class TestCompanyMailAddressesFollowAliasDomainV16(MailCommon):
    """A company's bounce/catchall address must follow the alias it is built from.

    ``_compute_bounce`` and ``_compute_catchall`` declared ``alias_domain_id``
    -- which domain is selected -- but read ``alias_domain_id.bounce_email`` and
    ``.catchall_email``. Renaming an alias in Settings left the company holding
    the old address, and those are what outgoing mail carries as Return-Path and
    what inbound routing matches replies against.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.domain = cls.env["mail.alias.domain"].create(
            {
                "name": "v16.example.com",
                "bounce_alias": "bounce-v16",
                "catchall_alias": "catchall-v16",
            }
        )
        cls.company = cls.env["res.company"].create(
            {
                "name": "V16 Company",
                "alias_domain_id": cls.domain.id,
            }
        )

    def test_bounce_follows_an_alias_rename(self):
        self.assertEqual(self.company.bounce_email, "bounce-v16@v16.example.com")

        self.domain.bounce_alias = "bounce-v16-renamed"
        self.assertEqual(
            self.company.bounce_email,
            "bounce-v16-renamed@v16.example.com",
            "renaming the bounce alias must reach the company",
        )
        self.assertEqual(
            self.company.bounce_formatted,
            tools.formataddr((self.company.name, "bounce-v16-renamed@v16.example.com")),
        )

    def test_catchall_follows_an_alias_rename(self):
        self.assertEqual(self.company.catchall_email, "catchall-v16@v16.example.com")

        self.domain.catchall_alias = "catchall-v16-renamed"
        self.assertEqual(
            self.company.catchall_email,
            "catchall-v16-renamed@v16.example.com",
            "renaming the catchall alias must reach the company",
        )
        self.assertEqual(
            self.company.catchall_formatted,
            tools.formataddr(
                (self.company.name, "catchall-v16-renamed@v16.example.com")
            ),
        )
