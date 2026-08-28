"""Regression tests for calendar defects fixed in the correctness/privacy pass.

Each test states an invariant the module relies on and that a specific defect
used to break:

- private events must not be readable through search domains, ``order`` or
  group-by aggregates (only through the masked read path);
- ``create`` must return events in the caller's order;
- making a plain event recurrent must build the recurrence whatever the
  ``recurrence_update`` policy;
- ``end_type='forever'`` must survive being stored;
- a notification must not copy a template attachment for an attendee it never
  mails;
- building a recurrence must not mutate its stored ``count`` column;
- moving events must un-accept their organizers, one write or many;
- moving a whole recurrence must tell its attendees the date changed;
- deleting the tail of a recurrence must trim the rule, not just the rows;
- the .ics of a recurring event must carry one well-formed RRULE;
- ``unavailable_partner_ids`` must not cost a query per event.
"""

from datetime import datetime

from dateutil.relativedelta import relativedelta

from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestCalendarPrivacyLeaks(TransactionCase):
    """`_fetch_query` masks private events field-by-field, but a domain is
    evaluated in SQL against the raw columns. Everything the fetch path hides
    is therefore recoverable through `search`/`search_count`/`order`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = new_test_user(cls.env, login="owner_priv", groups="base.group_user")
        cls.snoop = new_test_user(cls.env, login="snoop_priv", groups="base.group_user")
        cls.event = (
            cls.env["calendar.event"]
            .with_user(cls.owner)
            .create(
                {
                    "name": "Acquisition of NewCo",
                    "start": "2026-09-01 10:00:00",
                    "stop": "2026-09-01 11:00:00",
                    "privacy": "private",
                    "location": "Lawyer office",
                    "description": "<p>price is 4.5M</p>",
                    "partner_ids": [(6, 0, cls.owner.partner_id.ids)],
                }
            )
        )
        cls.env.flush_all()

    def _as_snoop(self):
        return self.env["calendar.event"].with_user(self.snoop)

    def test_private_name_is_masked_on_read(self):
        """Baseline: the masking the module already implements."""
        self.env.invalidate_all()
        self.assertEqual(self._as_snoop().browse(self.event.id).name, "Busy")

    def test_private_name_not_searchable(self):
        """A masked field must not be usable as a search oracle."""
        self.assertFalse(
            self._as_snoop().search([("id", "=", self.event.id), ("name", "ilike", "NewCo")]),
            "the name of an uninvited user's private event must not be searchable",
        )

    def test_private_name_not_recoverable_char_by_char(self):
        """`search_count` alone must not spell out a masked field."""
        recovered = ""
        alphabet = "ACINQTZabcdefghilmnoqrstuvw "
        for _position in range(len(self.event.name)):
            for char in alphabet:
                if self._as_snoop().search_count(
                    [("id", "=", self.event.id), ("name", "=like", f"{recovered}{char}%")]
                ):
                    recovered += char
                    break
            else:
                break
        self.assertNotEqual(
            recovered,
            self.event.name,
            "the full name of a private event was recovered through search_count alone",
        )

    def test_private_location_not_searchable(self):
        self.assertFalse(
            self._as_snoop().search(
                [("id", "=", self.event.id), ("location", "=", "Lawyer office")]
            ),
            "the location of an uninvited user's private event must not be searchable",
        )

    def test_private_description_not_searchable(self):
        self.assertFalse(
            self._as_snoop().search(
                [("id", "=", self.event.id), ("description", "ilike", "4.5M")]
            ),
            "the description of an uninvited user's private event must not be searchable",
        )

    def test_private_attendees_not_searchable(self):
        self.assertFalse(
            self._as_snoop().search(
                [("id", "=", self.event.id), ("partner_ids", "in", self.owner.partner_id.ids)]
            ),
            "the attendee list of an uninvited user's private event must not be searchable",
        )


@tagged("post_install", "-at_install")
class TestCalendarCreateOrdering(TransactionCase):
    """`create()` splits vals_list into non-recurring then recurring and
    `super().create()`s them separately, so the returned recordset no longer
    matches the caller's order -- yet two `zip(events, vals_list)` loops in the
    same method assume it does.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="order_user", groups="base.group_user")

    def test_create_preserves_vals_list_order(self):
        vals_list = [
            {
                "name": "REC-1",
                "start": "2026-10-05 10:00:00",
                "stop": "2026-10-05 11:00:00",
                "recurrency": True,
                "rrule_type": "daily",
                "end_type": "count",
                "count": 2,
            },
            {"name": "PLAIN-2", "start": "2026-10-06 10:00:00", "stop": "2026-10-06 11:00:00"},
            {
                "name": "REC-3",
                "start": "2026-10-07 10:00:00",
                "stop": "2026-10-07 11:00:00",
                "recurrency": True,
                "rrule_type": "daily",
                "end_type": "count",
                "count": 2,
            },
            {"name": "PLAIN-4", "start": "2026-10-08 10:00:00", "stop": "2026-10-08 11:00:00"},
        ]
        events = self.env["calendar.event"].with_user(self.user).create(vals_list)
        self.assertEqual(
            events.mapped("name"),
            [vals["name"] for vals in vals_list],
            "create() must return events in the order of vals_list; the two "
            "zip(events, vals_list) loops inside create() rely on it",
        )


@tagged("post_install", "-at_install")
class TestCalendarRecurrenceUpdateOnPlainEvent(TransactionCase):
    """Turning a plain event into a recurring one must either build the
    recurrence or refuse; it must not drop the rrule parameters silently.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="recur_user", groups="base.group_user")

    def _make_recurrent(self, recurrence_update):
        event = (
            self.env["calendar.event"]
            .with_user(self.user)
            .create(
                {
                    "name": f"become-recurrent-{recurrence_update}",
                    "start": "2026-11-02 10:00:00",
                    "stop": "2026-11-02 11:00:00",
                }
            )
        )
        self.env.flush_all()
        event.write(
            {
                "recurrency": True,
                "rrule_type": "weekly",
                "mon": True,
                "end_type": "count",
                "count": 5,
                "recurrence_update": recurrence_update,
            }
        )
        self.env.flush_all()
        return event

    def test_recurrence_built_whatever_the_update_policy(self):
        for policy in ("self_only", "future_events", "all_events"):
            with self.subTest(recurrence_update=policy):
                event = self._make_recurrent(policy)
                self.assertTrue(
                    event.recurrence_id,
                    f"recurrence_update={policy!r} silently discarded the rrule "
                    "parameters and left recurrency=True with no recurrence",
                )
                self.assertEqual(len(event.recurrence_id.calendar_event_ids), 5)


@tagged("post_install", "-at_install")
class TestCalendarRecurrenceForever(TransactionCase):
    """`end_type='forever'` must survive being stored."""

    def test_forever_survives_a_flush(self):
        recurrence = self.env["calendar.recurrence"].create(
            {"rrule_type": "weekly", "mon": True, "end_type": "forever", "interval": 1}
        )
        self.env.flush_all()
        recurrence.invalidate_recordset()
        self.assertEqual(
            recurrence.end_type,
            "forever",
            "_compute_rrule serialises 'forever' as COUNT=720 and _inverse_rrule "
            "parses it back as end_type='count', losing the user's choice",
        )


@tagged("post_install", "-at_install")
class TestCalendarNotificationAttachments(TransactionCase):
    """`_notify_attendees` copies the template attachments once per attendee in
    `self`, but only attendees that are actually mailed consume a copy.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="notify_user", groups="base.group_user")

    def test_no_orphan_attachment_copies(self):
        # four partners can be mailed, four cannot (no email address)
        partners = self.env["res.partner"].create(
            [
                {"name": f"P{index}", "email": f"p{index}@example.com" if index < 4 else False}
                for index in range(8)
            ]
        )
        template = self.env.ref("calendar.calendar_template_meeting_invitation")
        template.attachment_ids = [
            (
                0,
                0,
                {"name": "agenda.pdf", "datas": b"JVBERi0=", "mimetype": "application/pdf"},
            )
        ]
        event = (
            self.env["calendar.event"]
            .with_user(self.user)
            .with_context(no_mail_to_attendees=True)
            .create(
                {
                    "name": "Big meeting",
                    "start": "2026-12-01 10:00:00",
                    "stop": "2026-12-01 11:00:00",
                    "partner_ids": [(6, 0, partners.ids)],
                }
            )
        )
        self.env.flush_all()

        highest = self.env["ir.attachment"].search([], order="id desc", limit=1).id
        event.attendee_ids.with_context(no_mail_to_attendees=False)._notify_attendees(
            template, force_send=False
        )
        self.env.flush_all()

        created = self.env["ir.attachment"].search(
            [("id", ">", highest), ("name", "=", "agenda.pdf")]
        )
        referenced = (
            self.env["mail.message"]
            .search([("model", "=", "calendar.event"), ("res_id", "=", event.id)])
            .attachment_ids
        )
        self.assertFalse(
            created - referenced,
            "attachment copies were made for attendees that are never mailed; "
            f"{len(created - referenced)} of {len(created)} copies are orphaned",
        )


@tagged("post_install", "-at_install")
class TestCalendarRangeCalculation(TransactionCase):
    """`_range_calculation` inflates the occurrence count when start-of-period
    falls before the base event, but it must do so without mutating the stored
    `count` column (it used to write an inflated value and write it back).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="range_user", groups="base.group_user")

    def test_count_preserved_and_future_occurrences_complete(self):
        # 2026-11-04 is a Wednesday; the weekly rule also fires on Monday, whose
        # week-start is before the base event, so the naive generation drops the
        # pre-start occurrence and the inflation path runs.
        event = (
            self.env["calendar.event"]
            .with_user(self.user)
            .with_context(no_mail_to_attendees=True)
            .create(
                {
                    "name": "mid-week weekly",
                    "start": "2026-11-04 10:00:00",
                    "stop": "2026-11-04 11:00:00",
                }
            )
        )
        self.env.flush_all()
        event.write(
            {
                "recurrency": True,
                "rrule_type": "weekly",
                "mon": True,
                "wed": True,
                "fri": True,
                "end_type": "count",
                "count": 6,
            }
        )
        self.env.flush_all()
        recurrence = event.recurrence_id
        occurrences = recurrence.calendar_event_ids
        self.assertEqual(
            recurrence.count,
            6,
            "_range_calculation must not leave an inflated value in the stored count",
        )
        self.assertEqual(
            len(occurrences),
            6,
            "the requested number of future occurrences must be materialised",
        )
        self.assertTrue(
            all(occ.start.date() >= event.start.date() for occ in occurrences),
            "no occurrence may fall before the base event",
        )


@tagged("post_install", "-at_install")
class TestCalendarPopoverDeleteWizard(TransactionCase):
    """The delete wizard's action_delete must honour the recurrence_update
    vocabulary ('self_only'/'future_events'/'all_events') that the calendar form
    passes through action_unlink_event, not only the popover's own
    'one'/'next'/'all'. It used to no-op on the former, so deleting "this and
    following"/"all events" from the form silently deleted nothing.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="del_user", groups="base.group_user")

    def _recurrence(self):
        event = (
            self.env["calendar.event"]
            .with_user(self.user)
            .with_context(no_mail_to_attendees=True)
            .create({"name": "r", "start": "2027-01-04 10:00:00", "stop": "2027-01-04 11:00:00"})
        )
        self.env.flush_all()
        event.write(
            {"recurrency": True, "rrule_type": "daily", "end_type": "count", "count": 5}
        )
        self.env.flush_all()
        return event

    def _delete_with(self, deletion_type):
        event = self._recurrence()
        recurrence = event.recurrence_id
        started = len(recurrence.calendar_event_ids)
        wizard = (
            self.env["calendar.popover.delete.wizard"]
            .with_user(self.user)
            .with_context(default_recurrence=deletion_type)
            .create({"calendar_event_id": event.id})
        )
        wizard.action_delete()
        self.env.flush_all()
        remaining = (
            self.env["calendar.event"]
            .with_context(active_test=False)
            .search_count([("recurrence_id", "=", recurrence.id)])
            if recurrence.exists()
            else 0
        )
        return started, remaining

    def test_future_events_deletes_from_form_vocabulary(self):
        started, remaining = self._delete_with("future_events")
        self.assertLess(remaining, started, "'future_events' must delete the current and later occurrences")

    def test_all_events_deletes_from_form_vocabulary(self):
        _started, remaining = self._delete_with("all_events")
        self.assertEqual(remaining, 0, "'all_events' must delete the whole recurrence")

    def test_next_and_all_still_work(self):
        _, remaining_next = self._delete_with("next")
        self.assertEqual(remaining_next, 0, "'next' on a daily-from-base recurrence removes all following")
        _, remaining_all = self._delete_with("all")
        self.assertEqual(remaining_all, 0, "'all' must delete the whole recurrence")


@tagged("post_install", "-at_install")
class TestCalendarAttendeeCounts(TransactionCase):
    """The five counts must come from one source, so they always add up.

    `awaiting_count` used to be ``guests - accepted - declined - tentative``
    and could go negative; it is now a count of the unanswered. The headline
    `attendees_count` used to be `len(partner_ids)` while the four answer
    counts came from `attendee_ids` -- two sources, and a many2many read drops
    archived records while the attendee rows survive, so deactivating a contact
    made an event report fewer guests than answers.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.organizer = new_test_user(cls.env, "count_organizer", groups="base.group_user")
        cls.guest = new_test_user(cls.env, "count_guest", groups="base.group_user")
        cls.event = cls.env["calendar.event"].with_user(cls.organizer).create({
            "name": "counted",
            "start": "2035-04-01 10:00:00",
            "stop": "2035-04-01 11:00:00",
            "partner_ids": [(6, 0, [cls.organizer.partner_id.id, cls.guest.partner_id.id])],
        })

    def test_counts_add_up_for_a_normal_event(self):
        self.assertEqual(self.event.attendees_count, 2)
        self.assertEqual(self.event.accepted_count, 1, "the organizer is accepted")
        self.assertEqual(self.event.awaiting_count, 1, "the guest has not answered")
        self._assert_counts_add_up()

    def _assert_counts_add_up(self):
        answered = (
            self.event.accepted_count
            + self.event.declined_count
            + self.event.tentative_count
            + self.event.awaiting_count
        )
        self.assertEqual(
            self.event.attendees_count,
            answered,
            "the headline count and the breakdown must describe the same people",
        )
        self.assertGreaterEqual(
            self.event.awaiting_count, 0,
            "awaiting is a count of unanswered attendees, not a subtraction",
        )

    def test_awaiting_never_goes_negative(self):
        # An attendee row with no partner link: the state the subtraction could
        # not survive.
        extra = new_test_user(self.env, "count_extra", groups="base.group_user")
        self.env["calendar.attendee"].sudo().create({
            "event_id": self.event.id,
            "partner_id": extra.partner_id.id,
            "state": "accepted",
        })
        self.event.invalidate_recordset()
        self.assertEqual(self.event.attendees_count, 3)
        self.assertEqual(self.event.accepted_count, 2)
        self.assertEqual(self.event.awaiting_count, 1)
        self._assert_counts_add_up()

    def test_an_archived_contact_is_still_a_guest(self):
        """A many2many read drops archived records; the attendee row survives.

        Counting the guests from `partner_ids` and the answers from
        `attendee_ids` therefore disagreed the moment anybody deactivated a
        contact: the event read "1 guest, 2 answers".
        """
        # A plain contact, not a user's partner: a partner backing an active
        # user refuses to be archived at all.
        contact = self.env["res.partner"].create({"name": "Deactivated Guest"})
        self.event.write({"partner_ids": [(4, contact.id)]})
        self.env.flush_all()
        self.assertEqual(self.event.attendees_count, 3)

        contact.action_archive()
        self.event.invalidate_recordset()
        self.assertEqual(
            len(self.event.partner_ids), 2, "the m2m read drops the archived one"
        )
        self.assertEqual(
            self.event.attendees_count, 3, "but they are still on the invitation"
        )
        self._assert_counts_add_up()


@tagged("post_install", "-at_install")
class TestAlarmNotifyResponsible(TransactionCase):
    """"Notify Responsible" is only meaningful for channels that honour it.

    The base module used to force the flag off for `alarm_type in ('email',
    'notification')` -- a hardcoded list of its own two types, negated. It read
    as "not for these two" but meant "for anything that is not these two", so
    every alarm type added later was opted in by default without anybody
    deciding so.
    """

    def test_the_base_channels_never_offer_it(self):
        # Asserted as an exclusion, not as an empty set: which channels opt in
        # depends on which of calendar_sms / whatsapp_calendar is installed, and
        # a test that pinned the whole set would fail on a fuller database
        # rather than on a regression.
        responsible_aware = self.env["calendar.alarm"]._get_responsible_aware_alarm_types()
        self.assertNotIn("email", responsible_aware)
        self.assertNotIn("notification", responsible_aware)

    def test_the_flag_is_cleared_for_a_channel_that_does_not_honour_it(self):
        alarm = self.env["calendar.alarm"].new({
            "name": "a", "alarm_type": "email", "duration": 1, "interval": "hours",
            "notify_responsible": True,
        })
        alarm._onchange_duration_interval()
        self.assertFalse(alarm.notify_responsible)
        self.assertFalse(alarm.notify_responsible_available)


@tagged("post_install", "-at_install")
class TestCalendarOrganizerAnswerReset(TransactionCase):
    """Moving somebody else's event un-accepts its organizer.

    `_write_reset_organizer_answer` compared every candidate attendee against
    `self.user_id.partner_id` -- a many2one read off the whole recordset, which
    is the *union* of the organizers' partners. A union never equals the single
    partner on the left, so a write touching two events with different
    organizers reset neither, silently. The single-event case passed only
    because a one-element union is that one element.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.org_a = new_test_user(cls.env, login="reset_org_a", groups="base.group_user")
        cls.org_b = new_test_user(cls.env, login="reset_org_b", groups="base.group_user")
        cls.mover = new_test_user(cls.env, login="reset_mover", groups="base.group_user")

    def _event_for(self, organizer):
        event = (
            self.env["calendar.event"]
            .with_context(no_mail_to_attendees=True)
            .create({
                "name": "m",
                "start": "2030-03-01 10:00:00",
                "stop": "2030-03-01 11:00:00",
                "user_id": organizer.id,
                "partner_ids": [
                    (6, 0, (organizer.partner_id + self.mover.partner_id).ids)
                ],
            })
        )
        self._organizer_attendee(event).state = "accepted"
        self.env.flush_all()
        return event

    def _organizer_attendee(self, event):
        return event.attendee_ids.filtered(
            lambda att: att.partner_id == event.user_id.partner_id
        )

    def test_reset_on_a_single_event(self):
        event = self._event_for(self.org_a)
        event.with_user(self.mover).with_context(
            no_mail_to_attendees=True
        ).write({"start": "2030-03-02 10:00:00", "stop": "2030-03-02 11:00:00"})
        self.assertEqual(self._organizer_attendee(event).state, "needsAction")

    def test_reset_on_several_events_with_different_organizers(self):
        event_a = self._event_for(self.org_a)
        event_b = self._event_for(self.org_b)
        (event_a + event_b).with_user(self.mover).with_context(
            no_mail_to_attendees=True
        ).write({"start": "2030-03-02 10:00:00", "stop": "2030-03-02 11:00:00"})
        self.assertEqual(self._organizer_attendee(event_a).state, "needsAction")
        self.assertEqual(self._organizer_attendee(event_b).state, "needsAction")

    def test_the_mover_s_own_answer_survives(self):
        """The reset is for events moved *by somebody else*."""
        event = self._event_for(self.org_a)
        event.with_user(self.org_a).with_context(
            no_mail_to_attendees=True
        ).write({"start": "2030-03-02 10:00:00", "stop": "2030-03-02 11:00:00"})
        self.assertEqual(self._organizer_attendee(event).state, "accepted")


@tagged("post_install", "-at_install")
class TestCalendarRecurrenceDateChangeNotification(TransactionCase):
    """Moving a whole series must tell its attendees.

    `_write_notify_attendees` read "start" out of `write`'s own `vals`, which
    the recurrence branches empty into `time_values` before it runs -- so the
    "all events" and "this and following" paths reached the test with no
    "start" left and returned early. Only a single-occurrence move notified
    anybody, and the caller passing `update_recurrence` down purely to *unset*
    `calendar_template_ignore_recurrence` shows the branch was meant to run.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.organizer = new_test_user(
            cls.env, login="notif_organizer", groups="base.group_user"
        )
        cls.guest = new_test_user(
            cls.env, login="notif_guest", groups="base.group_user"
        )

    def _series(self, start="2030-04-01 10:00:00", stop="2030-04-01 11:00:00"):
        event = (
            self.env["calendar.event"]
            .with_user(self.organizer)
            .with_context(no_mail_to_attendees=True)
            .create({
                "name": "Series",
                "start": start,
                "stop": stop,
                "user_id": self.organizer.id,
                "partner_ids": [
                    (6, 0, (self.organizer.partner_id + self.guest.partner_id).ids)
                ],
                "recurrency": True,
                "rrule_type": "weekly",
                "mon": True,
                "end_type": "count",
                "count": 4,
                "event_tz": "UTC",
            })
        )
        self.env.flush_all()
        # Drop `no_mail_to_attendees`: it rides the recordset the create
        # returned, and every write below would otherwise silently mail nobody
        # for that reason rather than for the one under test.
        return event.with_context(no_mail_to_attendees=False)

    def _mails_sent_by(self, action):
        before = self.env["mail.mail"].search([])
        action()
        self.env.flush_all()
        return self.env["mail.mail"].search([]) - before

    def test_moving_a_single_occurrence_notifies(self):
        """Baseline: the path that already worked."""
        event = self._series()
        mails = self._mails_sent_by(
            lambda: event.with_user(self.organizer).write({
                "recurrence_update": "self_only",
                "start": "2030-04-01 14:00:00",
                "stop": "2030-04-01 15:00:00",
            })
        )
        self.assertTrue(mails, "a moved occurrence must be announced")

    def test_moving_the_whole_series_notifies(self):
        event = self._series()
        mails = self._mails_sent_by(
            lambda: event.with_user(self.organizer).write({
                "recurrence_update": "all_events",
                "start": "2030-04-01 14:00:00",
                "stop": "2030-04-01 15:00:00",
            })
        )
        self.assertTrue(mails, "a moved series must be announced")

    def test_the_series_is_announced_once_per_attendee(self):
        """Not once per occurrence: the template describes the recurrence."""
        event = self._series()
        mails = self._mails_sent_by(
            lambda: event.with_user(self.organizer).write({
                "recurrence_update": "all_events",
                "start": "2030-04-01 14:00:00",
                "stop": "2030-04-01 15:00:00",
            })
        )
        # The organizer is the one writing, so `_should_notify_attendee`
        # excludes them; the guest is the single recipient.
        self.assertEqual(len(mails), 1)

    def test_the_announcement_describes_the_recurrence(self):
        """Not just "the date moved": the whole point of the branch.

        `_write_notify_attendees` unsets `calendar_template_ignore_recurrence`
        when the write rewrote the series, and the template renders the
        repetition rule from it.
        """
        event = self._series()
        mails = self._mails_sent_by(
            lambda: event.with_user(self.organizer).write({
                "recurrence_update": "all_events",
                "start": "2030-04-01 14:00:00",
                "stop": "2030-04-01 15:00:00",
            })
        )
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails.recipient_ids, self.guest.partner_id)
        self.assertIn("Date Updated", mails.body_html)
        self.assertIn("Every", mails.body_html, "the recurrence must be described")

    def test_this_and_following_announces_once_not_twice(self):
        """`_update_future_events` writes on `self` again, carrying the new start.

        That nested `write` announces the move on its own. Letting the outer
        `write` announce it too sent every attendee the same mail twice --
        which is what happened the moment the outer branch was made reachable,
        and is why the inner write skips notification the way
        `_rewrite_recurrence`'s already did.
        """
        event = self._series()
        occurrences = event.recurrence_id.calendar_event_ids.sorted("start")
        middle = occurrences[2].with_context(no_mail_to_attendees=False)
        mails = self._mails_sent_by(
            lambda: middle.with_user(self.organizer).write({
                "recurrence_update": "future_events",
                "start": "2030-04-15 18:00:00",
                "stop": "2030-04-15 19:00:00",
            })
        )
        self.assertEqual(len(mails), 1, "one announcement per attendee, not two")
        self.assertEqual(mails.recipient_ids, self.guest.partner_id)

    def test_a_new_attendee_is_invited_and_the_old_one_told_the_date(self):
        """One write that both moves the series and adds somebody.

        The two templates are chosen per attendee, and neither must reach the
        other's recipient.
        """
        event = self._series()
        newcomer = new_test_user(
            self.env, login="notif_newcomer", groups="base.group_user"
        )
        mails = self._mails_sent_by(
            lambda: event.with_user(self.organizer).write({
                "recurrence_update": "all_events",
                "start": "2030-04-01 16:00:00",
                "stop": "2030-04-01 17:00:00",
                "partner_ids": [(6, 0, (
                    self.organizer.partner_id
                    + self.guest.partner_id
                    + newcomer.partner_id
                ).ids)],
            })
        )
        by_recipient = {mail.recipient_ids: mail.subject for mail in mails}
        self.assertEqual(len(mails), 2, by_recipient)
        self.assertIn("Invitation", by_recipient[newcomer.partner_id])
        self.assertIn("Date updated", by_recipient[self.guest.partner_id])

    def test_moving_a_series_into_the_past_notifies_nobody(self):
        """The future-only guard still holds on the recurrence path."""
        event = self._series(start="2020-01-06 10:00:00", stop="2020-01-06 11:00:00")
        mails = self._mails_sent_by(
            lambda: event.with_user(self.organizer).write({
                "recurrence_update": "all_events",
                "start": "2020-01-06 14:00:00",
                "stop": "2020-01-06 15:00:00",
            })
        )
        self.assertFalse(mails)


@tagged("post_install", "-at_install")
class TestCalendarMassDeletionTrimsTheRule(TransactionCase):
    """`action_mass_deletion('future_events')` must trim the recurrence too.

    It selected the occurrences from this one onward and unlinked the rows,
    leaving the rule still claiming its original `count` with no `until`. The
    next `_apply_recurrence` -- any later edit of the series reaches one --
    recreated every occurrence that had just been deleted.
    `action_mass_archive`, the sibling it mirrors, already trims via `_stop_at`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="trim_user", groups="base.group_user")

    def _series(self):
        event = (
            self.env["calendar.event"]
            .with_user(self.user)
            .with_context(no_mail_to_attendees=True)
            .create({
                "name": "Series",
                "start": "2030-06-03 10:00:00",
                "stop": "2030-06-03 11:00:00",
                "user_id": self.user.id,
                "partner_ids": [(6, 0, self.user.partner_id.ids)],
                "recurrency": True,
                "rrule_type": "weekly",
                "mon": True,
                "end_type": "count",
                "count": 4,
                "event_tz": "UTC",
            })
        )
        self.env.flush_all()
        return event

    def test_deleted_occurrences_do_not_come_back(self):
        event = self._series()
        recurrence = event.recurrence_id
        occurrences = recurrence.calendar_event_ids.sorted("start")
        self.assertEqual(len(occurrences), 4)

        occurrences[2].action_mass_deletion("future_events")
        self.env.flush_all()
        remaining = len(recurrence.calendar_event_ids)
        self.assertEqual(remaining, 2)

        recurrence._apply_recurrence()
        self.env.flush_all()
        self.assertEqual(
            len(recurrence.calendar_event_ids),
            remaining,
            "re-applying the rule must not resurrect the deleted occurrences",
        )

    def test_an_archived_occurrence_is_deleted_with_the_rest(self):
        """`_get_events_from` filtered `active` twice -- once reading the
        one2many, once in the search -- so an archived occurrence after the cut
        point was neither detached nor deleted. It survived pointing at a
        recurrence whose trimmed rule now ended before it started.
        """
        event = self._series()
        recurrence = event.recurrence_id
        occurrences = recurrence.calendar_event_ids.sorted("start")
        ids = occurrences.ids
        occurrences[3].with_context(dont_notify=True).write({"active": False})
        self.env.flush_all()

        occurrences[1].action_mass_deletion("future_events")
        self.env.flush_all()

        survivors = (
            self.env["calendar.event"]
            .with_context(active_test=False)
            .search([("id", "in", ids)])
        )
        self.assertEqual(
            survivors.ids,
            ids[:1],
            "only the occurrence before the cut point may survive, archived or not",
        )

    def test_the_rule_is_trimmed_to_end_before_the_deleted_occurrence(self):
        event = self._series()
        recurrence = event.recurrence_id
        occurrences = recurrence.calendar_event_ids.sorted("start")
        cut = occurrences[2]
        cut_date = cut.start.date()

        cut.action_mass_deletion("future_events")
        self.env.flush_all()
        self.assertEqual(recurrence.end_type, "end_date")
        self.assertTrue(recurrence.until)
        self.assertLess(recurrence.until, cut_date)


@tagged("post_install", "-at_install")
class TestCalendarIcsRecurrence(TransactionCase):
    """The .ics of a recurring event must carry one well-formed RRULE.

    `calendar.recurrence.rrule` stores dateutil's whole rendering,
    ``DTSTART:...\\nRRULE:...``, whose DTSTART is `now()` at compute time and
    means nothing. Assigning that block to an RRULE property emitted two RRULE
    lines, the first ``RRULE:DTSTART:<timestamp>``, and a client reading the
    invitation took a bare DTSTART as the rule.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="ics_user", groups="base.group_user")

    def _ics_lines(self, event):
        content = event._get_ics_file().get(event.id)
        self.assertTrue(content, "vobject is required for this test")
        # Unfold: iCalendar wraps long lines with a leading space.
        return content.decode().replace("\r\n ", "").replace("\n ", "").splitlines()

    def test_a_recurring_event_exports_exactly_one_rrule(self):
        event = (
            self.env["calendar.event"]
            .with_user(self.user)
            .with_context(no_mail_to_attendees=True)
            .create({
                "name": "ICS Series",
                "start": "2030-06-03 10:00:00",
                "stop": "2030-06-03 11:00:00",
                "user_id": self.user.id,
                "partner_ids": [(6, 0, self.user.partner_id.ids)],
                "recurrency": True,
                "rrule_type": "weekly",
                "mon": True,
                "end_type": "count",
                "count": 4,
                "event_tz": "UTC",
            })
        )
        self.env.flush_all()
        rrule_lines = [
            line for line in self._ics_lines(event) if line.startswith("RRULE:")
        ]
        self.assertEqual(len(rrule_lines), 1, rrule_lines)
        self.assertNotIn("DTSTART", rrule_lines[0])
        self.assertIn("FREQ=WEEKLY", rrule_lines[0])

    def _series(self):
        event = (
            self.env["calendar.event"]
            .with_user(self.user)
            .with_context(no_mail_to_attendees=True)
            .create({
                "name": "ICS Series",
                "start": "2032-03-01 10:00:00",
                "stop": "2032-03-01 11:00:00",
                "user_id": self.user.id,
                "partner_ids": [(6, 0, self.user.partner_id.ids)],
                "recurrency": True,
                "rrule_type": "daily",
                "end_type": "count",
                "count": 3,
                "event_tz": "UTC",
            })
        )
        self.env.flush_all()
        return event

    def _rrule_lines(self, event):
        return [line for line in self._ics_lines(event) if line.startswith("RRULE:")]

    def test_only_the_base_event_declares_the_series(self):
        """Every occurrence is already its own row; an RRULE asks the client to
        generate the siblings again. Three daily occurrences each declaring
        ``COUNT=3`` is nine events in the reader's calendar."""
        occurrences = self._series().recurrence_id.calendar_event_ids.sorted("start")
        self.assertEqual(len(occurrences), 3)
        self.assertEqual(len(self._rrule_lines(occurrences[0])), 1)
        for occurrence in occurrences[1:]:
            self.assertFalse(
                self._rrule_lines(occurrence),
                "a non-base occurrence must not re-declare the recurrence",
            )

    def test_a_reminder_does_not_declare_the_series(self):
        """`calendar_template_ignore_recurrence` is the module's own way of
        saying "this mail is about this occurrence" -- `_send_reminder` sets it
        for every reminder. The .ics must agree with the body."""
        base = self._series().recurrence_id.base_event_id
        self.assertTrue(self._rrule_lines(base))
        self.assertFalse(
            self._rrule_lines(
                base.with_context(calendar_template_ignore_recurrence=True)
            )
        )

    def test_a_reminder_triggers_before_the_event_not_after(self):
        """`TRIGGER;RELATED=START` with a positive duration means *after* the
        start (RFC 5545 3.8.6.3). Every reminder was exported with a positive
        one, so "remind me an hour before" reached the reader's calendar as
        `PT1H` -- an hour *late*, every time.
        """
        alarm = self.env["calendar.alarm"].create({
            "name": "1h before",
            "alarm_type": "notification",
            "interval": "hours",
            "duration": 1,
        })
        event = (
            self.env["calendar.event"]
            .with_user(self.user)
            .with_context(no_mail_to_attendees=True)
            .create({
                "name": "Alarmed",
                "start": "2033-05-05 10:00:00",
                "stop": "2033-05-05 11:00:00",
                "user_id": self.user.id,
                "partner_ids": [(6, 0, self.user.partner_id.ids)],
                "alarm_ids": [(4, alarm.id)],
            })
        )
        self.env.flush_all()
        triggers = [
            line for line in self._ics_lines(event) if line.startswith("TRIGGER")
        ]
        self.assertEqual(len(triggers), 1)
        self.assertTrue(
            triggers[0].endswith(":-PT1H"),
            f"the reminder must fire before the start, got {triggers[0]!r}",
        )

    def test_an_all_day_event_exports_dates_not_times(self):
        """`start`/`stop` hold 08:00 and 18:00 by this module's convention, and
        handing those naive datetimes to vobject emitted a *floating* datetime
        the reader shifts into its own zone. DTEND is exclusive for a DATE, so a
        24th-to-26th event ends on the 27th."""
        event = (
            self.env["calendar.event"]
            .with_user(self.user)
            .with_context(no_mail_to_attendees=True)
            .create({
                "name": "Holiday",
                "allday": True,
                "start_date": "2030-12-24",
                "stop_date": "2030-12-26",
                "user_id": self.user.id,
                "partner_ids": [(6, 0, self.user.partner_id.ids)],
            })
        )
        self.env.flush_all()
        lines = self._ics_lines(event)
        self.assertIn("DTSTART;VALUE=DATE:20301224", lines)
        self.assertIn("DTEND;VALUE=DATE:20301227", lines)

    def test_until_is_stamped_utc(self):
        """RFC 5545: with a UTC DTSTART, UNTIL must be UTC too."""
        value = self.env["calendar.event"]._get_ics_rrule(
            "DTSTART:20260828T195601\nRRULE:FREQ=WEEKLY;UNTIL=20300617T235959;BYDAY=MO"
        )
        self.assertEqual(value, "FREQ=WEEKLY;UNTIL=20300617T235959Z;BYDAY=MO")

    def test_a_lone_dtstart_is_not_a_rule(self):
        self.assertEqual(
            self.env["calendar.event"]._get_ics_rrule("DTSTART:20260828T195601"), ""
        )

    def test_a_bare_value_passes_through(self):
        self.assertEqual(
            self.env["calendar.event"]._get_ics_rrule("FREQ=DAILY;COUNT=2"),
            "FREQ=DAILY;COUNT=2",
        )


@tagged("post_install", "-at_install")
class TestCalendarUnavailableAttendees(TransactionCase):
    """`unavailable_partner_ids` must cost the same for one event and for many.

    `interval_from_events` groups the recordset into contiguous clusters, and
    the compute searched once per cluster -- so a calendar view of back-to-back
    meetings, which is one cluster per meeting, issued a query per event.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.organizer = new_test_user(
            cls.env, login="busy_organizer", groups="base.group_user"
        )
        cls.guest = new_test_user(cls.env, login="busy_guest", groups="base.group_user")

    def _events_on_distinct_days(self, count, year):
        partners = (self.organizer.partner_id + self.guest.partner_id).ids
        return (
            self.env["calendar.event"]
            .with_user(self.organizer)
            .with_context(no_mail_to_attendees=True)
            .create([
                {
                    "name": f"m{index}",
                    "start": datetime(year, 1, 1, 10) + relativedelta(days=index),
                    "stop": datetime(year, 1, 1, 11) + relativedelta(days=index),
                    "user_id": self.organizer.id,
                    "partner_ids": [(6, 0, partners)],
                }
                for index in range(count)
            ])
        )

    def _searches_to_compute(self, events):
        """How many times the compute goes to the database for busy events.

        Counted as calls rather than as `sql_log_count`, which measures the
        whole registry: `appointment` reads its own fields per event through
        the `_is_partner_unavailable` hook, so a raw query count grows with the
        recordset on a database that has it installed even when this compute
        does not. The invariant under test is one search whatever the number of
        clusters, and that is what is asserted.
        """
        self.env.flush_all()
        self.env.invalidate_all()
        partner_model = type(self.env["res.partner"])
        original = partner_model._search_busy_calendar_events
        calls = 0

        def counting(records, *args, **kwargs):
            nonlocal calls
            calls += 1
            return original(records, *args, **kwargs)

        self.patch(partner_model, "_search_busy_calendar_events", counting)
        events.mapped("unavailable_partner_ids")
        return calls

    def test_the_cost_does_not_grow_with_the_number_of_events(self):
        few = self._searches_to_compute(self._events_on_distinct_days(2, 2031))
        many = self._searches_to_compute(self._events_on_distinct_days(20, 2032))
        # Twenty events on twenty different days are twenty clusters, and used
        # to be twenty searches. Measured at N=2 against N=20 rather than as an
        # absolute count so a cache-warm run cannot make the assertion vacuous.
        self.assertEqual(few, 1)
        self.assertEqual(
            many,
            few,
            f"the compute searches once per cluster: {few} search(es) for 2 "
            f"events, {many} for 20",
        )

    def test_an_overlapping_attendee_is_still_reported_unavailable(self):
        """The batching must not change the answer."""
        partners = (self.organizer.partner_id + self.guest.partner_id).ids
        events = (
            self.env["calendar.event"]
            .with_user(self.organizer)
            .with_context(no_mail_to_attendees=True)
            .create([
                {
                    "name": "clash a",
                    "start": "2033-05-02 10:00:00",
                    "stop": "2033-05-02 11:00:00",
                    "user_id": self.organizer.id,
                    "partner_ids": [(6, 0, partners)],
                },
                {
                    "name": "clash b",
                    "start": "2033-05-02 10:30:00",
                    "stop": "2033-05-02 11:30:00",
                    "user_id": self.organizer.id,
                    "partner_ids": [(6, 0, partners)],
                },
                {
                    "name": "alone",
                    "start": "2033-09-09 10:00:00",
                    "stop": "2033-09-09 11:00:00",
                    "user_id": self.organizer.id,
                    "partner_ids": [(6, 0, partners)],
                },
            ])
        )
        self.env.flush_all()
        clash_a, clash_b, alone = events
        self.assertEqual(clash_a.unavailable_partner_ids, clash_b.partner_ids)
        self.assertEqual(clash_b.unavailable_partner_ids, clash_a.partner_ids)
        self.assertFalse(alone.unavailable_partner_ids)
