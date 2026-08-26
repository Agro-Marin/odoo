from datetime import datetime

from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestPlannedHours(TestProjectCommon):
    START = datetime(2026, 9, 1, 8, 0)
    END = datetime(2026, 9, 1, 12, 0)

    def _task(self, **vals):
        return self.env["project.task"].create(
            {"name": "Estimate", "project_id": self.project_pigs.id, **vals}
        )

    def test_the_formula_drives_a_scheduled_task(self) -> None:
        task = self._task(planned_date_begin=self.START, date_end=self.END)
        self.assertEqual(task.planned_hours, task.scheduled_hours)
        self.assertFalse(task.planned_hours_manual)

    def test_resources_and_units_multiply_the_duration(self) -> None:
        task = self._task(
            planned_date_begin=self.START, date_end=self.END, planned_resources=2
        )
        self.assertEqual(task.planned_hours, task.scheduled_hours * 2)

    def test_an_unscheduled_estimate_survives_scheduling(self) -> None:
        task = self._task(planned_hours=3.0)
        self.assertEqual(task.planned_hours, 3.0)
        self.assertTrue(task.planned_hours_manual)

        task.write({"planned_date_begin": self.START, "date_end": self.END})

        self.assertEqual(
            task.planned_hours, 3.0, "scheduling must not discard the estimate"
        )

    def test_one_write_and_two_writes_agree(self) -> None:
        one_write = self._task(
            planned_hours=3.0, planned_date_begin=self.START, date_end=self.END
        )
        two_writes = self._task(planned_hours=3.0)
        two_writes.write({"planned_date_begin": self.START, "date_end": self.END})

        self.assertEqual(one_write.planned_hours, two_writes.planned_hours)
        self.assertEqual(one_write.planned_hours, 3.0)

    def test_an_override_outlives_a_later_date_change(self) -> None:
        task = self._task(planned_date_begin=self.START, date_end=self.END)
        task.write({"planned_hours": 9.0})
        self.assertTrue(task.planned_hours_manual)

        task.write({"date_end": datetime(2026, 9, 1, 14, 0)})

        self.assertEqual(
            task.planned_hours, 9.0, "a date change must not revert an override"
        )

    def test_writing_the_formula_value_back_hands_the_field_over(self) -> None:
        task = self._task(planned_date_begin=self.START, date_end=self.END)
        task.write({"planned_hours": 9.0})
        self.assertTrue(task.planned_hours_manual)

        task.write({"planned_hours": task.scheduled_hours})
        self.assertFalse(task.planned_hours_manual)

        task.write({"date_end": datetime(2026, 9, 1, 16, 0)})
        self.assertEqual(
            task.planned_hours,
            task.scheduled_hours,
            "once handed back, the formula drives the field again",
        )

    def test_an_override_against_a_real_formula_is_logged(self) -> None:
        task = self._task(planned_date_begin=self.START, date_end=self.END)
        before = len(task.message_ids)
        task.write({"planned_hours": 9.0})
        bodies = task.message_ids[: len(task.message_ids) - before].mapped("body")
        self.assertTrue(
            any("manually overridden" in (body or "") for body in bodies),
            "an override of a formula that produced a value is worth a chatter line",
        )

    def test_an_estimate_on_an_unscheduled_task_is_not_logged(self) -> None:
        task = self._task()
        before = len(task.message_ids)
        task.write({"planned_hours": 3.0})
        bodies = task.message_ids[: len(task.message_ids) - before].mapped("body")
        self.assertFalse(any("manually overridden" in (body or "") for body in bodies))

    def test_planned_hours_estimate_is_not_a_formula_override(self) -> None:
        task = self.env["project.task"].create(
            {
                "name": "estimate",
                "project_id": self.project_pigs.id,
                "planned_hours": 5.0,
            }
        )
        self.assertFalse(
            any("manually overridden" in str(m.body) for m in task.message_ids)
        )

    def test_planned_hours_override_is_logged_once_per_batch(self) -> None:
        tasks = self.env["project.task"].create(
            [
                {
                    "name": f"t{i}",
                    "project_id": self.project_pigs.id,
                    "planned_date_begin": "2026-08-03 08:00:00",
                    "date_end": "2026-08-04 17:00:00",
                }
                for i in range(3)
            ]
        )
        self.env.flush_all()
        tasks.write({"planned_hours": 999.0})
        self.env.flush_all()
        for task in tasks:
            self.assertTrue(
                any("manually overridden" in str(m.body) for m in task.message_ids)
            )
