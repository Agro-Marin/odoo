"""Regression tests for the thirteenth mail hardening audit.

Each test pins a defect reproduced end to end before being fixed, so a refactor
cannot silently reintroduce it.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from dateutil.relativedelta import MO, relativedelta

from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCommon

# Spread deliberately wider than 24h (UTC-11 .. UTC+14): at *any* instant this
# set holds at least two distinct local dates, so a "today" built on a single
# server-side date is always wrong for part of it. That is what makes the
# reschedule tests below deterministic without freezing the clock.
SPREAD_TIMEZONES = (
    "Pacific/Kiritimati",
    "Pacific/Auckland",
    "Europe/Brussels",
    "UTC",
    "America/New_York",
    "Pacific/Midway",
)


@tagged("-at_install", "post_install", "mail_hardening_v13")
class TestActivityRescheduleTimezone(MailCommon):
    """``action_reschedule_*`` must build the new deadline on the same "today"
    that ``_compute_state`` grades it against -- the *assignee's*, not the
    server process's local date.

    The defect: ``date.today()`` resolves to the UTC date (``_monkeypatches``
    forces ``TZ=UTC`` on the process), so every assignee was rescheduled onto
    UTC's calendar day rather than their own. An assignee east of UTC got
    "Today" written as a date their timezone had already left and the activity
    came straight back as **Overdue**; an assignee west of it got **Planned**.
    No exotic deployment needed -- it bites for hours of every day, for most of
    the world.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model_id = cls.env["ir.model"]._get_id("res.partner")
        cls.activity_type = cls.env.ref("mail.mail_activity_data_todo")
        cls.record = cls.env["res.partner"].create({"name": "activity target"})

    def _activity_for_tz(self, tz):
        """An activity whose assignee sits in ``tz``."""
        user = self.env["res.users"].create(
            {
                "name": f"assignee {tz}",
                "login": f"assignee_v13_{tz}",
                "email": f"{tz.replace('/', '_')}@test.example.com",
                "tz": tz,
                "group_ids": [(4, self.env.ref("base.group_user").id)],
            }
        )
        return self.env["mail.activity"].create(
            {
                "activity_type_id": self.activity_type.id,
                "res_model_id": self.model_id,
                "res_id": self.record.id,
                "user_id": user.id,
                "summary": f"probe {tz}",
            }
        )

    def _assignee_today(self, activity):
        return self.env["mail.activity"]._compute_today_for_tz(activity.user_id.tz)

    def test_reschedule_today_lands_on_state_today(self):
        """Rescheduling to Today must read back as ``state == "today"`` everywhere."""
        for tz in SPREAD_TIMEZONES:
            with self.subTest(tz=tz):
                activity = self._activity_for_tz(tz)
                activity.action_reschedule_today()
                activity.invalidate_recordset(["state"])
                self.assertEqual(
                    activity.date_deadline,
                    self._assignee_today(activity),
                    "the deadline must be the assignee's today, not the server's",
                )
                self.assertEqual(
                    activity.state,
                    "today",
                    "rescheduling to Today must not produce an overdue/planned activity",
                )

    def test_reschedule_tomorrow_lands_on_state_planned(self):
        """Tomorrow must be the assignee's today + 1, and read back as planned."""
        for tz in SPREAD_TIMEZONES:
            with self.subTest(tz=tz):
                activity = self._activity_for_tz(tz)
                activity.action_reschedule_tomorrow()
                activity.invalidate_recordset(["state"])
                self.assertEqual(
                    activity.date_deadline,
                    self._assignee_today(activity) + timedelta(days=1),
                )
                self.assertEqual(activity.state, "planned")

    def test_reschedule_nextweek_anchors_on_assignee_today(self):
        """Next week keeps its weekday rule, anchored on the assignee's today."""
        for tz in SPREAD_TIMEZONES:
            with self.subTest(tz=tz):
                activity = self._activity_for_tz(tz)
                activity.action_reschedule_nextweek()
                self.assertEqual(
                    activity.date_deadline,
                    self._assignee_today(activity)
                    + relativedelta(weeks=1, weekday=MO(-1)),
                )

    def test_reschedule_is_per_assignee_not_per_batch(self):
        """A multi-assignee recordset resolves one "today" per timezone.

        Rescheduling in batch previously stamped a single server date over every
        activity, so only assignees who happened to share the server's date got
        the right one.
        """
        activities = self.env["mail.activity"].browse()
        for tz in SPREAD_TIMEZONES:
            activities |= self._activity_for_tz(tz)

        activities.action_reschedule_today()
        activities.invalidate_recordset(["state"])

        for activity in activities:
            self.assertEqual(activity.date_deadline, self._assignee_today(activity))
            self.assertEqual(activity.state, "today")

        # The point of the test: the batch really did span several dates.
        self.assertGreater(
            len(set(activities.mapped("date_deadline"))),
            1,
            "the chosen timezones must straddle a date boundary for this to bite",
        )

    def test_reschedule_handles_an_unassigned_activity(self):
        """``user_id`` may be NULL whenever ``res_model`` is set (see the
        ``_check_user_id_is_set_if_model`` constraint), so the per-assignee
        grouping has to cope with an empty ``user_id`` -- whose ``tz`` is
        ``False``, i.e. the UTC fallback that ``_compute_state`` also uses."""
        activity = self.env["mail.activity"].create(
            {
                "activity_type_id": self.activity_type.id,
                "res_model_id": self.model_id,
                "res_id": self.record.id,
                "user_id": False,
                "summary": "unassigned",
            }
        )
        activity.action_reschedule_today()
        activity.invalidate_recordset(["state"])
        self.assertEqual(
            activity.date_deadline,
            self.env["mail.activity"]._compute_today_for_tz(False),
        )
        self.assertEqual(activity.state, "today")

    def test_reschedule_mixes_assigned_and_unassigned_in_one_batch(self):
        """One batch, two different notions of "today", neither crashing."""
        activities = self.env["mail.activity"].create(
            [
                {
                    "activity_type_id": self.activity_type.id,
                    "res_model_id": self.model_id,
                    "res_id": self.record.id,
                    "user_id": False,
                    "summary": "unassigned",
                }
            ]
        )
        activities |= self._activity_for_tz("Pacific/Kiritimati")
        activities.action_reschedule_today()
        activities.invalidate_recordset(["state"])
        for activity in activities:
            self.assertEqual(activity.state, "today")
            self.assertEqual(
                activity.date_deadline,
                self.env["mail.activity"]._compute_today_for_tz(activity.user_id.tz),
            )

    def test_reschedule_skips_archived_activities(self):
        """The ``filtered("active")`` guard survives the per-timezone grouping."""
        activity = self._activity_for_tz("Europe/Brussels")
        original = activity.date_deadline
        activity.active = False
        activity.action_reschedule_tomorrow()
        self.assertEqual(
            activity.date_deadline, original, "an archived activity is not rescheduled"
        )


@tagged("-at_install", "post_install", "mail_hardening_v13")
class TestNotifyByEmailBatchedCreate(MailCommon):
    """``_notify_thread_by_email`` creates every notification mail in one
    ``create()``, so each mail must still be paired with exactly the recipients
    whose values built it.

    The mails used to be created one chunk at a time, which made the pairing
    trivially local; batching them means the ``mail.notification`` rows are
    zipped back on afterwards, and a mis-zip would silently attribute a
    recipient's notification to another recipient's mail -- the failure that
    these tests exist to catch, since the mail count alone would look right.
    """

    def _partners_with_email_notif(self, count):
        users = self.env["res.users"].create(
            [
                {
                    "name": f"batch recipient {i}",
                    "login": f"batch_recipient_v13_{i}",
                    "email": f"batch_recipient_v13_{i}@test.example.com",
                    "notification_type": "email",
                    "group_ids": [(4, self.env.ref("base.group_user").id)],
                }
                for i in range(count)
            ]
        )
        return users.partner_id

    def test_every_recipient_is_notified_through_its_own_mail(self):
        """One notification per recipient, on a mail that really targets them."""
        # A batch size well under the recipient count, so the chunking that used
        # to drive one create() per chunk definitely happens.
        self.env["ir.config_parameter"].sudo().set_param("mail.batch_size", 3)
        partners = self._partners_with_email_notif(10)
        record = self.env["res.partner"].create({"name": "batched fanout target"})

        with self.mock_mail_gateway():
            message = record.message_post(
                body="batched",
                partner_ids=partners.ids,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )

        notifications = self.env["mail.notification"].search(
            [("mail_message_id", "=", message.id)]
        )
        self.assertEqual(
            notifications.res_partner_id,
            partners,
            "every recipient must get exactly one notification",
        )
        self.assertEqual(len(notifications), len(partners))

        for notification in notifications:
            self.assertIn(
                notification.res_partner_id,
                notification.mail_mail_id.recipient_ids,
                "a notification must point at the mail that actually carries it",
            )

    def test_chunking_still_splits_at_the_batch_size(self):
        """Batching the creates must not merge the recipient chunks themselves."""
        self.env["ir.config_parameter"].sudo().set_param("mail.batch_size", 3)
        partners = self._partners_with_email_notif(7)
        record = self.env["res.partner"].create({"name": "chunk target"})

        with self.mock_mail_gateway():
            message = record.message_post(
                body="chunked",
                partner_ids=partners.ids,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )

        mails = (
            self.env["mail.notification"]
            .search([("mail_message_id", "=", message.id)])
            .mail_mail_id
        )
        self.assertEqual(len(mails), 3, "7 recipients at batch size 3 -> 3 mails")
        self.assertEqual(
            sorted(len(mail.recipient_ids) for mail in mails),
            [1, 3, 3],
            "chunks keep their own recipients rather than collapsing into one mail",
        )


@tagged("-at_install", "post_install", "mail_hardening_v13")
class TestActivityTodayFallbackIsUTC(MailCommon):
    """With no assignee timezone, "today" must be UTC everywhere.

    ``mail.activity.mixin`` resolves the same notion in SQL as
    ``COALESCE(mail_activity.user_tz, 'utc')`` (``_search_activity_state``,
    ``_read_group_activity_state``), so the Python fallback has to be UTC too.

    Not a live defect: the old spelling, ``date.today()``, is the *process's*
    local date, and it matched only because ``odoo/_monkeypatches`` forces
    ``TZ=UTC`` at boot. These tests pin the contract directly, so that neither
    dropping that monkeypatch nor reading this code as "the server's local
    date" can quietly split the compute from the search.
    """

    def test_no_timezone_falls_back_to_utc(self):
        self.assertEqual(
            self.env["mail.activity"]._compute_today_for_tz(False),
            datetime.now(UTC).date(),
        )

    def test_fallback_ignores_the_server_local_date(self):
        """Pinned against a process clock whose local date is *not* the UTC one.

        ``TZ=UTC`` is patched away here on purpose: that is the only way to tell
        "UTC" apart from "whatever the process calls today", which is exactly
        the distinction this fallback has to get right.
        """
        instant = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)  # UTC-6 server: Dec 31

        class _Datetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

        class _Date(date):
            @classmethod
            def today(cls):
                return date(2025, 12, 31)  # what a UTC-6 server would report

        module = "odoo.addons.mail.models.mail_activity"
        with (
            patch(f"{module}.datetime", _Datetime),
            patch(f"{module}.date", _Date),
        ):
            self.assertEqual(
                self.env["mail.activity"]._compute_today_for_tz(False),
                date(2026, 1, 1),
                "the fallback must be UTC's date, not the server's local date",
            )

    def test_compute_and_search_agree_without_a_timezone(self):
        """End to end: the state compute and the ``activity_state`` search agree.

        This is the user-visible half of the same defect -- a record listed as
        rotting-free by the filter while its own badge said otherwise.
        """
        user = self.env["res.users"].create(
            {
                "name": "no tz assignee",
                "login": "no_tz_assignee_v13",
                "email": "notz@test.example.com",
                "tz": False,
                "group_ids": [(4, self.env.ref("base.group_user").id)],
            }
        )
        record = self.env["res.partner"].create({"name": "no tz target"})
        activity = self.env["mail.activity"].create(
            {
                "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
                "res_model_id": self.env["ir.model"]._get_id("res.partner"),
                "res_id": record.id,
                "user_id": user.id,
                "date_deadline": datetime.now(UTC).date(),
            }
        )
        activity.invalidate_recordset(["state"])
        self.assertEqual(activity.state, "today")

        found = self.env["res.partner"].search(
            [("id", "=", record.id), ("activity_state", "=", "today")]
        )
        self.assertEqual(
            found,
            record,
            "the activity_state search must classify the record the same way "
            "mail.activity.state does",
        )
