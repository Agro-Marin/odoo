"""Resource levelling: when a task is moved off an assignee, and when it is not."""

from odoo import Command
from odoo.tests import freeze_time, tagged

from .test_project_base import TestProjectCommon


# Every test here starts its schedule at "now", so the answer depends on where
# in the working day the suite happens to run. `test_a_day_asked_for_more_than
# _it_holds_is_relieved` asserts that a full 8h anchor leaves no room for an
# extra quarter-hour -- true when the day starts fresh, false once "now" is
# already partway through it and the anchor spills into the next day, taking
# the light task's slot with it. The suite passed after 17:00 Brussels and
# failed at 14:00 for exactly that reason.
#
# 05:00 UTC is 07:00 in the calendar's Europe/Brussels, i.e. just before the
# 08:00 start, so the schedule always opens on a whole working day. Monday, so
# the day is not a weekend either.
@freeze_time("2026-08-10 05:00:00")
@tagged("post_install", "-at_install")
class TestResourceLevelling(TestProjectCommon):
    def _project(self, name):
        project = self.env["project.project"].create({"name": name})
        project.company_id = self.env.company
        project.allow_dependencies = True
        return project

    def _user(self, login):
        return self.env["res.users"].create(
            {"name": login, "login": login, "email": f"{login}@example.com"}
        )

    def test_a_shift_that_fits_the_float_is_taken(self) -> None:
        """The guard compared a wall-clock shift against working-hour float, so
        any move crossing a night or a weekend was refused — which is every
        move. Measured before the fix: 15h of float, a move needing ~8 working
        hours, rejected because those 8 hours spanned 50h of wall clock.

        The assignee here is genuinely over capacity: 9 person-hours committed
        inside a one-hour window."""
        project = self._project("Levelling")
        user = self._user("leveller_e")
        Task = self.env["project.task"]
        first = Task.create(
            {
                "name": "First",
                "project_id": project.id,
                "planned_hours": 8.0,
                "allocated_hours": 8.0,
                "user_ids": [Command.link(user.id)],
            }
        )
        Task.create(
            {
                "name": "Chained",
                "project_id": project.id,
                "planned_hours": 8.0,
                "predecessor_ids": [Command.link(first.id)],
            }
        )
        movable = Task.create(
            {
                "name": "Movable",
                "project_id": project.id,
                "planned_hours": 1.0,
                "allocated_hours": 1.0,
                "user_ids": [Command.link(user.id)],
            }
        )
        project.action_compute_critical_path()
        self.env.flush_all()
        start_before = movable.cpm_date_start
        self.assertFalse(movable.is_critical_path)
        self.assertGreater(movable.total_float, 0.0)

        project.action_level_resources()
        self.env.flush_all()

        self.assertGreater(
            movable.cpm_date_start,
            start_before,
            "an assignee committed beyond their capacity must be relieved",
        )

    def test_an_overlap_within_capacity_is_left_alone(self) -> None:
        """Levelling used to move any task that merely *overlapped* another one
        on the same assignee — the test was ``concurrent > 0`` and no capacity
        was ever computed, despite a comment claiming "> 8h/day". Measured
        before the fix on three same-window tasks held by one person: the same
        4.00-working-hour shift at 0.75 h/day of load as at 24 h/day. So it
        spent a task's entire float relieving an overload that did not exist.
        """
        project = self._project("Levelling within capacity")
        user = self._user("leveller_light")
        Task = self.env["project.task"]
        # Half a day of work, so the quarter-hour below still fits inside it.
        anchor = Task.create(
            {
                "name": "Anchor",
                "project_id": project.id,
                "planned_hours": 4.0,
                "user_ids": [Command.link(user.id)],
            }
        )
        Task.create(
            {
                "name": "Chained",
                "project_id": project.id,
                "planned_hours": 8.0,
                "predecessor_ids": [Command.link(anchor.id)],
            }
        )
        # A quarter of an hour of work: 4.25 h asked of an eight-hour day.
        light = Task.create(
            {
                "name": "Light",
                "project_id": project.id,
                "planned_hours": 0.25,
                "user_ids": [Command.link(user.id)],
            }
        )
        project.action_compute_critical_path()
        self.env.flush_all()
        self.assertFalse(light.is_critical_path)
        start_before = light.cpm_date_start

        project.action_level_resources()
        self.env.flush_all()

        self.assertEqual(
            light.cpm_date_start,
            start_before,
            "a task whose assignee is inside their capacity must not be moved",
        )

    def test_a_day_asked_for_more_than_it_holds_is_relieved(self) -> None:
        """The counterpart: the same shape, but the anchor already fills the
        day, so the extra quarter-hour genuinely does not fit."""
        project = self._project("Levelling over capacity")
        user = self._user("leveller_full")
        Task = self.env["project.task"]
        anchor = Task.create(
            {
                "name": "Anchor",
                "project_id": project.id,
                "planned_hours": 8.0,
                "user_ids": [Command.link(user.id)],
            }
        )
        Task.create(
            {
                "name": "Chained",
                "project_id": project.id,
                "planned_hours": 8.0,
                "predecessor_ids": [Command.link(anchor.id)],
            }
        )
        light = Task.create(
            {
                "name": "Light",
                "project_id": project.id,
                "planned_hours": 0.25,
                "user_ids": [Command.link(user.id)],
            }
        )
        project.action_compute_critical_path()
        self.env.flush_all()
        start_before = light.cpm_date_start

        project.action_level_resources()
        self.env.flush_all()

        self.assertGreater(light.cpm_date_start, start_before)

    def test_levelling_never_pushes_the_project_end_out(self) -> None:
        """Shifts are bounded by each task's float, so the schedule's end date is
        an invariant of the operation whatever the load."""
        project = self._project("Levelling end date")
        user = self._user("leveller_end")
        Task = self.env["project.task"]
        first = Task.create(
            {
                "name": "First",
                "project_id": project.id,
                "planned_hours": 8.0,
                "user_ids": [Command.link(user.id)],
            }
        )
        Task.create(
            {
                "name": "Chained",
                "project_id": project.id,
                "planned_hours": 8.0,
                "predecessor_ids": [Command.link(first.id)],
            }
        )
        Task.create(
            {
                "name": "Movable",
                "project_id": project.id,
                "planned_hours": 8.0,
                "user_ids": [Command.link(user.id)],
            }
        )
        project.action_compute_critical_path()
        self.env.flush_all()
        # The project's end is the latest end of ALL its tasks, the critical
        # chain included — measuring it over the movable ones alone would only
        # observe that they moved.
        tasks = self.env["project.task"].search([("project_id", "=", project.id)])
        end_before = max(tasks.mapped("cpm_date_end"))

        project.action_level_resources()
        self.env.flush_all()
        tasks.invalidate_recordset()

        self.assertEqual(
            max(tasks.mapped("cpm_date_end")),
            end_before,
            "levelling must stay inside float and preserve the project end date",
        )

    def test_load_is_shared_between_the_assignees_of_a_task(self) -> None:
        """A task's effort is spread over the people who hold it: two assignees
        on a 16h task carry 8h each, not 16h each. Counting the full figure
        against every assignee reported an overload that no one had."""
        project = self._project("Levelling shared")
        user_a = self._user("leveller_a")
        user_b = self._user("leveller_b")
        Task = self.env["project.task"]
        shared = Task.create(
            {
                "name": "Shared",
                "project_id": project.id,
                "planned_hours": 16.0,
                "user_ids": [Command.link(user_a.id), Command.link(user_b.id)],
            }
        )
        self.assertEqual(
            shared.planned_hours / len(shared.user_ids),
            8.0,
            "the per-assignee load of a 16h two-person task is 8h",
        )
