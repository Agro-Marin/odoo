# Part of Odoo. See LICENSE file for full copyright and licensing details.
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
- building a recurrence must not mutate its stored ``count`` column.
"""

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
