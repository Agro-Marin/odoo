"""Regression tests for the resource audit round.

Each class pins one defect that was reproduced against a live database before
being fixed; the docstrings record the observed wrong value so a regression is
recognisable rather than merely red.
"""

from datetime import datetime

from lxml import etree
from psycopg.errors import CheckViolation
from pytz import utc

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestPlanDaysEndOfDay(TransactionCase):
    """``plan_days`` returned the end of the n-th day's FIRST attendance block.

    On the stock 8-12 / 13-17 calendar that is lunchtime: ``plan_days(1)`` gave
    Mon 12:00 where ``plan_hours(8)`` gave Mon 17:00.  The backward branch was
    the mirror image, returning 13:00 (the afternoon's start) instead of 08:00.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Default attendances: Mon-Fri 8-12, 12-13 lunch, 13-17.
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Audit 40h", "tz": "UTC"}
        )
        cls.monday = utc.localize(datetime(2025, 1, 6))
        cls.friday_night = utc.localize(datetime(2025, 1, 10, 23, 59))

    def test_plan_days_returns_end_of_day(self):
        for days, expected in (
            (1, datetime(2025, 1, 6, 17)),
            (2, datetime(2025, 1, 7, 17)),
            (5, datetime(2025, 1, 10, 17)),
        ):
            with self.subTest(days=days):
                self.assertEqual(
                    self.calendar.plan_days(days, self.monday),
                    utc.localize(expected),
                )

    def test_plan_days_agrees_with_plan_hours(self):
        """The two planners must not disagree on where a working day ends."""
        for days in (1, 2, 3, 5):
            with self.subTest(days=days):
                self.assertEqual(
                    self.calendar.plan_days(days, self.monday),
                    self.calendar.plan_hours(days * 8, self.monday),
                )

    def test_plan_days_backwards_returns_start_of_day(self):
        for days, expected in (
            (-1, datetime(2025, 1, 10, 8)),
            (-2, datetime(2025, 1, 9, 8)),
        ):
            with self.subTest(days=days):
                self.assertEqual(
                    self.calendar.plan_days(days, self.friday_night),
                    utc.localize(expected),
                )

    def test_plan_days_edge_cases_preserved(self):
        """Zero, unsatisfiable and fractional requests keep their semantics."""
        self.assertEqual(self.calendar.plan_days(0, self.monday), self.monday)
        self.assertFalse(self.calendar.plan_days(3000, self.monday))
        self.assertFalse(self.calendar.plan_days(0.0002, self.monday))

    def test_plan_days_spans_multiple_scan_windows(self):
        """The day boundary must survive the 14-day window seam."""
        # 20 working days is 4 calendar weeks, i.e. past the first window.
        self.assertEqual(
            self.calendar.plan_days(20, self.monday),
            self.calendar.plan_hours(20 * 8, self.monday),
        )


@tagged("post_install", "-at_install")
class TestAllocatedPercentageBounds(TransactionCase):
    """A negative ``allocated_percentage`` disarmed conflict detection.

    The cumulative sweep sums the percentages, so a -100% row covering a slot
    made ``100 - 100 + 100 = 100``, which is not ``> 100``: the double booking
    reported ``schedule_overlap_count == 0`` and slipped past a reservation
    whose ``enforcement_mode`` was ``hard``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Bounds", "tz": "UTC"}
        )
        cls.resource = cls.env["resource.resource"].create(
            {"name": "Bounded", "calendar_id": cls.calendar.id, "tz": "UTC"}
        )
        cls.slot = {
            "date_start": datetime(2025, 7, 1, 8),
            "date_end": datetime(2025, 7, 1, 12),
        }

    def _reservation(self, name, **extra):
        return self.env["resource.reservation"].create(
            {"name": name, "resource_id": self.resource.id, **self.slot, **extra}
        )

    @mute_logger("odoo.db.cursor")
    def test_negative_percentage_rejected(self):
        # The table CHECK is what rejects this, and it fires during the INSERT
        # — before any Python constraint would — so the raw violation is the
        # error a direct create sees.  The web client renders the constraint's
        # declared message instead.
        with self.assertRaises(CheckViolation), self.env.cr.savepoint(flush=False):
            self._reservation("negative", allocated_percentage=-100.0)

    @mute_logger("odoo.db.cursor")
    def test_percentage_above_100_rejected(self):
        with self.assertRaises(CheckViolation), self.env.cr.savepoint(flush=False):
            self._reservation("overshoot", allocated_percentage=900.0)

    def test_boundaries_accepted(self):
        self.assertTrue(self._reservation("zero", allocated_percentage=0.0))
        self.assertTrue(self._reservation("full", allocated_percentage=100.0))

    def test_hard_enforcement_cannot_be_cancelled_out(self):
        """A row predating the constraint must still not disarm ``hard``.

        The clamp in the overlap sweep is what guarantees this for databases
        upgraded before ``migrations/1.4`` ran.  Reproduce such a row by
        dropping the constraint inside the test transaction (which rolls back).
        """
        # Park a harmless 0% row over the whole day first, so that neither it
        # nor the hard booking conflicts while the constraint is still on.
        umbrella = self.env["resource.reservation"].create(
            {
                "name": "umbrella",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 7, 1, 0),
                "date_end": datetime(2025, 7, 2, 0),
                "allocated_percentage": 0.0,
            }
        )
        self._reservation("hard", enforcement_mode="hard")
        self.env.flush_all()
        self.env.cr.execute(
            "ALTER TABLE resource_reservation"
            " DROP CONSTRAINT resource_reservation_check_allocated_percentage"
        )
        self.env.cr.execute(
            "UPDATE resource_reservation SET allocated_percentage = -100 WHERE id = %s",
            (umbrella.id,),
        )
        self.env.invalidate_all()
        with self.assertRaises(ValidationError):
            self._reservation("intruder", allocated_percentage=100.0)


@tagged("post_install", "-at_install")
class TestReservationCalendarOverride(TransactionCase):
    """``resource_calendar_id`` was honoured without a resource, ignored with one.

    A booking on a resource whose calendar was overridden to a 4 h/day calendar
    still reported the resource's own 8 h.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Calendar = cls.env["resource.calendar"]
        cls.full = Calendar.create({"name": "Full 8h", "tz": "UTC"})
        cls.half = Calendar.create(
            {
                "name": "Half 4h",
                "tz": "UTC",
                "attendance_ids": [(5, 0, 0)]
                + [
                    (
                        0,
                        0,
                        {
                            "name": f"day{day}",
                            "dayofweek": str(day),
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    )
                    for day in range(5)
                ],
            }
        )
        cls.resource = cls.env["resource.resource"].create(
            {"name": "Overridable", "calendar_id": cls.full.id, "tz": "UTC"}
        )
        cls.window = {
            "date_start": datetime(2025, 1, 6),
            "date_end": datetime(2025, 1, 7),
        }

    def test_override_is_honoured_with_a_resource(self):
        reservation = self.env["resource.reservation"].create(
            {
                "name": "override",
                "resource_id": self.resource.id,
                "resource_calendar_id": self.half.id,
                **self.window,
            }
        )
        self.assertEqual(reservation.allocated_hours, 4.0)

    def test_resource_calendar_used_when_not_overridden(self):
        reservation = self.env["resource.reservation"].create(
            {"name": "native", "resource_id": self.resource.id, **self.window}
        )
        self.assertEqual(reservation.resource_calendar_id, self.full)
        self.assertEqual(reservation.allocated_hours, 8.0)

    def test_override_still_honoured_without_a_resource(self):
        """The behaviour that already worked must not regress."""
        reservation = self.env["resource.reservation"].create(
            {
                "name": "calendar only",
                "resource_calendar_id": self.half.id,
                **self.window,
            }
        )
        self.assertEqual(reservation.allocated_hours, 4.0)

    def test_mixed_batch_resolves_each_record_on_its_own_calendar(self):
        Reservation = self.env["resource.reservation"]
        overridden = Reservation.create(
            {
                "name": "o",
                "resource_id": self.resource.id,
                "resource_calendar_id": self.half.id,
                **self.window,
            }
        )
        native = Reservation.create(
            {"name": "n", "resource_id": self.resource.id, **self.window}
        )
        (overridden | native).invalidate_recordset(["allocated_hours"])
        (overridden | native)._compute_allocated_hours()
        self.assertEqual(overridden.allocated_hours, 4.0)
        self.assertEqual(native.allocated_hours, 8.0)


@tagged("post_install", "-at_install")
class TestTwoWeeksWeekType(TransactionCase):
    """A two-weeks calendar accepted a line with no ``week_type``.

    ``int(False)`` is ``0``, so the line produced first-week work intervals
    while ``_works_on_date`` — which keys on the ``False`` bucket — reported
    that same day as not worked, and ``_check_overlap`` validated it in neither
    week.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Two weeks", "tz": "UTC"}
        )
        cls.calendar.switch_calendar_type()

    def test_week_type_is_required_on_a_two_weeks_calendar(self):
        with self.assertRaises(ValidationError):
            self.env["resource.calendar.attendance"].create(
                {
                    "calendar_id": self.calendar.id,
                    "name": "orphan",
                    "dayofweek": "2",
                    "hour_from": 9,
                    "hour_to": 17,
                    "day_period": "morning",
                    "week_type": False,
                }
            )

    def test_clearing_week_type_is_rejected(self):
        line = self.calendar.attendance_ids.filtered(lambda a: not a.display_type)[0]
        with self.assertRaises(ValidationError):
            line.week_type = False

    def test_sections_may_keep_their_own_week_type(self):
        """Section rows are UX only and must stay writable."""
        sections = self.calendar.attendance_ids.filtered(
            lambda a: a.display_type == "line_section"
        )
        self.assertEqual(len(sections), 2)
        self.assertEqual({s.week_type for s in sections}, {"0", "1"})

    def test_single_week_calendar_still_allows_unset_week_type(self):
        plain = self.env["resource.calendar"].create({"name": "Plain", "tz": "UTC"})
        self.assertTrue(
            self.env["resource.calendar.attendance"].create(
                {
                    "calendar_id": plain.id,
                    "name": "normal",
                    "dayofweek": "2",
                    "hour_from": 9,
                    "hour_to": 17,
                    "day_period": "morning",
                }
            )
        )


@tagged("post_install", "-at_install")
class TestCalendarlessIntervalApi(TransactionCase):
    """An empty calendar failed two different, opaque ways.

    ``_leave_intervals`` raised ``KeyError: False`` because the calendar-level
    key was only published when ``self`` was truthy, and the leave domain then
    carried no calendar filter at all — an empty recordset swept every leave in
    the database.
    """

    def test_leave_intervals_on_empty_calendar_is_empty(self):
        start = utc.localize(datetime(2025, 1, 6))
        end = utc.localize(datetime(2025, 1, 7))
        self.assertEqual(
            len(self.env["resource.calendar"].browse()._leave_intervals(start, end)),
            0,
        )

    def test_empty_calendar_does_not_sweep_other_calendars_leaves(self):
        calendar = self.env["resource.calendar"].create({"name": "Owner", "tz": "UTC"})
        self.env["resource.calendar.leaves"].create(
            {
                "name": "owned leave",
                "calendar_id": calendar.id,
                "date_from": datetime(2025, 1, 6, 8),
                "date_to": datetime(2025, 1, 6, 17),
            }
        )
        start = utc.localize(datetime(2025, 1, 6))
        end = utc.localize(datetime(2025, 1, 7))
        got = self.env["resource.calendar"].browse()._leave_intervals_batch(start, end)
        self.assertFalse(list(got[False]))

    def test_attendance_intervals_on_empty_calendar_explains_itself(self):
        start = utc.localize(datetime(2025, 1, 6))
        end = utc.localize(datetime(2025, 1, 7))
        with self.assertRaises(ValueError) as caught:
            self.env["resource.calendar"].browse()._attendance_intervals_batch(
                start, end
            )
        self.assertIn("fully flexible", str(caught.exception))


@tagged("post_install", "-at_install")
class TestOriginDisplayAccess(TransactionCase):
    """``origin_display`` published the name of unreadable source records.

    Reservations are the shared booking ledger and every internal user may read
    them, so resolving the source's ``display_name`` unconditionally handed out
    the title of records the reader has no rights to.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Origin", "tz": "UTC"}
        )
        cls.resource = cls.env["resource.resource"].create(
            {"name": "Origin res", "calendar_id": cls.calendar.id, "tz": "UTC"}
        )
        cls.user = cls.env["res.users"].create(
            {
                "name": "Origin reader",
                "login": "origin_reader",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )

    def _reservation(self, res_model, res_id, day):
        return self.env["resource.reservation"].create(
            {
                "name": "origin probe",
                "resource_id": self.resource.id,
                "res_model": res_model,
                "res_id": res_id,
                "date_start": datetime(2025, 5, day, 8),
                "date_end": datetime(2025, 5, day, 12),
            }
        )

    def test_unreadable_source_falls_back_to_raw_reference(self):
        # ir.mail_server is group_system only, so a plain internal user must
        # not learn its name through a reservation.
        server = self.env["ir.mail_server"].create(
            {"name": "secret smtp", "smtp_host": "h"}
        )
        reservation = self._reservation("ir.mail_server", server.id, 1)
        reservation.invalidate_recordset(["origin_display"])
        self.assertEqual(
            reservation.with_user(self.user).origin_display,
            f"ir.mail_server,{server.id}",
        )

    def test_readable_source_still_resolves(self):
        partner = self.env["res.partner"].create({"name": "Visible Partner"})
        reservation = self._reservation("res.partner", partner.id, 2)
        reservation.invalidate_recordset(["origin_display"])
        self.assertEqual(
            reservation.with_user(self.user).origin_display, "Visible Partner"
        )

    def test_deleted_source_still_falls_back(self):
        reservation = self._reservation("res.partner", 99999999, 3)
        reservation.invalidate_recordset(["origin_display"])
        self.assertEqual(
            reservation.with_user(self.user).origin_display, "res.partner,99999999"
        )

    def test_uninstalled_model_still_falls_back(self):
        reservation = self._reservation("no.such.model", 7, 4)
        reservation.invalidate_recordset(["origin_display"])
        self.assertEqual(reservation.origin_display, "no.such.model,7")


@tagged("post_install", "-at_install")
class TestResourceAdminAccess(TransactionCase):
    """``resource.resource`` was the only model here a sysadmin could not edit.

    The module ships ``menu_resource_resource`` under Settings > Technical >
    Resource, pointing at a ``list,form`` action — but ``base.group_system``
    held read-only rights, so the New button and every save raised AccessError.
    Its siblings (calendar, attendance, time off, reservation) all grant the
    group full CRUD; only this one did not, so the menu promised something the
    ACL refused. Consumer modules (``hr``, ``mrp``) grant their own groups
    write access, which is why the gap stayed invisible wherever one of them
    was installed.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sysadmin = cls.env["res.users"].create(
            {
                "name": "Resource sysadmin",
                "login": "resource_sysadmin",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("base.group_system").id,
                        ],
                    )
                ],
            }
        )

    def test_sysadmin_can_manage_resources(self):
        Resource = self.env["resource.resource"].with_user(self.sysadmin)
        for operation in ("read", "write", "create", "unlink"):
            with self.subTest(operation=operation):
                Resource.check_access(operation)

    def test_the_menu_action_actually_works(self):
        resource = (
            self.env["resource.resource"]
            .with_user(self.sysadmin)
            .create({"name": "made from the menu", "tz": "UTC"})
        )
        resource.name = "renamed"
        self.assertEqual(resource.name, "renamed")
        resource.unlink()

    def test_plain_user_stays_read_only(self):
        reader = self.env["res.users"].create(
            {
                "name": "Resource reader",
                "login": "resource_reader",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        Resource = self.env["resource.resource"].with_user(reader)
        Resource.check_access("read")
        for operation in ("write", "create", "unlink"):
            with self.subTest(operation=operation), self.assertRaises(AccessError):
                Resource.check_access(operation)


@tagged("post_install", "-at_install")
class TestViewAvatarFields(TransactionCase):
    """``avatar_field`` must name a field that exists on the related model.

    The Resource Time Off calendar asked for ``image_128`` on
    ``resource.resource``, which has ``avatar_128`` and never had an
    ``image_128``.  Nothing validates the attribute — the ORM only checks
    ``<field name=...>`` nodes — so the view loaded fine and the calendar
    filter panel simply requested
    ``/web/image/resource.resource/<id>/image_128`` and rendered a broken
    image for every resource.  This walks the module's own views so a typo
    fails a test instead of a pixel.
    """

    def test_module_views_reference_real_avatar_fields(self):
        view_ids = (
            self.env["ir.model.data"]
            .search([("module", "=", "resource"), ("model", "=", "ir.ui.view")])
            .mapped("res_id")
        )
        checked = 0
        for view in self.env["ir.ui.view"].browse(view_ids):
            if not view.model or view.model not in self.env:
                continue
            model = self.env[view.model]
            for node in etree.fromstring(view.arch_db).xpath("//field[@avatar_field]"):
                field_name = node.get("name")
                avatar_field = node.get("avatar_field")
                field = model._fields.get(field_name)
                self.assertIsNotNone(
                    field, f"{view.xml_id}: unknown field {field_name!r}"
                )
                comodel = self.env[field.comodel_name]
                self.assertIn(
                    avatar_field,
                    comodel._fields,
                    f"{view.xml_id}: avatar_field={avatar_field!r} does not exist on "
                    f"{field.comodel_name} (available: "
                    f"{sorted(n for n in comodel._fields if 'avatar' in n or 'image' in n)})",
                )
                checked += 1
        self.assertTrue(checked, "no avatar_field found — the guard would be vacuous")


@tagged("post_install", "-at_install")
class TestViewNodeNames(TransactionCase):
    """Named nodes must be unique inside a view, or inheritance targets the wrong one.

    The working-time form gave all three notebook pages ``name="working_hours"``
    — the single-week page and both two-week pages.  ``//page[@name=...]`` is
    the normal way to extend a page, and it resolves to the first match, so any
    module trying to reach the Week 2 page silently patched the Week 1 one.
    """

    def _module_views(self):
        view_ids = (
            self.env["ir.model.data"]
            .search([("module", "=", "resource"), ("model", "=", "ir.ui.view")])
            .mapped("res_id")
        )
        return self.env["ir.ui.view"].browse(view_ids)

    def test_notebook_page_names_are_unique_per_view(self):
        for view in self._module_views():
            names = [
                page.get("name")
                for page in etree.fromstring(view.arch_db).xpath("//page[@name]")
            ]
            with self.subTest(view=view.xml_id):
                self.assertEqual(
                    len(names),
                    len(set(names)),
                    f"{view.xml_id}: duplicate <page name=...>: "
                    f"{sorted(n for n in names if names.count(n) > 1)}",
                )

    def test_form_views_have_at_most_one_header(self):
        """A placeholder <header/> collides with inheritors adding their own."""
        for view in self._module_views():
            root = etree.fromstring(view.arch_db)
            if root.tag != "form":
                continue
            with self.subTest(view=view.xml_id):
                self.assertLessEqual(
                    len(root.xpath("./header")),
                    1,
                    f"{view.xml_id}: more than one <header> in a form",
                )
