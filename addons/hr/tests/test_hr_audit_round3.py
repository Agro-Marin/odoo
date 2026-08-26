"""Regression tests for the round-3 hr audit.

Every case below was reproduced against a live database before the fix, and
each one names the shape that broke rather than the line that changed.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tests import tagged

from .common import TestHrCommon


@tagged("post_install", "-at_install")
class TestHrAuditRound3(TestHrCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Employee = cls.env["hr.employee"]

    # ------------------------------------------------------------------
    # multi-record writes
    # ------------------------------------------------------------------
    def test_unlink_user_on_several_employees_at_once(self):
        """``write({"user_id": False})`` over more than one employee must work.

        ``_sync_user`` re-read ``self.work_contact_id`` to write it straight back
        -- a no-op on a singleton, and "Expected singleton" for any batch.
        """
        first = self.Employee.create({"name": "Batch A"})
        second = self.Employee.create({"name": "Batch B"})
        contacts = (first | second).work_contact_id
        self.assertEqual(len(contacts), 2, "each employee got its own work contact")

        (first | second).write({"user_id": False})

        self.assertFalse((first | second).user_id)
        self.assertEqual(
            (first | second).work_contact_id,
            contacts,
            "clearing the user must not disturb the existing work contacts",
        )

    def test_set_user_on_employees_of_different_companies(self):
        """A batch write of ``user_id`` across companies must work.

        ``_remove_work_contact_id`` read ``self.company_id.id``, which raised
        "Expected singleton" as soon as the batch spanned two companies.
        """
        other_company = self.env["res.company"].create({"name": "Round3 Co"})
        user = self.env["res.users"].create(
            {
                "name": "Round3 User",
                "login": "round3_user",
                "company_ids": [(6, 0, [self.env.company.id, other_company.id])],
                "company_id": self.env.company.id,
            }
        )
        here = self.Employee.create({"name": "Here", "company_id": self.env.company.id})
        there = self.Employee.create({"name": "There", "company_id": other_company.id})

        # One user per company is all ``_user_uniq`` allows, and these two sit in
        # different companies, so the batch is legal -- it just used to crash.
        (here | there).write({"user_id": user.id})

        self.assertEqual(here.user_id, user)
        self.assertEqual(there.user_id, user)

    def test_remove_work_contact_id_on_create_without_company(self):
        """Creating an employee for a user whose partner is already some other
        employee's work contact clears that stale link.

        ``create`` calls ``_remove_work_contact_id`` on the *empty* recordset, so
        the company fell back to ``self.company_id.id`` == False and the
        comparison could never match: the stale work contact survived.
        """
        user = self.env["res.users"].create(
            {"name": "Shared Partner", "login": "shared_partner_r3"}
        )
        squatter = self.Employee.create(
            {"name": "Squatter", "work_contact_id": user.partner_id.id}
        )
        self.assertEqual(squatter.work_contact_id, user.partner_id)

        self.Employee.create({"name": "Real Owner", "user_id": user.id})

        self.assertFalse(
            squatter.work_contact_id,
            "the userless employee must lose the partner now claimed by a user",
        )

    def test_department_subscription_covers_every_written_employee(self):
        """A batch ``department_id`` write subscribes that department's channels.

        Guard, not a reproduction: the ``self[:1].department_id`` fallback it
        replaces is only reachable on a ``user_id``-only batch write, which the
        ``_user_uniq`` constraint and the singleton crash above made impossible
        to hit. This pins the batch behaviour so the fallback cannot regress
        once those are fixed.
        """
        dept_a = self.env["hr.department"].create({"name": "R3 A"})
        dept_b = self.env["hr.department"].create({"name": "R3 B"})
        user_a = self.env["res.users"].create({"name": "R3 UA", "login": "r3_ua"})
        user_b = self.env["res.users"].create({"name": "R3 UB", "login": "r3_ub"})
        emp_a = self.Employee.create(
            {"name": "R3 EA", "user_id": user_a.id, "department_id": dept_a.id}
        )
        emp_b = self.Employee.create(
            {"name": "R3 EB", "user_id": user_b.id, "department_id": dept_b.id}
        )
        channel_b = self.env["discuss.channel"].create(
            {
                "name": "R3 chan B",
                "channel_type": "channel",
                "subscription_department_ids": [(6, 0, dept_b.ids)],
            }
        )
        channel_b.channel_member_ids.filtered(
            lambda member: member.partner_id == user_b.partner_id
        ).unlink()
        self.assertNotIn(user_b.partner_id, channel_b.channel_partner_ids)

        # emp_a comes first in the recordset; the department written is dept_b.
        (emp_a | emp_b).write({"department_id": dept_b.id})

        self.assertIn(
            user_b.partner_id,
            channel_b.channel_partner_ids,
            "the written department's channel must auto-subscribe its members",
        )

    # ------------------------------------------------------------------
    # timezone handling
    # ------------------------------------------------------------------
    def test_calendar_tz_batch_resolves_the_employee_local_date(self):
        """``_get_calendar_tz_batch`` must convert the instant into the
        employee's zone before choosing the effective version.

        ``dt.replace(tzinfo=tz)`` relabels the wall clock: ``.date()`` stayed
        equal to ``dt.date()`` for every zone, so the UTC-date version was
        picked for everyone and the per-timezone grouping was a no-op.
        """
        tokyo = self.env["resource.calendar"].create(
            {"name": "R3 Tokyo", "tz": "Asia/Tokyo"}
        )
        auckland = self.env["resource.calendar"].create(
            {"name": "R3 Auckland", "tz": "Pacific/Auckland"}
        )
        employee = self.Employee.create(
            {
                "name": "R3 Tokyo Emp",
                "tz": "Asia/Tokyo",
                "resource_calendar_id": tokyo.id,
            }
        )
        employee.version_id.write(
            {
                "date_version": date(2026, 1, 10),
                "contract_date_start": date(2026, 1, 10),
                "resource_calendar_id": tokyo.id,
            }
        )
        employee.create_version(
            {"date_version": date(2026, 1, 15), "resource_calendar_id": auckland.id}
        )
        self.env.flush_all()

        # 2026-01-14 22:00 UTC is 2026-01-15 07:00 in Tokyo, so the version
        # effective on the 15th -- the Auckland calendar -- is the right one.
        instant = datetime(2026, 1, 14, 22, 0)
        self.assertEqual(
            instant.replace(tzinfo=ZoneInfo("UTC"))
            .astimezone(ZoneInfo("Asia/Tokyo"))
            .date(),
            date(2026, 1, 15),
        )
        self.assertEqual(
            employee._get_calendar_tz_batch(instant),
            {employee.id: "Pacific/Auckland"},
        )

    def test_calendar_tz_batch_keeps_each_group_to_its_own_employees(self):
        """Each timezone group resolves only its own employees.

        Guard, not a reproduction: passing the whole recordset on every pass was
        benign while all passes computed the same answer (the dates were equal,
        see the test above). This pins the per-group scoping now that the dates
        genuinely differ.
        """
        tokyo_cal = self.env["resource.calendar"].create(
            {"name": "R3 TK", "tz": "Asia/Tokyo"}
        )
        ny_cal = self.env["resource.calendar"].create(
            {"name": "R3 NY", "tz": "America/New_York"}
        )
        tokyo_emp = self.Employee.create(
            {
                "name": "R3 TK Emp",
                "tz": "Asia/Tokyo",
                "resource_calendar_id": tokyo_cal.id,
            }
        )
        ny_emp = self.Employee.create(
            {
                "name": "R3 NY Emp",
                "tz": "America/New_York",
                "resource_calendar_id": ny_cal.id,
            }
        )
        self.env.flush_all()

        self.assertEqual(
            (tokyo_emp | ny_emp)._get_calendar_tz_batch(datetime(2026, 1, 15, 3, 0)),
            {tokyo_emp.id: "Asia/Tokyo", ny_emp.id: "America/New_York"},
        )

    def test_get_calendar_at_accepts_its_own_default(self):
        """``resource._get_calendar_at(dt)`` must work without an explicit tz.

        ``date_target.astimezone(False)`` raised TypeError, so the signature's
        documented default was unusable.
        """
        calendar = self.env["resource.calendar"].create(
            {"name": "R3 cal", "tz": "Europe/Brussels"}
        )
        employee = self.Employee.create(
            {"name": "R3 CalAt", "resource_calendar_id": calendar.id}
        )
        self.env.flush_all()

        result = employee.resource_id._get_calendar_at(
            datetime(2026, 1, 15, 3, 0, tzinfo=ZoneInfo("UTC"))
        )
        self.assertEqual(result[employee.resource_id], calendar)

    # ------------------------------------------------------------------
    # the public model mirrors the private one
    # ------------------------------------------------------------------
    def test_public_last_activity_matches_the_private_one(self):
        """``hr.employee.public.last_activity`` now delegates instead of
        restating hr.employee's presence/timezone arithmetic.

        Pins the deletion of a 20-line verbatim copy: the two must agree on real
        presence data (both answering False proves nothing), and the public one
        must still resolve for a user with no hr.employee access -- which is the
        model's whole purpose.
        """
        user = self.env["res.users"].create(
            {"name": "R3 Presence User", "login": "r3_presence_user"}
        )
        employee = self.Employee.create(
            {"name": "R3 Presence", "user_id": user.id, "tz": "Asia/Tokyo"}
        )
        self.env["mail.presence"].create(
            {
                "user_id": user.id,
                "last_presence": datetime.now(),
                "status": "online",
            }
        )
        self.env.flush_all()
        plain_user = self.env["res.users"].create(
            {
                "name": "R3 Presence Reader",
                "login": "r3_presence_reader",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )

        public = self.env["hr.employee.public"].browse(employee.id)
        self.assertTrue(employee.last_activity, "real presence, so a real date")
        self.assertEqual(
            (public.last_activity, public.last_activity_time),
            (employee.last_activity, employee.last_activity_time),
        )
        as_plain_user = (
            self.env["hr.employee.public"].with_user(plain_user).browse(employee.id)
        )
        self.assertEqual(
            (as_plain_user.last_activity, as_plain_user.last_activity_time),
            (employee.last_activity, employee.last_activity_time),
        )

    # ------------------------------------------------------------------
    # search methods
    # ------------------------------------------------------------------
    def test_member_of_department_matches_nothing_without_a_department(self):
        """On hr.version, "My Department" for a user with no department must match
        nothing -- not hr.version rows whose id happens to equal an employee id.

        The branch was copied from hr.employee.public, where the SQL view makes
        ``id`` the employee id; on hr.version it compared ids across models and
        returned arbitrary versions, contract templates included.
        """
        user = self.env["res.users"].create(
            {
                "name": "R3 No Dept",
                "login": "r3_nodept",
                "group_ids": [(4, self.env.ref("hr.group_hr_user").id)],
            }
        )
        employee = self.Employee.create({"name": "R3 No Dept Emp", "user_id": user.id})
        self.assertFalse(employee.department_id)
        self.env.flush_all()

        Version = self.env["hr.version"].with_user(user)
        # Assert the domain, not only its result: at HEAD the domain was
        # ``[("id", "in", <employee ids>)]``, whose result depended on whether an
        # hr.version row happened to carry that id.
        self.assertEqual(
            Domain(Version._search_member_of_department("in", [True])),
            Domain.FALSE,
        )
        self.assertFalse(
            Version.search([("member_of_department", "=", True)]),
            "no department means no member, so nothing matches",
        )

    def test_bank_account_search_by_absent_employee(self):
        """``res.partner.bank`` search on ``employee_id = False`` must return the
        non-employee accounts, not an empty set.

        The old implementation resolved ``hr.employee.search([("id", "in",
        [False])])`` -- always empty -- and then mapped that to bank ids.
        """
        partner = self.env["res.partner"].create({"name": "R3 Plain"})
        plain = self.env["res.partner.bank"].create(
            {"acc_number": "R3PLAIN0001", "partner_id": partner.id}
        )
        employee = self.Employee.create({"name": "R3 Banked"})
        banked = self.env["res.partner.bank"].create(
            {"acc_number": "R3EMP00001", "partner_id": employee.work_contact_id.id}
        )
        employee.bank_account_ids = [(6, 0, banked.ids)]
        self.env.flush_all()

        scope = [("id", "in", (plain | banked).ids)]
        self.assertEqual(
            self.env["res.partner.bank"].search([*scope, ("employee_id", "=", False)]),
            plain,
        )
        self.assertEqual(
            self.env["res.partner.bank"].search([*scope, ("employee_id", "!=", False)]),
            banked,
        )

    def test_bank_account_search_is_usable_by_a_non_hr_user(self):
        """``employee_id`` carries no group and its compute resolves under sudo,
        so the search must too.

        Expressing it as a domain over ``partner_id.employee_ids`` -- which is
        hr.group_hr_user-only -- raised AccessError for an ordinary internal
        user on every operator.
        """
        partner = self.env["res.partner"].create({"name": "R3 NonHR Plain"})
        plain = self.env["res.partner.bank"].create(
            {"acc_number": "R3NHR0001", "partner_id": partner.id}
        )
        employee = self.Employee.create({"name": "R3 NonHR Banked"})
        banked = self.env["res.partner.bank"].create(
            {"acc_number": "R3NHR0002", "partner_id": employee.work_contact_id.id}
        )
        employee.bank_account_ids = [(6, 0, banked.ids)]
        plain_user = self.env["res.users"].create(
            {
                "name": "R3 Plain User",
                "login": "r3_plain_user",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.env.flush_all()

        Bank = self.env["res.partner.bank"].with_user(plain_user)
        scope = [("id", "in", (plain | banked).ids)]
        # An ordinary user only sees non-employee accounts anyway (ir.rule
        # ir_rule_res_partner_bank_internal_users); the point is that asking
        # does not raise.
        self.assertEqual(Bank.search([*scope, ("employee_id", "=", False)]), plain)
        self.assertFalse(Bank.search([*scope, ("employee_id", "!=", False)]))
        self.assertFalse(Bank.search([*scope, ("employee_id", "=", employee.id)]))

    def test_bank_account_search_matches_its_own_compute(self):
        """The search resolves through ``work_contact_id``, the relation the
        compute reads -- not through the ``bank_account_ids`` m2m.

        An account on an employee's work contact but absent from that m2m has
        ``employee_id`` set, and the old mapping never returned it.
        """
        employee = self.Employee.create({"name": "R3 Two Accounts"})
        listed = self.env["res.partner.bank"].create(
            {"acc_number": "R3TWO0001", "partner_id": employee.work_contact_id.id}
        )
        unlisted = self.env["res.partner.bank"].create(
            {"acc_number": "R3TWO0002", "partner_id": employee.work_contact_id.id}
        )
        employee.bank_account_ids = [(6, 0, listed.ids)]
        self.env.flush_all()

        self.assertEqual(unlisted.employee_id, employee, "the compute claims it")
        self.assertEqual(
            self.env["res.partner.bank"].search(
                [
                    ("id", "in", (listed | unlisted).ids),
                    ("employee_id", "=", employee.id),
                ]
            ),
            listed | unlisted,
            "so the search must return it too",
        )

    def test_batch_user_write_does_not_wipe_avatars(self):
        """Writing ``user_id`` over a batch must not clear the images of
        employees that have one.

        ``_sync_user`` was handed ``all(emp.image_1920 for emp in self)`` -- one
        boolean for the whole batch -- so a single imageless employee put
        ``image_1920: False`` in the shared vals and wiped everyone else's.
        Reachable from the employee list view, which carries ``multi_edit="1"``
        and exposes ``user_id``.
        """
        with_image = self.Employee.create({"name": "R3 With Image"})
        without_image = self.Employee.create({"name": "R3 Without Image"})
        without_image.image_1920 = False
        self.env.flush_all()
        original = with_image.image_1920
        self.assertTrue(original)
        self.assertFalse(without_image.image_1920)

        (with_image | without_image).write({"user_id": False})
        self.env.flush_all()

        self.assertEqual(with_image.image_1920, original)

    def test_user_write_still_seeds_a_missing_avatar(self):
        """The non-destructive rule must not stop an imageless employee from
        inheriting the user's avatar (singleton parity with the old flag)."""
        donor = self.Employee.create({"name": "R3 Donor"})
        user = self.env["res.users"].create(
            {"name": "R3 Avatar User", "login": "r3_avatar_user"}
        )
        user.image_1920 = donor.image_1920
        employee = self.Employee.create({"name": "R3 Seeded"})
        employee.image_1920 = False
        self.env.flush_all()

        employee.write({"user_id": user.id})
        self.env.flush_all()

        self.assertEqual(employee.image_1920, user.image_1920)

    def test_no_bank_account_relation_is_self_writable(self):
        """No res.users field reaching res.partner.bank may be self-writable.

        ``res.users.write`` elevates a self-write to superuser when every key is
        self-writable, gating on top-level key names only -- so any writable
        relation to res.partner.bank lets an ordinary employee create or trust an
        arbitrary bank account under sudo (vendor-payment fraud).

        TestHrAuditRound2 pins this for ``employee_bank_account_ids`` by name.
        This asserts the *shape*, so the next field of that kind is caught on the
        commit that adds it rather than on the audit that finds it.
        """
        Users = self.env["res.users"]
        self_writable = set(Users.SELF_WRITEABLE_FIELDS)
        offenders = [
            name
            for name, field in Users._fields.items()
            if name in self_writable
            and field.relational
            and field.comodel_name == "res.partner.bank"
        ]
        self.assertFalse(
            offenders,
            "self-writable relation(s) to res.partner.bank: %s" % offenders,
        )

    # ------------------------------------------------------------------
    # guards and idempotence
    # ------------------------------------------------------------------
    def test_version_periods_rejects_an_employee_only_field(self):
        """``_get_version_periods`` reads ``field`` off hr.version, so a field
        that exists only on hr.employee must raise the documented UserError --
        the guard checked ``self`` (hr.employee) and let it die on a KeyError."""
        employee = self.Employee.create({"name": "R3 Periods"})
        employee.version_id.write({"contract_date_start": date(2026, 1, 1)})
        self.env.flush_all()

        self.assertIn("barcode", employee._fields)
        self.assertNotIn("barcode", self.env["hr.version"]._fields)
        with self.assertRaises(UserError):
            employee._get_version_periods(
                datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
                datetime(2026, 3, 1, tzinfo=ZoneInfo("UTC")),
                field="barcode",
            )

    def test_expiry_cron_is_idempotent(self):
        """Two runs of the expiry cron in the same day must not stack duplicate
        activities: it matched on an exact date but scheduled unconditionally."""
        company = self.env.company
        company.work_permit_expiration_notice_period = 5
        company.contract_expiration_notice_period = 5
        today = date.today()
        employee = self.Employee.create(
            {
                "name": "R3 Expiring",
                "work_permit_expiration_date": today + timedelta(days=5),
            }
        )
        employee.version_id.write(
            {
                "contract_date_start": today - timedelta(days=30),
                "contract_date_end": today + timedelta(days=5),
            }
        )
        self.env.flush_all()

        def activity_count():
            return self.env["mail.activity"].search_count(
                [("res_model", "=", "hr.employee"), ("res_id", "=", employee.id)]
            )

        self.Employee.notify_expiring_contract_work_permit()
        self.env.flush_all()
        after_first = activity_count()
        self.assertEqual(
            after_first, 2, "one reminder for the contract, one for the work permit"
        )

        self.Employee.notify_expiring_contract_work_permit()
        self.env.flush_all()
        self.assertEqual(activity_count(), after_first, "the second run adds nothing")

    @freeze_time("2026-07-13")
    def test_expiry_cron_still_notifies_after_missing_a_day(self):
        """The cron matches a notice WINDOW, not the exact notice day.

        Matching ``contract_date_end = today + notice_period`` meant a day the
        cron did not run -- server down, cron disabled, a restored backup -- lost
        that expiry's notification for good, because the next run's date no longer
        matched. Safe only because ``_schedule_expiry_activity`` is idempotent.
        """
        company = self.env.company
        company.contract_expiration_notice_period = 7
        today = date(2026, 7, 13)
        # Three days inside a seven-day window: the old exact-day match would
        # have needed the cron to run on 2026-07-06 and never notified again.
        inside = self.Employee.create(
            {
                "name": "R3 Inside Window",
                "date_version": "2020-01-01",
                "contract_date_start": "2020-01-01",
                "contract_date_end": fields.Date.to_string(today + timedelta(days=3)),
            }
        )
        beyond = self.Employee.create(
            {
                "name": "R3 Beyond Window",
                "date_version": "2020-01-01",
                "contract_date_start": "2020-01-01",
                "contract_date_end": fields.Date.to_string(today + timedelta(days=30)),
            }
        )
        already_over = self.Employee.create(
            {
                "name": "R3 Already Expired",
                "date_version": "2020-01-01",
                "contract_date_start": "2020-01-01",
                "contract_date_end": fields.Date.to_string(today - timedelta(days=1)),
            }
        )
        self.env.flush_all()

        self.Employee.notify_expiring_contract_work_permit()
        self.env.flush_all()

        self.assertTrue(inside.activity_ids, "inside the window, so notified")
        self.assertFalse(beyond.activity_ids, "past the window, not yet due")
        self.assertFalse(
            already_over.activity_ids, "already expired, the window starts today"
        )

        # And still exactly once, however many times the cron runs.
        self.Employee.notify_expiring_contract_work_permit()
        self.env.flush_all()
        self.assertEqual(len(inside.activity_ids), 1)

    def test_versions_count_follows_its_versions(self):
        """``versions_count`` declares ``version_ids``, so adding a version
        invalidates it instead of leaving a cached value behind."""
        employee = self.Employee.create({"name": "R3 Counting"})
        self.env.flush_all()
        self.assertEqual(employee.versions_count, 1)

        employee.create_version({"date_version": date.today() + timedelta(days=10)})
        self.env.flush_all()

        self.assertEqual(employee.versions_count, 2)

    def test_date_state_fields_stay_consistent(self):
        """is_current / is_past / is_future come from one compute now.

        Guard for that merge: the three must stay mutually exclusive.
        """
        today = date.today()
        employee = self.Employee.create({"name": "R3 Dates"})
        employee.version_id.write(
            {
                "date_version": today - timedelta(days=10),
                "contract_date_start": today - timedelta(days=10),
            }
        )
        self.env.flush_all()

        version = employee.version_id
        self.assertTrue(version.is_current)
        self.assertFalse(version.is_past)
        self.assertFalse(version.is_future)

        version.write({"contract_date_end": today - timedelta(days=1)})
        self.env.flush_all()
        version.invalidate_recordset()
        self.assertFalse(version.is_current)
        self.assertTrue(version.is_past)
        self.assertFalse(version.is_future)

    # ------------------------------------------------------------------
    # searches answer with domains, and cover the whole field
    # ------------------------------------------------------------------
    def test_newly_hired_search_covers_a_null_hire_date(self):
        """``newly_hired = False`` must include employees whose hire-date field is
        NULL -- the compute calls those not-newly-hired.

        The search now answers with a domain instead of inlining every
        newly-hired id, and a bare ``<= threshold`` would silently drop NULL rows
        because no SQL comparison against NULL is ever true.
        """
        recent = self.Employee.create({"name": "R3 Recent"})
        old = self.Employee.create({"name": "R3 Old"})
        undated = self.Employee.create({"name": "R3 Undated"})
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE hr_employee SET create_date = %s WHERE id = %s",
            (datetime(2020, 1, 1), old.id),
        )
        self.env.cr.execute(
            "UPDATE hr_employee SET create_date = NULL WHERE id = %s", (undated.id,)
        )
        (recent | old | undated).invalidate_recordset()

        self.assertTrue(recent.newly_hired)
        self.assertFalse(old.newly_hired)
        self.assertFalse(undated.newly_hired)

        scope = [("id", "in", (recent | old | undated).ids)]
        self.assertEqual(
            self.Employee.search([*scope, ("newly_hired", "=", True)]), recent
        )
        self.assertEqual(
            self.Employee.search([*scope, ("newly_hired", "=", False)]),
            old | undated,
            "an employee with no hire date is not newly hired, so the negative "
            "search must return them",
        )

    def test_member_of_department_search_agrees_with_its_compute(self):
        """On hr.employee.public too, "My Department" must not return a record on
        which ``member_of_department`` reads False."""
        user = self.env["res.users"].create(
            {
                "name": "R3 Public NoDept",
                "login": "r3_public_nodept",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        employee = self.Employee.create(
            {"name": "R3 Public NoDept Emp", "user_id": user.id}
        )
        self.env.flush_all()
        self.assertFalse(employee.department_id)

        Public = self.env["hr.employee.public"].with_user(user)
        self.assertFalse(Public.browse(employee.id).member_of_department)
        self.assertFalse(
            Public.search([("member_of_department", "=", True)]),
            "the field reads False on every row, so the filter must match none",
        )

    def test_expected_attendances_leave_domain_differs_by_branch(self):
        """PINS A DIVERGENCE, it does not endorse it.

        ``_get_expected_attendances`` filters leaves by ``time_type = "leave"``
        when the employee has an in-contract version, and does NOT filter when
        they have none. A ``time_type = "other"`` entry -- what a public holiday
        or a training day is recorded as -- is therefore subtracted from the
        no-version branch's working time and kept in the version branch's.

        The two branches do not compute the same thing. Reconciling them changes
        attendance figures and wants product input, so the difference is asserted
        here instead of sitting unnoticed between two loops that used to be
        copies of each other.
        """
        calendar = self.env["resource.calendar"].create(
            {"name": "R3 Leave Domain", "tz": "UTC"}
        )
        period_start = datetime(2026, 3, 2, tzinfo=ZoneInfo("UTC"))  # a Monday
        period_stop = datetime(2026, 3, 6, 23, 59, tzinfo=ZoneInfo("UTC"))
        self.env["resource.calendar.leaves"].create(
            {
                "name": "R3 Public Holiday",
                "calendar_id": calendar.id,
                "date_from": datetime(2026, 3, 4, 0, 0),
                "date_to": datetime(2026, 3, 4, 23, 59),
                "time_type": "other",
            }
        )

        without_contract = self.Employee.create(
            {"name": "R3 No Contract", "resource_calendar_id": calendar.id}
        )
        with_contract = self.Employee.create(
            {"name": "R3 In Contract", "resource_calendar_id": calendar.id}
        )
        with_contract.version_id.write(
            {
                "date_version": date(2026, 1, 1),
                "contract_date_start": date(2026, 1, 1),
                "resource_calendar_id": calendar.id,
            }
        )
        self.env.flush_all()

        def covers_the_holiday(employee):
            intervals = employee._get_expected_attendances(period_start, period_stop)
            return any(
                start.date() == date(2026, 3, 4) for start, _stop, _meta in intervals
            )

        self.assertFalse(
            covers_the_holiday(without_contract),
            "the no-version branch passes no time_type filter, so the "
            'time_type="other" entry is subtracted',
        )
        self.assertTrue(
            covers_the_holiday(with_contract),
            'the per-version branch filters time_type="leave", so the same entry '
            "is left as working time -- the divergence this test pins",
        )

    # ------------------------------------------------------------------
    # crons, defaults and uniqueness
    # ------------------------------------------------------------------
    def test_current_version_cron_covers_archived_employees(self):
        """``_cron_update_current_version_id`` must refresh archived employees too.

        ``search([])`` is active-only, and hr.employee.public JOINs on
        ``current_version_id``, so an archived employee's public row showed a
        stale version indefinitely.
        """
        employee = self.Employee.create({"name": "R3 Archived"})
        employee.version_id.write({"date_version": date.today() - timedelta(days=30)})
        later = employee.create_version(
            {"date_version": date.today() - timedelta(days=1)}
        )
        self.env.flush_all()
        # Force the stored value back to the older version, then archive.
        self.env.cr.execute(
            "UPDATE hr_employee SET current_version_id = %s WHERE id = %s",
            (employee.version_ids.sorted("date_version")[0].id, employee.id),
        )
        employee.invalidate_recordset()
        employee.action_archive()
        self.env.flush_all()
        self.assertFalse(employee.active)

        self.Employee._cron_update_current_version_id()
        self.env.flush_all()
        employee.invalidate_recordset()

        self.assertEqual(employee.current_version_id, later)

    def test_random_barcode_avoids_taken_badges(self):
        """``generate_random_barcode`` must not hand out a badge already in use --
        ``_barcode_uniq`` is a DB UNIQUE, so a collision was a traceback."""
        employees = self.Employee.create(
            [{"name": "R3 Badge %d" % index} for index in range(6)]
        )
        self.env.flush_all()

        employees.generate_random_barcode()
        self.env.flush_all()

        barcodes = employees.mapped("barcode")
        self.assertEqual(len(barcodes), len(set(barcodes)), "no duplicate in a batch")
        self.assertTrue(all(code.startswith("041") for code in barcodes))
        # And a second draw must avoid the ones just handed out.
        more = self.Employee.create([{"name": "R3 Badge more"}])
        more.generate_random_barcode()
        self.env.flush_all()
        self.assertNotIn(more.barcode, barcodes)

    def test_structure_type_default_resolves_for_an_hr_officer(self):
        """``_compute_structure_type_id`` runs under sudo like the field's default.

        hr.payroll.structure.type is readable by hr.group_hr_manager only, so the
        compute's own (non-sudo) lookup returned nothing for an officer and left
        the manager-only field unset when the company changed.
        """
        officer_env = self.env(user=self.res_users_hr_officer)
        employee = officer_env["hr.employee"].create({"name": "R3 Officer Created"})
        self.env.flush_all()
        version = employee.sudo().version_id
        self.assertTrue(
            version.structure_type_id, "a default must have been resolved under sudo"
        )

        other_country = self.env["res.country"].search(
            [("id", "!=", self.env.company.country_id.id)], limit=1
        )
        other_company = self.env["res.company"].create(
            {"name": "R3 Other Country Co", "country_id": other_country.id}
        )
        version.sudo().write({"company_id": other_company.id})
        self.env.flush_all()
        # Recompute as the officer: the lookup must still find a default.
        version.with_user(self.res_users_hr_officer).invalidate_recordset()
        self.assertTrue(
            version.sudo().structure_type_id,
            "the compute must not clear the field for a non-manager",
        )

    def test_department_plan_action_domain_is_evaluated(self):
        """``action_plan_from_department`` reads a stored domain that names
        ``allowed_company_ids``.

        It used to substitute the name into the string and ``ast.literal_eval``
        the result; it now evaluates the expression through
        ``eval_action_domain``. Either way the action must come back with a
        usable, searchable domain.
        """
        department = self.env["hr.department"].create({"name": "R3 Plan Dept"})
        action = department.action_plan_from_department()

        self.assertIn("domain", action)
        # The clause from the stored domain survived, and the method's own
        # department clause was ANDed onto it.
        flattened = str(action["domain"])
        self.assertIn("res_model", flattened)
        self.assertIn("department_id", flattened)
        # And it is a domain the ORM accepts.
        self.env["mail.activity.plan"].search(action["domain"])

    def test_create_users_reports_a_login_clash(self):
        """An employee whose work email is already some user's *login* gets the
        friendly notification, not a raw UniqueViolation on res_users_login_key.

        The conflict search already matched ``login``, but the membership test
        below it compared ``email_normalized`` only.
        """
        self.env["res.users"].create(
            {
                "name": "R3 Squatter",
                "login": "r3_taken@example.com",
                "email": "r3_other@example.com",
            }
        )
        employee = self.Employee.create({"name": "R3 Newbie"})
        employee.work_email = "r3_taken@example.com"
        self.env.flush_all()

        action = employee.action_create_users()
        self.env.flush_all()

        self.assertEqual(action["params"]["type"], "warning")
        self.assertIn("R3 Newbie", action["params"]["message"])
        self.assertFalse(employee.user_id)
