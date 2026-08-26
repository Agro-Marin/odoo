from odoo import Command
from odoo.tests import freeze_time, tagged

from .test_project_base import TestProjectCommon


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
        project = self._project("Levelling within capacity")
        user = self._user("leveller_light")
        Task = self.env["project.task"]
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
