# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regression tests for the hr full-module audit fixes.

Each test pins down a bug found during the audit so it cannot silently return.
"""

from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta
from pytz import timezone

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import freeze_time

from odoo.addons.hr.tests.common import TestHrCommon
from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestHrAuditFixes(TestHrCommon):
    def _new_employee(self, name, **vals):
        return self.env["hr.employee"].create(
            {"name": name, "date_version": "2020-01-01", **vals}
        )

    def _add_bank_account(self, employee, acc_number):
        return self.env["res.partner.bank"].create(
            {"acc_number": acc_number, "partner_id": employee.work_contact_id.id}
        )

    def test_version_id_context_is_per_record(self):
        """A pinned ``version_id`` in context must resolve per employee, even when
        ``version_id`` is computed over a multi-record recordset.

        Regression: the compute compared ``context_version.employee_id`` against
        the whole recordset (``self``) instead of the loop's current record, so
        the pin was silently dropped for every batch of size > 1.
        """
        emp1 = self._new_employee("E1")
        emp2 = self._new_employee("E2")
        old_version = emp1.create_version({"date_version": "2019-01-01"})
        self.assertNotEqual(
            emp1.current_version_id, old_version, "current version is the 2020 one"
        )

        combined = (emp1 | emp2).with_context(version_id=old_version.id)
        version_by_emp = {emp.id: emp.version_id for emp in combined}

        self.assertEqual(
            version_by_emp[emp1.id],
            old_version,
            "the pinned context version wins for the employee it belongs to",
        )
        self.assertEqual(
            version_by_emp[emp2.id],
            emp2.current_version_id,
            "an unrelated employee keeps its own current version",
        )

    def test_salary_distribution_autosync_and_constraint(self):
        """Adding accounts auto-splits to 100%; the constraint rejects a bad total."""
        emp = self._new_employee("Bank Guy")
        ba1 = self._add_bank_account(emp, "BE000001")
        ba2 = self._add_bank_account(emp, "BE000002")
        emp.bank_account_ids = [(6, 0, (ba1 | ba2).ids)]

        dist = emp.salary_distribution
        self.assertEqual(set(dist), {str(ba1.id), str(ba2.id)})
        total = sum(v["amount"] for v in dist.values() if v["amount_is_percentage"])
        self.assertAlmostEqual(total, 100.0, places=4)

        with self.assertRaises(ValidationError):
            emp.salary_distribution = {
                str(ba1.id): {
                    "amount": 60.0,
                    "amount_is_percentage": True,
                    "sequence": 1,
                },
                str(ba2.id): {
                    "amount": 30.0,
                    "amount_is_percentage": True,
                    "sequence": 2,
                },
            }

    def test_primary_bank_account_and_trust_toggle(self):
        """primary account = lowest sequence; the trust toggle flips it and the
        mirrored ``is_trusted_bank_account`` flag follows."""
        emp = self._new_employee("Primary Guy")
        ba1 = self._add_bank_account(emp, "BE000011")
        ba2 = self._add_bank_account(emp, "BE000012")
        emp.bank_account_ids = [(6, 0, (ba1 | ba2).ids)]

        primary = emp.primary_bank_account_id
        self.assertIn(primary, ba1 | ba2)
        min_seq_key = min(
            emp.salary_distribution,
            key=lambda k: emp.salary_distribution[k]["sequence"],
        )
        self.assertEqual(str(primary.id), min_seq_key)

        self.assertFalse(emp.is_trusted_bank_account)
        emp.action_toggle_primary_bank_account_trust()
        self.assertTrue(emp.primary_bank_account_id.allow_out_payment)
        self.assertTrue(emp.is_trusted_bank_account)

    def test_bank_salary_amount_remaining_for_unallocated_account(self):
        """An account not in the distribution reports the still-allocatable
        percentage (regression: the ``get_remaining_percentage`` branch was dead
        and every such account showed 0)."""
        emp = self._new_employee("Fixed Guy")
        ba1 = self._add_bank_account(emp, "BE000021")
        ba2 = self._add_bank_account(emp, "BE000022")
        emp.bank_account_ids = [(4, ba1.id)]
        # ba1 is a fixed-amount allocation -> 0% of salary is percentage-allocated.
        emp.salary_distribution = {
            str(ba1.id): {
                "amount": 500.0,
                "amount_is_percentage": False,
                "sequence": 1,
            },
        }

        # ba1 participates -> reports its own (fixed) amount.
        self.assertEqual(ba1.employee_salary_amount, 500.0)
        self.assertFalse(ba1.employee_salary_amount_is_percentage)
        # ba2 is not in the distribution -> 100% still allocatable.
        self.assertEqual(ba2.employee_salary_amount, 100.0)
        self.assertTrue(ba2.employee_salary_amount_is_percentage)

    def test_get_unusual_days_without_date_to(self):
        """``_get_unusual_days`` must not crash when ``date_to`` is omitted."""
        emp = self._new_employee("Calendar Guy")
        result = emp._get_unusual_days("2020-06-01 00:00:00")
        self.assertIsInstance(result, dict)

    def test_job_title_cleared_when_job_removed(self):
        """Clearing ``job_id`` drops a non-custom job title instead of leaving a
        stale one (the compute previously skipped records with no job)."""
        job = self.env["hr.job"].create({"name": "Developer"})
        emp = self._new_employee("Titled Guy", job_id=job.id)
        version = emp.version_id
        self.assertEqual(version.job_title, "Developer")
        self.assertFalse(version.is_custom_job_title)

        version.job_id = False
        self.assertFalse(
            version.job_title, "a non-custom title must not survive its job"
        )

    def test_job_title_custom_survives_job_removal(self):
        """A user-typed (custom) title is kept when the job is cleared."""
        job = self.env["hr.job"].create({"name": "Developer"})
        emp = self._new_employee("Custom Guy", job_id=job.id)
        version = emp.version_id
        version.job_title = "Lead Engineer"
        self.assertTrue(version.is_custom_job_title)

        version.job_id = False
        self.assertEqual(version.job_title, "Lead Engineer")

    def test_employees_count_batched(self):
        """The batched ``_compute_employees_count`` returns the right per-partner
        count (guards the N+1 refactor)."""
        emp = self._new_employee("Counted Guy")
        partner = emp.work_contact_id
        self.assertEqual(partner.employees_count, 1)
        # A second employee on the same work contact.
        self.env["hr.employee"].create(
            {
                "name": "Counted Guy 2",
                "date_version": "2020-01-01",
                "work_contact_id": partner.id,
            }
        )
        partner.invalidate_recordset(["employees_count"])
        self.assertEqual(partner.employees_count, 2)


@tagged("post_install", "-at_install")
class TestHrAuditCoverage(TestHrCommon):
    """New coverage for business-critical paths that had no Python tests."""

    def _new_employee(self, name, **vals):
        return self.env["hr.employee"].create(
            {"name": name, "date_version": "2020-01-01", **vals}
        )

    def test_department_manager_propagation(self):
        """Changing a department's manager re-parents exactly the employees who
        reported to the *old* manager, and leaves others untouched."""
        m1 = self._new_employee("Manager 1")
        m2 = self._new_employee("Manager 2")
        other = self._new_employee("Other Manager")
        dept = self.env["hr.department"].create({"name": "Sales", "manager_id": m1.id})

        e1 = self._new_employee("Emp 1", department_id=dept.id, parent_id=m1.id)
        e2 = self._new_employee("Emp 2", department_id=dept.id, parent_id=m1.id)
        e3 = self._new_employee("Emp 3", department_id=dept.id, parent_id=other.id)

        dept.manager_id = m2.id

        self.assertEqual(e1.parent_id, m2, "old manager's report moves to the new one")
        self.assertEqual(e2.parent_id, m2, "old manager's report moves to the new one")
        self.assertEqual(
            e3.parent_id, other, "a member reporting elsewhere is left untouched"
        )

    @freeze_time("2026-07-13")
    def test_notify_expiring_contract_and_work_permit(self):
        """The expiry cron schedules an activity for contracts/permits landing
        exactly on the company's notice window, and nothing for those outside it."""
        company = self.env.company
        today = fields.Date.from_string("2026-07-13")
        contract_notice = company.contract_expiration_notice_period
        wp_notice = company.work_permit_expiration_notice_period

        expiring = self._new_employee(
            "Expiring Contract",
            contract_date_start="2020-01-01",
            contract_date_end=fields.Date.to_string(
                today + relativedelta(days=contract_notice)
            ),
        )
        safe = self._new_employee(
            "Safe Contract",
            contract_date_start="2020-01-01",
            contract_date_end=fields.Date.to_string(
                today + relativedelta(days=contract_notice + 30)
            ),
        )
        wp_expiring = self._new_employee(
            "Expiring Permit",
            work_permit_expiration_date=fields.Date.to_string(
                today + relativedelta(days=wp_notice)
            ),
        )

        self.env["hr.employee"].notify_expiring_contract_work_permit()

        self.assertTrue(
            expiring.activity_ids, "expiring contract gets a reminder activity"
        )
        self.assertFalse(
            safe.activity_ids, "a contract well within its term gets no reminder"
        )
        self.assertTrue(
            wp_expiring.activity_ids, "expiring work permit gets a reminder activity"
        )

    def test_verify_pin_rejects_non_digits(self):
        emp = self._new_employee("Pin Guy")
        with self.assertRaises(ValidationError):
            emp.pin = "12ab"
        emp.pin = "1234"
        self.assertEqual(emp.pin, "1234")


@tagged("post_install", "-at_install")
class TestHrAuditRound2(TestHrCommon):
    """Regression tests for the round-2 audit (empirically reproduced bugs)."""

    def _new_employee(self, name, **vals):
        return self.env["hr.employee"].create(
            {"name": name, "date_version": "2020-01-01", **vals}
        )

    def test_self_write_cannot_mint_trusted_bank_account(self):
        """An ordinary employee must NOT be able to create/trust a bank account by
        self-writing ``employee_bank_account_ids`` on their own user record.

        Regression: that field sat in HR_WRITABLE_FIELDS, and res.users.write
        elevates a self-write to superuser when every key is self-writable
        (gating only on top-level key names). So `[(0, 0, {...})]` created a
        *trusted* res.partner.bank on an arbitrary partner under sudo — a
        vendor-payment fraud vector.
        """
        user = mail_new_test_user(
            self.env, login="plainuser", groups="base.group_user", name="Plain User"
        )
        self.env["hr.employee"].create({"name": "Plain User", "user_id": user.id})
        vendor = self.env["res.partner"].create(
            {"name": "Vendor X", "is_company": True}
        )

        # The field must not be in the self-writable set.
        self.assertNotIn(
            "employee_bank_account_ids",
            self.env["res.users"].SELF_WRITEABLE_FIELDS,
        )

        user_self = self.env["res.users"].with_user(user).browse(user.id)
        with self.assertRaises(AccessError):
            user_self.write(
                {
                    "employee_bank_account_ids": [
                        (
                            0,
                            0,
                            {
                                "partner_id": vendor.id,
                                "acc_number": "ATTACKER-0001",
                                "allow_out_payment": True,
                            },
                        )
                    ]
                }
            )
        self.assertFalse(
            self.env["res.partner.bank"]
            .sudo()
            .search([("acc_number", "=", "ATTACKER-0001")]),
            "no bank account should have been created",
        )

    def test_bank_account_number_masking(self):
        """Masking never reveals more than the last 4 chars and never corrupts.

        Regression: the old slice showed the full number for length 6 and
        produced a duplicated-digit string for length 5.
        """
        mask = self.env["res.partner.bank"]._mask_account_number
        self.assertEqual(mask("1234"), "****")
        self.assertEqual(mask("12345"), "*2345")
        self.assertEqual(mask("123456"), "**3456")
        self.assertEqual(mask("1234567"), "12*4567")
        self.assertEqual(mask("0011223344556677"), "00**********6677")
        # Property: output length matches, and the interior is never the raw value.
        for acc in ("12345", "123456", "1234567", "0011223344556677"):
            masked = mask(acc)
            self.assertEqual(len(masked), len(acc))
            self.assertNotEqual(masked, acc)

    def test_bank_account_masking_end_to_end_non_hr(self):
        """A non-HR user reading an employee bank account sees a masked name."""
        emp = self._new_employee("Masked Guy")
        ba = self.env["res.partner.bank"].create(
            {"acc_number": "123456", "partner_id": emp.work_contact_id.id}
        )
        emp.bank_account_ids = [(4, ba.id)]
        plain = mail_new_test_user(
            self.env, login="plainreader", groups="base.group_user", name="Reader"
        )
        display = ba.with_user(plain).display_name
        self.assertNotIn("123456", display, "the full number must not be exposed")
        self.assertEqual(display, "**3456")

    def test_combine_tz_uses_correct_offset(self):
        """``_combine_tz`` localizes via pytz (correct DST/standard offset), not
        the historical LMT offset produced by ``.replace(tzinfo=...)``."""
        mx = timezone("America/Mexico_City")
        dt = self.env["hr.employee"]._combine_tz(date(2026, 7, 1), time.min, mx)
        # America/Mexico_City is UTC-6 (no DST since 2022); the LMT bug gave ~-6:36.
        self.assertEqual(dt.utcoffset(), timedelta(hours=-6))
        # The buggy path would have differed:
        buggy = datetime.combine(date(2026, 7, 1), time.min).replace(tzinfo=mx)
        self.assertNotEqual(dt.utcoffset(), buggy.utcoffset())
        # Falsy tz -> naive datetime, unchanged behavior.
        self.assertIsNone(
            self.env["hr.employee"]._combine_tz(date(2026, 7, 1), time.min, None).tzinfo
        )

    def test_leave_on_version_last_day_gets_calendar(self):
        """A leave on a version's inclusive ``date_end`` is assigned that version's
        calendar (regression: the exclusive midnight bound dropped last-day leaves)."""
        cal1 = self.env["resource.calendar"].search([], limit=1)
        cal2 = self.env["resource.calendar"].create({"name": "R2 Cal2"})
        emp = self._new_employee("Leave Guy", resource_calendar_id=cal1.id)
        emp.create_version(
            {"date_version": "2026-01-01", "contract_date_start": "2026-01-01"}
        )
        # A future version bounds the current one, so its date_end is set.
        emp.create_version(
            {"date_version": "2026-08-01", "resource_calendar_id": cal2.id}
        )
        current = emp.version_id
        self.assertEqual(str(current.date_end), "2026-07-31")

        leave = self.env["resource.calendar.leaves"].create(
            {
                "name": "last day",
                "resource_id": emp.resource_id.id,
                "date_from": datetime(2026, 7, 31, 9, 0),
                "date_to": datetime(2026, 7, 31, 17, 0),
            }
        )
        leave.invalidate_recordset(["calendar_id"])
        self.assertEqual(
            leave.calendar_id,
            current.resource_calendar_id,
            "a leave on the version's last valid day must get that version's calendar",
        )

    def test_create_version_end_without_start_raises_clean_error(self):
        """create_version with a contract end date at a non-contract date raises a
        clear UserError instead of an opaque DB CheckViolation, and does not touch
        sibling versions."""
        emp = self._new_employee("NoContract Guy")
        emp.create_version({"date_version": "2019-01-01"})
        versions_before = self.env["hr.version"].search([("employee_id", "=", emp.id)])
        self.assertFalse(emp._is_in_contract(date(2026, 3, 1)))

        with self.assertRaises(UserError):
            emp.create_version(
                {"date_version": "2026-03-01", "contract_date_end": "2026-12-31"}
            )

        # No sibling version was stamped with an end date.
        self.assertFalse(
            versions_before.filtered("contract_date_end"),
            "no version should have gained a contract end date",
        )
