# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime, timedelta

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestCalendarReservation(TransactionCase):
    """`calendar.event` projects into the shared `resource.reservation` ledger.

    Until this landed, a meeting booked nobody: the ledger's consumers were
    `project.task`, `mrp.workorder` and `planning.slot`, so a meeting and a
    shift on the same person at the same hour did not conflict.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("calendar.block_mail", True)
        cls.organizer = new_test_user(
            cls.env, "resa_organizer", groups="base.group_user"
        )
        cls.invitee = new_test_user(cls.env, "resa_invitee", groups="base.group_user")
        cls.resources = cls.env["resource.resource"].create(
            [
                {"name": "Organizer", "user_id": cls.organizer.id},
                {"name": "Invitee", "user_id": cls.invitee.id},
            ]
        )
        cls.organizer_resource, cls.invitee_resource = cls.resources
        # A partner with no user at all: an external contact invited by e-mail.
        cls.external = cls.env["res.partner"].create({"name": "External Guest"})
        cls.start = datetime(2035, 3, 15, 10, 0)

    def _make_event(self, **kwargs):
        vals = {
            "name": "Design review",
            "start": self.start,
            "stop": self.start + timedelta(hours=2),
            "partner_ids": [
                (6, 0, [self.organizer.partner_id.id, self.invitee.partner_id.id])
            ],
        }
        vals.update(kwargs)
        return self.env["calendar.event"].with_user(self.organizer).create(vals)

    def _reservations(self, event):
        return (
            self.env["resource.reservation"]
            .sudo()
            .with_context(active_test=False)
            .search([("res_model", "=", "calendar.event"), ("res_id", "in", event.ids)])
        )

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------

    def test_meeting_books_one_reservation_per_attendee_with_a_resource(self):
        event = self._make_event()
        reservations = self._reservations(event)
        self.assertEqual(
            reservations.resource_id,
            self.resources,
            "each attendee resolving to a resource books exactly one row",
        )
        self.assertEqual(set(reservations.mapped("date_start")), {self.start})
        self.assertEqual(
            set(reservations.mapped("date_end")), {self.start + timedelta(hours=2)}
        )
        self.assertEqual(set(reservations.mapped("allocated_percentage")), {100.0})

    def test_external_attendee_books_nothing(self):
        event = self._make_event(
            partner_ids=[(6, 0, [self.organizer.partner_id.id, self.external.id])]
        )
        self.assertEqual(
            self._reservations(event).resource_id,
            self.organizer_resource,
            "a contact with no user holds no capacity in this database",
        )

    def test_event_shown_as_free_books_nothing(self):
        event = self._make_event(show_as="free")
        self.assertFalse(self._reservations(event))

    def test_flipping_show_as_releases_and_retakes_the_claims(self):
        event = self._make_event()
        self.assertEqual(len(self._reservations(event)), 2)
        event.show_as = "free"
        self.assertFalse(
            self._reservations(event), "marking the time free must release it"
        )
        event.show_as = "busy"
        self.assertEqual(
            len(self._reservations(event)), 2, "and marking it busy must retake it"
        )

    def test_moving_the_meeting_moves_the_bookings(self):
        event = self._make_event()
        event.write(
            {
                "start": self.start + timedelta(days=1),
                "stop": self.start + timedelta(days=1, hours=2),
            }
        )
        self.assertEqual(
            set(self._reservations(event).mapped("date_start")),
            {self.start + timedelta(days=1)},
        )

    def test_renaming_the_meeting_relabels_the_bookings(self):
        event = self._make_event()
        event.name = "Renamed review"
        self.assertEqual(
            set(self._reservations(event).mapped("name")), {"Renamed review"}
        )

    def test_removing_an_attendee_releases_their_booking(self):
        event = self._make_event()
        event.partner_ids = [(6, 0, [self.organizer.partner_id.id])]
        self.assertEqual(self._reservations(event).resource_id, self.organizer_resource)

    # ------------------------------------------------------------------
    # Conflicts — the point of the whole exercise
    # ------------------------------------------------------------------

    def test_two_meetings_on_the_same_person_conflict(self):
        first = self._make_event()
        second = self._make_event(
            name="Clashing meeting",
            start=self.start + timedelta(hours=1),
            stop=self.start + timedelta(hours=3),
        )
        self.assertTrue(
            first.schedule_overlap_count,
            "an overlapping meeting must be visible as a conflict",
        )
        self.assertTrue(second.schedule_overlap_count)

    def test_a_meeting_conflicts_with_a_foreign_ledger_claim(self):
        """The ledger is model-agnostic: a shift booked by another consumer
        (planning, mrp, project) clashes with a meeting just the same. Stand in
        for that consumer with a raw claim, since none of them is installable
        from `calendar`'s own dependency set."""
        self.env["resource.reservation"].sudo().create(
            {
                "name": "Warehouse shift",
                "date_start": self.start + timedelta(hours=1),
                "date_end": self.start + timedelta(hours=4),
                "resource_id": self.invitee_resource.id,
                "res_model": "planning.slot",
                "res_id": 1,
                "enforcement_mode": "soft",
            }
        )
        event = self._make_event()
        self.assertTrue(
            event.schedule_overlap_count,
            "a meeting must collide with a shift on the same resource",
        )

    def test_non_overlapping_meetings_do_not_conflict(self):
        first = self._make_event()
        second = self._make_event(
            name="Later meeting",
            start=self.start + timedelta(hours=3),
            stop=self.start + timedelta(hours=4),
        )
        self.assertFalse(first.schedule_overlap_count)
        self.assertFalse(second.schedule_overlap_count)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def test_archiving_releases_the_claims_and_restoring_retakes_them(self):
        event = self._make_event()
        event.action_archive()
        self.assertFalse(
            self._reservations(event).filtered("active"),
            "an archived meeting is not a live claim on anyone",
        )
        event.action_unarchive()
        self.assertEqual(len(self._reservations(event).filtered("active")), 2)

    def test_deleting_the_meeting_leaves_no_orphan_rows(self):
        event = self._make_event()
        event_id = event.id
        event.unlink()
        self.assertFalse(
            self.env["resource.reservation"]
            .sudo()
            .with_context(active_test=False)
            .search([("res_model", "=", "calendar.event"), ("res_id", "=", event_id)])
        )

    # ------------------------------------------------------------------
    # Recurrence — the reason the sync is manual
    # ------------------------------------------------------------------

    def test_a_recurrence_books_every_occurrence_exactly_once(self):
        event = self._make_event(
            recurrency=True,
            rrule_type="daily",
            interval=1,
            end_type="count",
            count=3,
        )
        occurrences = event.recurrence_id.calendar_event_ids
        self.assertEqual(len(occurrences), 3)
        reservations = self._reservations(occurrences)
        self.assertEqual(
            len(reservations), 6, "3 occurrences x 2 attendees, no duplicates"
        )

    def test_rewriting_a_whole_recurrence_leaves_one_booking_set_per_occurrence(self):
        """`_rewrite_recurrence` never calls `super().write()` on `self`, so an
        automatic sync hook would not fire here at all."""
        event = self._make_event(
            recurrency=True,
            rrule_type="daily",
            interval=1,
            end_type="count",
            count=3,
        )
        base = event.recurrence_id.base_event_id
        base.write(
            {
                "recurrence_update": "all_events",
                "start": self.start + timedelta(hours=4),
                "stop": self.start + timedelta(hours=6),
            }
        )
        occurrences = base.recurrence_id.calendar_event_ids
        live = self._reservations(occurrences).filtered("active")
        self.assertEqual(
            len(live),
            2 * len(occurrences),
            "every occurrence keeps exactly one booking per attendee",
        )
        self.assertEqual(
            {r.date_start.hour for r in live},
            {14},
            "the rewritten times must reach the ledger",
        )
