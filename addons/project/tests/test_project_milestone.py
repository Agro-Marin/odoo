from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import Form, tagged

from .test_project_base import TestProjectCommon


@tagged("-at_install", "post_install")
class TestProjectMilestone(TestProjectCommon):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref("project.group_project_milestone")
        cls.milestone_pigs, cls.milestone_goats = (
            cls.env["project.milestone"]
            .with_context({"mail_create_nolog": True})
            .create(
                [
                    {
                        "name": "Milestone Pigs",
                        "project_id": cls.project_pigs.id,
                    },
                    {
                        "name": "Milestone Goats",
                        "project_id": cls.project_goats.id,
                    },
                ]
            )
        )

    def test_milestones_settings_change(self) -> None:
        self.env.user.group_ids -= self.env.ref("project.group_project_milestone")
        project1 = self.env["project.project"].create(
            {"name": "Test allow_milestones on New Project"}
        )
        self.assertFalse(
            project1.allow_milestones,
            'The "Milestones" feature should be disabled by default when the feature is disabled globally.',
        )
        with Form(self.env["project.project"]) as project_form:
            project_form.name = "My Mouses Project"
            self.assertFalse(
                project_form.allow_milestones,
                "New projects allow_milestones should be False by default.",
            )

        self.env.user.group_ids |= self.env.ref("project.group_project_milestone")
        project2 = self.env["project.project"].create(
            {"name": "Test allow_milestones on New Project"}
        )
        self.assertFalse(
            project2.allow_milestones,
            'The "Milestones" feature should still be disabled by default when the feature is enabled globally.',
        )
        with Form(self.env["project.project"]) as project_form:
            project_form.name = "My Mouses Project"
            self.assertFalse(
                project_form.allow_milestones,
                "New projects allow_milestones should be False by default.",
            )

    def test_change_project_in_task(self) -> None:
        self.task_1.milestone_id = self.milestone_pigs
        self.assertEqual(self.task_1.milestone_id, self.milestone_pigs)

        self.task_1.project_id = self.project_goats
        self.assertFalse(
            self.task_1.milestone_id,
            "No milestone should be linked to the task since its project has changed",
        )

        task_2 = (
            self.env["project.task"]
            .with_context({"mail_create_nolog": True})
            .create(
                {
                    "name": "Child MilestoneTask",
                    "user_ids": self.user_projectmanager,
                    "project_id": self.project_pigs.id,
                    "parent_id": self.task_1.id,
                    "milestone_id": self.milestone_pigs.id,
                }
            )
        )
        self.assertEqual(task_2.milestone_id, self.milestone_pigs)

        task_2.project_id = self.project_goats
        self.assertFalse(
            task_2.milestone_id,
            "No milestone should be linked to the task since its project has changed and its parent task has no milestone",
        )

        self.task_1.project_id = self.project_pigs
        self.task_1.milestone_id = self.milestone_pigs
        task_2.project_id = self.project_pigs
        task_2.milestone_id = self.milestone_pigs
        self.assertEqual(task_2.milestone_id, self.milestone_pigs)

        task_2.project_id = self.project_goats
        self.assertFalse(
            task_2.milestone_id,
            "No milestone should be linked to the task since its project has changed and its parent task belongs to another project",
        )

        self.task_1.project_id = self.project_goats
        self.task_1.milestone_id = self.milestone_goats
        task_2.project_id = self.project_pigs
        task_2.milestone_id = self.milestone_pigs
        self.assertEqual(task_2.milestone_id, self.milestone_pigs)
        task_2.project_id = self.project_goats
        self.assertEqual(
            task_2.milestone_id,
            self.milestone_goats,
            "The milestone of the task should be replaced by the one of its parent task as they now belong to the same project",
        )

        task_2.parent_id = False
        self.assertEqual(task_2.milestone_id, self.milestone_goats)
        task_2.project_id = False
        self.assertFalse(
            task_2.milestone_id,
            "No milestone should be linked to a private task",
        )

    def test_duplicate_project_duplicates_milestones_on_tasks(self) -> None:
        unique_name_1 = "unique_name_1"
        unique_name_2 = "unique_name_2"
        unique_names = [unique_name_1, unique_name_2]
        project = self.env["project.project"].create(
            {
                "name": "Test project",
                "allow_milestones": True,
            }
        )
        milestones = self.env["project.milestone"].create(
            [
                {
                    "name": unique_name_1,
                    "project_id": project.id,
                },
                {
                    "name": unique_name_2,
                    "project_id": project.id,
                },
            ]
        )
        tasks = self.env["project.task"].create(
            [
                {
                    "name": unique_name_1,
                    "project_id": project.id,
                    "milestone_id": milestones[0].id,
                },
                {
                    "name": unique_name_2,
                    "project_id": project.id,
                    "milestone_id": milestones[1].id,
                },
            ]
        )
        self.assertEqual(tasks[0].milestone_id, milestones[0])
        self.assertEqual(tasks[1].milestone_id, milestones[1])
        project_copy = project.copy()
        self.assertNotEqual(project_copy.milestone_ids, False)
        self.assertEqual(
            project.milestone_ids.mapped("name"),
            project_copy.milestone_ids.mapped("name"),
        )
        self.assertNotEqual(project_copy.task_ids, False)
        for milestone in project_copy.task_ids.milestone_id:
            self.assertTrue(milestone in project_copy.milestone_ids)
        for unique_name in unique_names:
            orig_task = project.task_ids.filtered(lambda t, n=unique_name: t.name == n)
            copied_task = project_copy.task_ids.filtered(
                lambda t, n=unique_name: t.name == n
            )
            self.assertEqual(
                orig_task.name,
                copied_task.name,
                "The copied_task should be a copy of the original task",
            )
            self.assertNotEqual(
                copied_task.milestone_id,
                False,
                "We should copy the milestone and it shouldn't be reset to false from _compute_milestone_id",
            )
            self.assertEqual(
                orig_task.milestone_id.name,
                copied_task.milestone_id.name,
                "the copied milestone should be a copy of the original ",
            )

    def test_duplicate_project_with_milestones_disabled(self) -> None:
        extra_milestone_pigs = (
            self.env["project.milestone"]
            .with_context({"mail_create_nolog": True})
            .create(
                {
                    "name": "Test Extra Milestone",
                    "project_id": self.project_pigs.id,
                }
            )
        )

        self.task_1.milestone_id = self.milestone_pigs
        self.task_2.milestone_id = extra_milestone_pigs
        self.project_pigs.allow_milestones = False
        project_copied = self.project_pigs.copy()
        project_copied.task_ids._compute_milestone_id()
        self.assertFalse(
            project_copied.allow_milestones,
            "The project copied should have the milestone feature disabled",
        )
        self.assertFalse(
            project_copied.milestone_ids,
            "The project copied should not have any milestone",
        )
        self.assertFalse(
            project_copied.task_ids.milestone_id,
            "None of the project's task should have a milestone",
        )

    def test_basic_milestone_write(self) -> None:
        extra_milestone_pigs = (
            self.env["project.milestone"]
            .with_context({"mail_create_nolog": True})
            .create(
                {
                    "name": "Test Extra Milestone",
                    "project_id": self.project_pigs.id,
                }
            )
        )

        self.task_1.project_id = self.project_pigs
        self.assertEqual(self.task_1.project_id, self.project_pigs)
        self.assertFalse(self.task_1.milestone_id)

        self.task_1.milestone_id = self.milestone_pigs
        self.assertEqual(
            self.task_1.milestone_id,
            self.milestone_pigs,
            "Assignation of a valid milestone to a task with no milestone is not working properly.",
        )
        self.task_1.milestone_id = extra_milestone_pigs
        self.assertEqual(
            self.task_1.milestone_id,
            extra_milestone_pigs,
            "Change of the milestone of a task to a milestone from the same project is not working properly.",
        )

        self.assertEqual(self.task_1.project_id, self.project_pigs)
        self.assertEqual(self.task_1.milestone_id, extra_milestone_pigs)

        self.task_1.write(
            {
                "milestone_id": self.milestone_goats.id,
                "project_id": self.project_goats.id,
            }
        )
        self.assertEqual(
            self.task_1.milestone_id,
            self.milestone_goats,
            "Changing the project of a task and its milestone simultaneously is not working properly.",
        )
        self.assertEqual(
            self.task_1.project_id,
            self.project_goats,
            "Changing the project of a task and its milestone simultaneously is not working properly.",
        )

        self.assertEqual(self.task_1.project_id, self.project_goats)
        self.assertEqual(self.task_1.milestone_id, self.milestone_goats)

        self.task_1.milestone_id = self.milestone_pigs
        self.assertFalse(
            self.task_1.milestone_id,
            "Setting the milestone of a task to an invalid value should reset the value of milestone_id.",
        )

    def test_set_milestone_parent_task(self) -> None:
        task_2, task_3 = (
            self.env["project.task"]
            .with_context({"mail_create_nolog": True})
            .create(
                [
                    {
                        "name": "Child MilestoneTask",
                        "user_ids": self.user_projectmanager,
                        "project_id": self.project_pigs.id,
                        "parent_id": self.task_1.id,
                    },
                    {
                        "name": "Grand-child MilestoneTask",
                        "user_ids": self.user_projectmanager,
                        "project_id": self.project_pigs.id,
                    },
                ]
            )
        )
        self.assertFalse(self.task_1.milestone_id)
        self.assertFalse(task_2.milestone_id)

        self.task_1.milestone_id = self.milestone_pigs
        self.assertEqual(
            task_2.milestone_id,
            self.milestone_pigs,
            "The milestone of the parent task should be set to its subtasks if they belong to the same project (or the subtask has not project set) and the subtask has no milestone already set.",
        )

        extra_milestone_pigs = (
            self.env["project.milestone"]
            .with_context({"mail_create_nolog": True})
            .create(
                {
                    "name": "Extra Milestone Pigs",
                    "project_id": self.project_pigs.id,
                }
            )
        )
        self.task_1.milestone_id = False
        task_2.milestone_id = extra_milestone_pigs
        self.assertFalse(self.task_1.milestone_id)
        self.assertEqual(task_2.milestone_id, extra_milestone_pigs)

        self.task_1.milestone_id = self.milestone_pigs
        self.assertEqual(
            task_2.milestone_id,
            extra_milestone_pigs,
            "The milestone of the child task should not be modified has it has already one set.",
        )

        task_2.project_id = self.project_goats
        self.assertFalse(task_2.milestone_id)
        self.task_1.milestone_id = extra_milestone_pigs
        self.assertFalse(
            task_2.milestone_id,
            "The milestone of the parent task should not be set to its child task as they belong to different projects.",
        )

        task_3.parent_id = task_2
        self.task_1.project_id = task_2.project_id = task_3.project_id = (
            self.project_pigs
        )
        self.task_1.milestone_id = task_2.milestone_id = task_3.milestone_id = False
        self.assertFalse(task_2.milestone_id)
        self.assertFalse(task_3.milestone_id)

        self.task_1.milestone_id = self.milestone_pigs
        self.assertEqual(
            task_3.milestone_id,
            self.milestone_pigs,
            "The milestone of the parent task should be set to its (grand)child tasks recursively.",
        )

        self.task_1.milestone_id = False
        task_2.milestone_id = self.milestone_pigs
        task_3.milestone_id = False
        self.assertFalse(self.task_1.milestone_id)
        self.assertFalse(task_3.milestone_id)
        self.assertEqual(task_2.milestone_id, self.milestone_pigs)

        self.task_1.milestone_id = extra_milestone_pigs
        self.assertEqual(task_2.milestone_id, self.milestone_pigs)
        self.assertFalse(
            task_3.milestone_id,
            "The milestone of the parent task should be set to its (grand)child tasks recursively. If a child task milestone should not be updated, it stops the recursion.",
        )

        self.task_1.milestone_id = self.milestone_pigs
        self.assertEqual(task_2.milestone_id, self.milestone_pigs)
        self.assertEqual(self.task_1.milestone_id, self.milestone_pigs)
        self.task_1.milestone_id = extra_milestone_pigs
        self.assertEqual(
            task_2.milestone_id,
            extra_milestone_pigs,
            "If parent and child tasks share the same milestone, the update of the parent's milestone should trigger the update of its child's milestone.",
        )

        self.assertEqual(task_2.milestone_id, extra_milestone_pigs)
        self.assertEqual(self.task_1.milestone_id, extra_milestone_pigs)

        self.task_1.write(
            {
                "project_id": self.project_goats.id,
                "milestone_id": self.milestone_goats.id,
            }
        )
        self.assertTrue(
            task_2.milestone_id == self.task_1.milestone_id == self.milestone_goats,
            "The child milestone should be updated if the parent task's project is changed.",
        )

        self.task_1.project_id = self.project_pigs
        task_2._compute_milestone_id()
        self.task_1.milestone_id = extra_milestone_pigs
        self.assertEqual(task_2.milestone_id, extra_milestone_pigs)
        self.assertEqual(self.task_1.milestone_id, extra_milestone_pigs)

        self.task_1.write(
            {
                "project_id": self.project_pigs.id,
                "milestone_id": self.milestone_pigs.id,
            }
        )
        self.assertEqual(self.task_1.milestone_id, self.milestone_pigs)
        self.assertEqual(
            task_2.milestone_id,
            self.milestone_pigs,
            "The child milestone should be updated as the project of the parent task does not actually change.",
        )

        self.task_1.write(
            {
                "project_id": self.project_pigs.id,
                "milestone_id": extra_milestone_pigs.id,
            }
        )
        self.assertEqual(task_2.milestone_id, extra_milestone_pigs)
        self.assertEqual(self.task_1.milestone_id, extra_milestone_pigs)

        self.task_1.write(
            {
                "project_id": self.project_goats.id,
                "milestone_id": self.milestone_goats.id,
            }
        )
        self.assertEqual(self.task_1.milestone_id, self.milestone_goats)
        self.assertEqual(task_2.project_id, self.project_goats)
        self.assertEqual(
            task_2.milestone_id,
            self.milestone_goats,
            "The child milestone should be updated if the parent task's project is changed only if dislay_on_project is set to False for the subtask.",
        )

        self.task_1.project_id = task_2.project_id = self.project_pigs
        self.task_1.milestone_id = task_2.milestone_id = self.milestone_pigs
        task_2.state = "done"
        self.assertEqual(task_2.milestone_id, self.milestone_pigs)
        self.assertEqual(self.task_1.milestone_id, self.milestone_pigs)

        self.task_1.write(
            {
                "milestone_id": extra_milestone_pigs.id,
            }
        )
        self.assertEqual(self.task_1.milestone_id, extra_milestone_pigs)
        self.assertEqual(
            task_2.milestone_id,
            self.milestone_pigs,
            "The child milestone should not be updated if it is closed.",
        )

    def test_project_milestone_color(self) -> None:
        self.task_1.write(
            {
                "milestone_id": self.milestone_pigs.id,
                "state": "done",
            }
        )
        self.milestone_goats.write(
            {"deadline": fields.Date.today() + relativedelta(days=-1)}
        )

        (self.project_pigs | self.project_goats)._compute_next_milestone_id()

        self.assertTrue(
            self.project_goats.is_milestone_deadline_exceeded,
            "Expected project_goats to have exceeded the milestone deadline.",
        )
        self.assertFalse(
            self.project_pigs.is_milestone_deadline_exceeded,
            "Expected project_pigs to not have exceeded the milestone deadline.",
        )
        self.assertTrue(
            self.project_pigs.can_mark_milestone_as_done,
            "Expected project_pigs to be able to mark the milestone as done.",
        )
        self.assertFalse(
            self.project_goats.can_mark_milestone_as_done,
            "Expected project_goats to not be able to mark the milestone as done.",
        )


@tagged("post_install", "-at_install")
class TestMilestoneCopyAndCompletion(TestProjectCommon):
    def test_multi_project_copy_isolates_milestones(self) -> None:
        project_a = self.env["project.project"].create(
            {
                "name": "Alpha",
                "allow_milestones": True,
            }
        )
        project_b = self.env["project.project"].create(
            {
                "name": "Beta",
                "allow_milestones": True,
            }
        )
        self.env["project.milestone"].create(
            {
                "name": "A-M1",
                "project_id": project_a.id,
            }
        )
        self.env["project.milestone"].create(
            {
                "name": "B-M1",
                "project_id": project_b.id,
            }
        )
        copies = (project_a + project_b).copy()
        self.assertEqual(len(copies[0].milestone_ids), 1)
        self.assertEqual(len(copies[1].milestone_ids), 1)
        self.assertEqual(copies[0].milestone_ids.name, "A-M1")
        self.assertEqual(copies[1].milestone_ids.name, "B-M1")

    def test_empty_milestone_mark_done_consistent(self) -> None:
        self.project_pigs.allow_milestones = True
        saved = self.env["project.milestone"].create(
            {"project_id": self.project_pigs.id, "name": "M"}
        )
        saved.invalidate_recordset(["can_be_marked_as_done"])
        new_rec = self.env["project.milestone"].new(
            {"project_id": self.project_pigs.id, "name": "Mnew"}
        )
        self.assertFalse(saved.can_be_marked_as_done)
        self.assertEqual(
            saved.can_be_marked_as_done,
            new_rec.can_be_marked_as_done,
            "saved and onchange computation must agree for an empty milestone",
        )

    def test_milestone_markable_reacts_to_task_state(self) -> None:
        project = self.env["project.project"].create(
            {"name": "MSReact", "allow_milestones": True}
        )
        milestone = self.env["project.milestone"].create(
            {"name": "M", "project_id": project.id}
        )
        task = self.env["project.task"].create(
            {"name": "mt", "project_id": project.id, "milestone_id": milestone.id}
        )
        self.assertFalse(milestone.can_be_marked_as_done, "open task → not markable")
        task.state = "done"
        self.assertTrue(
            milestone.can_be_marked_as_done,
            "closing the only task must make the milestone markable (depends)",
        )

    def test_late_milestone_flag_reacts_to_a_milestone_switch(self) -> None:
        project = self.env["project.project"].create(
            {"name": "LateSwitch", "allow_milestones": True}
        )
        late, soon = self.env["project.milestone"].create(
            [
                {
                    "name": "LATE",
                    "project_id": project.id,
                    "deadline": fields.Date.today() - relativedelta(days=5),
                },
                {
                    "name": "SOON",
                    "project_id": project.id,
                    "deadline": fields.Date.today() + relativedelta(days=5),
                },
            ]
        )
        task = self.env["project.task"].create(
            {"name": "t", "project_id": project.id, "milestone_id": soon.id}
        )
        self.assertFalse(task.has_late_and_unreached_milestone)
        task.milestone_id = late
        self.assertTrue(task.has_late_and_unreached_milestone)

    def test_late_milestone_flag_reacts_to_a_deadline_move(self) -> None:
        project = self.env["project.project"].create(
            {"name": "LateMove", "allow_milestones": True}
        )
        milestone = self.env["project.milestone"].create(
            {
                "name": "M",
                "project_id": project.id,
                "deadline": fields.Date.today() + relativedelta(days=5),
            }
        )
        task = self.env["project.task"].create(
            {"name": "t", "project_id": project.id, "milestone_id": milestone.id}
        )
        self.assertFalse(task.has_late_and_unreached_milestone)
        milestone.deadline = fields.Date.today() - relativedelta(days=1)
        self.assertTrue(task.has_late_and_unreached_milestone)
