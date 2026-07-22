from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tests import TransactionCase, tagged


@tagged("recruitment")
class TestCertificationActivities(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = date.today()
        cls.demo_data_activities = cls.env["hr.employee"]._add_certification_activity_to_employees()

        cls.t_job = cls.env["hr.job"].create({"name": "Test Job"})
        cls.t_user_1, cls.t_user_2 = cls.env["res.users"].create(
            [
                {
                    "name": "Test User 1",
                    "login": "user_1",
                    "password": "password",
                },
                {
                    "name": "Test User 2",
                    "login": "user_2",
                    "password": "password",
                },
            ],
        )
        cls.t_cert_type = cls.env["hr.skill.type"].create({"name": "Certification for tests", "is_certification": True})
        cls.t_cert_level_1, cls.t_cert_level_2 = cls.env["hr.skill.level"].create(
            [
                {"name": "Half Certified", "skill_type_id": cls.t_cert_type.id, "level_progress": 50},
                {"name": "Fully Certified", "skill_type_id": cls.t_cert_type.id, "level_progress": 100},
            ],
        )
        cls.t_cert_1, cls.t_cert_2 = cls.env["hr.skill"].create(
            [
                {"name": "Certification 1", "skill_type_id": cls.t_cert_type.id},
                {"name": "Certification 2", "skill_type_id": cls.t_cert_type.id},
            ],
        )
        cls.t_job_cert_1, cls.t_job_cert_2 = cls.env["hr.job.skill"].create(
            [
                {
                    "job_id": cls.t_job.id,
                    "skill_id": cls.t_cert_1.id,
                    "skill_level_id": cls.t_cert_level_1.id,
                    "skill_type_id": cls.t_cert_type.id,
                    "valid_from": cls.today,
                    "valid_to": False,
                },
                {
                    "job_id": cls.t_job.id,
                    "skill_id": cls.t_cert_2.id,
                    "skill_level_id": cls.t_cert_level_2.id,
                    "skill_type_id": cls.t_cert_type.id,
                    "valid_from": cls.today,
                    "valid_to": False,
                },
            ],
        )

        cls.t_employee_1 = cls.env["hr.employee"].create(
            [
                {"name": "test employee 1", "job_id": cls.t_job.id, "user_id": cls.t_user_1.id},
            ],
        )

    def test_employee_with_no_certifications_gets_activity(self):
        """Employee missing all job certifications gets one activity per missing certification."""
        activities = self.env["hr.employee"]._add_certification_activity_to_employees()
        self.assertEqual(len(activities), 2)
        self.assertEqual(self.t_job.job_skill_ids.mapped("display_name"), activities.mapped("summary"))
        self.assertEqual(set(activities.mapped("res_id")), set(self.t_employee_1.ids))

    def test_employee_with_correct_certifications_gets_no_activity(self):
        """Employee with all job certifications gets no activity."""
        self.env["hr.employee.skill"].create(
            [
                {
                    "employee_id": self.t_employee_1.id,
                    "skill_id": self.t_cert_1.id,
                    "skill_level_id": self.t_cert_level_1.id,
                    "skill_type_id": self.t_cert_type.id,
                    "valid_from": self.today,
                    "valid_to": False,
                },
                {
                    "employee_id": self.t_employee_1.id,
                    "skill_id": self.t_cert_2.id,
                    "skill_level_id": self.t_cert_level_2.id,
                    "skill_type_id": self.t_cert_type.id,
                    "valid_from": self.today,
                    "valid_to": False,
                },
            ],
        )
        activities = self.env["hr.employee"]._add_certification_activity_to_employees()
        self.assertFalse(activities)

    def test_employee_with_wrong_certifications_gets_activity(self):
        """Employee with the correct certification but the wrong level gets an activity."""
        self.env["hr.employee.skill"].create(
            {
                "employee_id": self.t_employee_1.id,
                "skill_id": self.t_cert_1.id,
                "skill_level_id": self.t_cert_level_2.id,
                "skill_type_id": self.t_cert_type.id,
                "valid_from": self.today,
                "valid_to": False,
            },
        )
        activities = self.env["hr.employee"]._add_certification_activity_to_employees()
        self.assertEqual(len(activities), 2)
        self.assertEqual(self.t_job.job_skill_ids.mapped("display_name"), activities.mapped("summary"))
        self.assertEqual(set(activities.mapped("res_id")), set(self.t_employee_1.ids))

    def test_employee_with_one_correct_certification_gets_one_activity(self):
        """Employee with one of two job certifications gets one activity."""
        self.env["hr.employee.skill"].create(
            {
                "employee_id": self.t_employee_1.id,
                "skill_id": self.t_cert_1.id,
                "skill_level_id": self.t_cert_level_1.id,
                "skill_type_id": self.t_cert_type.id,
                "valid_from": self.today,
                "valid_to": False,
            },
        )
        activities = self.env["hr.employee"]._add_certification_activity_to_employees()
        self.assertEqual(len(activities), 1)
        self.assertEqual(self.t_job_cert_2.mapped("display_name"), activities.mapped("summary"))
        self.assertEqual(set(activities.mapped("res_id")), set(self.t_employee_1.ids))

    def test_employee_with_correct_but_expired_certifications_gets_activity(self):
        """Employee whose job certifications are expired (valid_to < today) gets activities."""
        self.env["hr.employee.skill"].create(
            [
                {
                    "employee_id": self.t_employee_1.id,
                    "skill_id": self.t_cert_1.id,
                    "skill_level_id": self.t_cert_level_1.id,
                    "skill_type_id": self.t_cert_type.id,
                    "valid_from": self.today - relativedelta(months=2),
                    "valid_to": self.today - relativedelta(months=1),
                },
                {
                    "employee_id": self.t_employee_1.id,
                    "skill_id": self.t_cert_2.id,
                    "skill_level_id": self.t_cert_level_2.id,
                    "skill_type_id": self.t_cert_type.id,
                    "valid_from": self.today - relativedelta(months=2),
                    "valid_to": self.today - relativedelta(months=1),
                },
            ],
        )
        activities = self.env["hr.employee"]._add_certification_activity_to_employees()
        self.assertEqual(len(activities), 2)
        self.assertEqual(self.t_job.job_skill_ids.mapped("display_name"), activities.mapped("summary"))
        self.assertEqual(set(activities.mapped("res_id")), set(self.t_employee_1.ids))

    def test_employee_with_correct_but_expiring_in_3_months_certifications_gets_activity(self):
        """Employee with a job certification expiring within the next 3 months gets an activity."""
        self.env["hr.employee.skill"].create(
            [
                {
                    "employee_id": self.t_employee_1.id,
                    "skill_id": self.t_cert_1.id,
                    "skill_level_id": self.t_cert_level_1.id,
                    "skill_type_id": self.t_cert_type.id,
                    "valid_from": self.today - relativedelta(months=2),
                    "valid_to": self.today + relativedelta(months=3),
                },
                {
                    "employee_id": self.t_employee_1.id,
                    "skill_id": self.t_cert_2.id,
                    "skill_level_id": self.t_cert_level_2.id,
                    "skill_type_id": self.t_cert_type.id,
                    "valid_from": self.today - relativedelta(months=2),
                    "valid_to": self.today + relativedelta(months=4),
                },
            ],
        )
        activities = self.env["hr.employee"]._add_certification_activity_to_employees()
        self.assertEqual(len(activities), 1)
        self.assertEqual(self.t_job_cert_1.mapped("display_name"), activities.mapped("summary"))
        self.assertEqual(set(activities.mapped("res_id")), set(self.t_employee_1.ids))

    def test_activities_are_only_created_once(self):
        """An activity is created only once for an employee missing skills."""
        activities = self.env["hr.employee"]._add_certification_activity_to_employees()
        self.assertEqual(len(activities), 2)
        self.assertEqual(self.t_job.job_skill_ids.mapped("display_name"), activities.mapped("summary"))
        self.assertEqual(set(activities.mapped("res_id")), set(self.t_employee_1.ids))

        new_activities = self.env["hr.employee"]._add_certification_activity_to_employees()
        self.assertFalse(new_activities)

    def test_activities_are_created_for_multiple_employees_with_no_certification(self):
        """Activities are created for multiple employees with no certifications."""
        employee_2 = self.env["hr.employee"].create(
            {"name": "test employee 2", "job_id": self.t_job.id, "user_id": self.t_user_2.id},
        )
        activities = self.env["hr.employee"]._add_certification_activity_to_employees()
        self.assertEqual(len(activities), 4)
        self.assertEqual(set(self.t_job.job_skill_ids.mapped("display_name")), set(activities.mapped("summary")))
        self.assertEqual(set(activities.mapped("res_id")), set(self.t_employee_1.ids) | set(employee_2.ids))

    def test_no_activities_are_created_for_multiple_employees_with_certification(self):
        """No activities are created for multiple employees with the correct certifications."""
        employee_2 = self.env["hr.employee"].create(
            {"name": "test employee 2", "job_id": self.t_job.id, "user_id": self.t_user_2.id},
        )
        self.env["hr.employee.skill"].create(
            [
                {
                    "employee_id": self.t_employee_1.id,
                    "skill_id": self.t_cert_1.id,
                    "skill_level_id": self.t_cert_level_1.id,
                    "skill_type_id": self.t_cert_type.id,
                    "valid_from": self.today,
                    "valid_to": False,
                },
                {
                    "employee_id": self.t_employee_1.id,
                    "skill_id": self.t_cert_2.id,
                    "skill_level_id": self.t_cert_level_2.id,
                    "skill_type_id": self.t_cert_type.id,
                    "valid_from": self.today,
                    "valid_to": False,
                },
                {
                    "employee_id": employee_2.id,
                    "skill_id": self.t_cert_1.id,
                    "skill_level_id": self.t_cert_level_1.id,
                    "skill_type_id": self.t_cert_type.id,
                    "valid_from": self.today,
                    "valid_to": False,
                },
                {
                    "employee_id": employee_2.id,
                    "skill_id": self.t_cert_2.id,
                    "skill_level_id": self.t_cert_level_2.id,
                    "skill_type_id": self.t_cert_type.id,
                    "valid_from": self.today,
                    "valid_to": False,
                },
            ],
        )
        activities = self.env["hr.employee"]._add_certification_activity_to_employees()
        self.assertFalse(activities)
