from datetime import datetime, timedelta

from odoo.exceptions import AccessError

from odoo.addons.digest.tests.common import TestDigestCommon
from odoo.addons.mail.tests.common import mail_new_test_user


class TestEventDigest(TestDigestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.user_eventmanager = mail_new_test_user(
            cls.env,
            login="user_eventmanager_digest",
            groups="base.group_user,event.group_event_manager",
            name="Eglantine Manager",
        )
        cls.user_employee = mail_new_test_user(
            cls.env,
            login="user_employee_digest",
            groups="base.group_user",
            name="Eusebio Employee",
        )

        def _event(company, name):
            return cls.env["event.event"].create(
                {
                    "name": name,
                    "company_id": company.id if company else False,
                    "date_begin": datetime.now() + timedelta(days=1),
                    "date_end": datetime.now() + timedelta(days=2),
                    "event_mail_ids": [],
                    "question_ids": [],
                }
            )

        event_1 = _event(cls.company_1, "Digest Event 1")
        event_2 = _event(cls.company_2, "Digest Event 2")

        cls.env["event.registration"].create(
            [{"event_id": event_1.id, "name": f"Attendee {i}"} for i in range(3)]
            + [{"event_id": event_2.id, "name": "Other company attendee"}]
        )
        # outside the digest window: created long before the period it reports on
        old = cls.env["event.registration"].create(
            {"event_id": event_1.id, "name": "Ancient attendee"}
        )
        cls.env.cr.execute(
            "UPDATE event_registration SET create_date = %s WHERE id = %s",
            (datetime.now() - timedelta(days=700), old.id),
        )
        cls.env["event.registration"].invalidate_model(["create_date"])

    def test_kpi_nbr_of_registrations_value(self):
        self.assertEqual(self.digest_1.kpi_nbr_of_registrations_value, 3)
        self.assertEqual(
            self.digest_2.kpi_nbr_of_registrations_value,
            1,
            "this digest belongs to the other company",
        )
        self.assertEqual(
            self.digest_3.kpi_nbr_of_registrations_value,
            3,
            "a digest with no company reports on the current one",
        )

    def test_kpi_nbr_of_registrations_is_reserved_to_event_managers(self):
        digest = self.digest_1
        self.assertEqual(
            digest.with_user(self.user_eventmanager).kpi_nbr_of_registrations_value, 3
        )
        digest.invalidate_recordset()
        with self.assertRaises(AccessError):
            digest.with_user(self.user_employee).kpi_nbr_of_registrations_value

    def test_kpi_nbr_of_registrations_reaches_the_digest_mail(self):
        digest = self.digest_1
        digest.kpi_nbr_of_registrations = True
        kpis = digest._get_kpi_data(self.company_1, self.env.user)
        row = next(
            (k for k in kpis if k["kpi_name"] == "kpi_nbr_of_registrations"), None
        )
        self.assertIsNotNone(row, "the KPI must reach the rendered digest")
        self.assertEqual(row["kpi_action"], "event.action_registration")
