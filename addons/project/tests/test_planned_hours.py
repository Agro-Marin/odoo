"""``planned_hours``: the PMBOK formula, and the override that must outlive it."""

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
        """The field advertises an override and the inverse logs one, but the
        formula used to take it straight back: an estimate entered before the
        dates was replaced the moment the task was scheduled."""
        task = self._task(planned_hours=3.0)
        self.assertEqual(task.planned_hours, 3.0)
        self.assertTrue(task.planned_hours_manual)

        task.write({"planned_date_begin": self.START, "date_end": self.END})

        self.assertEqual(
            task.planned_hours, 3.0, "scheduling must not discard the estimate"
        )

    def test_one_write_and_two_writes_agree(self) -> None:
        """The outcome used to depend on the shape of the write rather than on
        the intent: "3 h" plus dates in one save kept the 3, the same two values
        in two saves did not."""
        one_write = self._task(
            planned_hours=3.0, planned_date_begin=self.START, date_end=self.END
        )
        two_writes = self._task(planned_hours=3.0)
        two_writes.write({"planned_date_begin": self.START, "date_end": self.END})

        self.assertEqual(one_write.planned_hours, two_writes.planned_hours)
        self.assertEqual(one_write.planned_hours, 3.0)

    def test_an_override_outlives_a_later_date_change(self) -> None:
        """An override that was accepted *and written to the chatter* was then
        silently reverted by any later nudge of a date, leaving the log entry
        describing a value the record no longer held."""
        task = self._task(planned_date_begin=self.START, date_end=self.END)
        task.write({"planned_hours": 9.0})
        self.assertTrue(task.planned_hours_manual)

        task.write({"date_end": datetime(2026, 9, 1, 14, 0)})

        self.assertEqual(
            task.planned_hours, 9.0, "a date change must not revert an override"
        )

    def test_writing_the_formula_value_back_hands_the_field_over(self) -> None:
        """The way out of an override: agree with the formula."""
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
        """With no dates the formula has no opinion, so the estimate is not
        contradicting anything — flag it, but do not narrate it."""
        task = self._task()
        before = len(task.message_ids)
        task.write({"planned_hours": 3.0})
        bodies = task.message_ids[: len(task.message_ids) - before].mapped("body")
        self.assertFalse(any("manually overridden" in (body or "") for body in bodies))
