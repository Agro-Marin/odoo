from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import HttpCase, new_test_user, tagged

from .test_project_base import TestProjectCommon


@tagged("-at_install", "post_install", "personal_stages")
class TestPersonalStages(TestProjectCommon):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        for user in (cls.user_projectuser, cls.user_projectmanager):
            if not cls.env["project.triage"].search_count([("user_id", "=", user.id)]):
                cls.env["project.triage"].create(
                    cls.env["project.task"]._get_default_triage_vals(user.id)
                )
        cls.user_stages = cls.env["project.triage"].search(
            [("user_id", "=", cls.user_projectuser.id)]
        )
        cls.manager_stages = cls.env["project.triage"].search(
            [("user_id", "=", cls.user_projectmanager.id)]
        )

    def test_personal_stage_base(self) -> None:
        self.task_1.with_user(self.user_projectuser)._compute_personal_triage_id()
        self.assertTrue(
            self.task_1.with_user(self.user_projectuser).triage_id,
            "Project User is assigned to task 1, he should have a personal stage assigned.",
        )

        self.task_1.with_user(self.user_projectmanager)._compute_personal_triage_id()
        self.assertFalse(
            self.env["project.task"]
            .browse(self.task_1.id)
            .with_user(self.user_projectmanager)
            .triage_id,
            "Project Manager is not assigned to task 1, he should not have a personal stage assigned.",
        )

        self.task_1.user_ids += self.user_projectmanager
        self.assertTrue(
            self.task_1.with_user(self.user_projectmanager).triage_id,
            "Project Manager has now been assigned to task 1 and should have a personal stage assigned.",
        )

        self.task_1.with_user(self.user_projectmanager)._compute_personal_triage_id()
        task_1_manager_stage = self.task_1.with_user(self.user_projectmanager).triage_id

        self.task_1.with_user(self.user_projectuser)._compute_personal_triage_id()
        self.task_1.with_user(self.user_projectuser).triage_id = self.user_stages[1]
        self.assertEqual(
            self.task_1.with_user(self.user_projectuser).triage_id,
            self.user_stages[1],
            "Assigning another personal stage to the task should have changed it for user 1.",
        )

        self.task_1.with_user(self.user_projectmanager)._compute_personal_triage_id()
        self.assertEqual(
            self.task_1.with_user(self.user_projectmanager).triage_id,
            task_1_manager_stage,
            "Modifying the personal stage of Project User should not have affected the personal stage of Project Manager.",
        )

        self.task_2.with_user(self.user_projectmanager).triage_id = self.manager_stages[
            1
        ]
        self.assertEqual(
            self.task_1.with_user(self.user_projectmanager).triage_id,
            task_1_manager_stage,
            "Modifying the personal stage on task 2 for Project Manager should not have affected the stage on task 1.",
        )

    def test_personal_stage_search(self) -> None:
        self.task_2.user_ids += self.user_projectuser
        self.task_1.with_user(self.user_projectuser).triage_id = self.user_stages[0]
        self.task_2.with_user(self.user_projectuser).triage_id = self.user_stages[1]
        tasks = (
            self.env["project.task"]
            .with_user(self.user_projectuser)
            .search([("triage_id", "=", self.user_stages[0].id)])
        )
        self.assertTrue(tasks, "The search result should not be empty.")
        for task in tasks:
            self.assertEqual(
                task.triage_id,
                self.user_stages[0],
                "The search should only have returned task that are in the inbox personal stage.",
            )

    def test_personal_stage_read_group(self) -> None:
        (
            self.env["project.task"]
            .sudo()
            .search(
                [
                    (
                        "user_ids",
                        "in",
                        (self.task_1.user_ids + self.user_projectmanager).ids,
                    )
                ]
            )
            - self.task_1
        ).unlink()

        self.task_1.user_ids += self.user_projectmanager
        self.task_1.with_user(self.user_projectmanager).triage_id = self.manager_stages[
            1
        ]
        self.env.flush_all()
        read_group_user = (
            self.env["project.task"]
            .with_context(read_group_expand=True)
            .with_user(self.user_projectuser)
            .formatted_read_group(
                [("user_ids", "=", self.user_projectuser.id)],
                aggregates=["sequence:avg", "__count"],
                groupby=["triage_ids"],
            )
        )
        self.assertEqual(
            len(self.user_stages),
            len(read_group_user),
            "read_group should return %d groups" % len(self.user_stages),
        )
        total = 0
        for group in read_group_user:
            total += group["__count"]
        self.assertEqual(
            1,
            total,
            "read_group should not have returned more tasks than the user is assigned to.",
        )
        read_group_manager = (
            self.env["project.task"]
            .with_context(read_group_expand=True)
            .with_user(self.user_projectmanager)
            .formatted_read_group(
                [("user_ids", "=", self.user_projectmanager.id)],
                aggregates=["sequence:avg", "__count"],
                groupby=["triage_ids"],
            )
        )
        self.assertEqual(
            len(self.manager_stages),
            len(read_group_manager),
            "read_group should return %d groups" % len(self.user_stages),
        )
        total = 0
        total_stage_0 = 0
        total_stage_1 = 0
        for group in read_group_manager:
            total += group["__count"]
            if group["triage_ids"][0] == self.manager_stages[0].id:
                total_stage_0 += 1
            elif group["triage_ids"][0] == self.manager_stages[1].id:
                total_stage_1 += 1
        self.assertEqual(
            1,
            total,
            "read_group should not have returned more tasks than the user is assigned to.",
        )
        self.assertEqual(1, total_stage_0)
        self.assertEqual(1, total_stage_1)

    def test_delete_personal_stage(self) -> None:
        user_1, user_2, user_3 = self.env["res.users"].create(
            [
                {
                    "login": "user_1_stages",
                    "name": "User 1 with personal stages",
                },
                {
                    "login": "user_2_stages",
                    "name": "User 2 with personal stages",
                },
                {
                    "login": "user_3_stages",
                    "name": "User 3 with personal stages",
                },
            ]
        )

        self.env["project.task"].sudo().search(
            [("user_ids", "in", (user_1 + user_2 + user_3).ids)]
        ).unlink()
        user_ids = (user_1 + user_2 + user_3).ids
        self.env.cr.execute(
            "DELETE FROM project_task_triage WHERE triage_id IN "
            "(SELECT id FROM project_triage WHERE user_id = ANY(%s))",
            [user_ids],
        )
        self.env.cr.execute(
            "DELETE FROM project_triage WHERE user_id = ANY(%s)",
            [user_ids],
        )
        self.env.invalidate_all()

        self.assertEqual(
            self.env["project.triage"].search_count([("user_id", "=", user_1.id)]),
            0,
        )
        self.assertEqual(
            self.env["project.triage"].search_count([("user_id", "=", user_2.id)]),
            0,
        )
        self.assertEqual(
            self.env["project.task"].search_count([("user_ids", "in", user_1.ids)]),
            0,
        )
        self.assertEqual(
            self.env["project.task"].search_count([("user_ids", "in", user_2.ids)]),
            0,
        )

        user_1_stages = self.env["project.triage"].create(
            [
                {
                    "user_id": user_1.id,
                    "name": f"User 1 - Stage {i}",
                    "sequence": 10 * i,
                }
                for i in range(1, 6)
            ]
        )
        user_2_stages = self.env["project.triage"].create(
            [
                {
                    "user_id": user_2.id,
                    "name": f"User 2 - Stage {i}",
                    "sequence": 10 * i,
                }
                for i in range(1, 4)
            ]
        )

        private_tasks = self.env["project.task"].create(
            [
                {
                    "user_ids": [
                        Command.link(user_1.id),
                        Command.link(user_2.id),
                    ],
                    "name": "Task 1",
                    "project_id": False,
                },
                {
                    "user_ids": [
                        Command.link(user_1.id),
                        Command.link(user_2.id),
                    ],
                    "name": "Task 2",
                    "project_id": False,
                },
                {
                    "user_ids": [Command.link(user_1.id)],
                    "name": "Task 3",
                    "project_id": False,
                },
                {
                    "user_ids": [Command.link(user_1.id)],
                    "name": "Task 4",
                    "project_id": False,
                },
            ]
        )

        private_tasks[0].with_user(user_1.id).triage_id = user_1_stages[2].id
        private_tasks[1].with_user(user_1.id).triage_id = user_1_stages[3].id
        private_tasks[2].with_user(user_1.id).triage_id = user_1_stages[4].id
        private_tasks[3].with_user(user_1.id).triage_id = user_1_stages[4].id

        private_tasks[0].with_user(user_2.id).triage_id = user_2_stages[0].id
        private_tasks[1].with_user(user_2.id).triage_id = user_2_stages[1].id

        self.assertEqual(
            self.env["project.triage"]
            .with_user(user_1.id)
            .search_count([("user_id", "=", user_1.id)]),
            5,
        )
        self.assertEqual(
            self.env["project.task"]
            .with_user(user_1.id)
            .search_count([("user_ids", "in", user_1.ids)]),
            4,
        )
        private_tasks.invalidate_recordset(["triage_id"])
        self.assertEqual(
            private_tasks[0].with_user(user_1.id).triage_id.id,
            user_1_stages[2].id,
        )
        self.assertEqual(
            private_tasks[1].with_user(user_1.id).triage_id.id,
            user_1_stages[3].id,
        )
        self.assertEqual(
            private_tasks[2].with_user(user_1.id).triage_id.id,
            user_1_stages[4].id,
        )
        self.assertEqual(
            private_tasks[3].with_user(user_1.id).triage_id.id,
            user_1_stages[4].id,
        )
        self.assertEqual(
            self.env["project.triage"]
            .with_user(user_2.id)
            .search_count([("user_id", "=", user_2.id)]),
            3,
        )
        self.assertEqual(
            self.env["project.task"]
            .with_user(user_2.id)
            .search_count([("user_ids", "in", user_2.ids)]),
            2,
        )
        private_tasks.invalidate_recordset(["triage_id"])
        self.assertEqual(
            private_tasks[0].with_user(user_2.id).triage_id.id,
            user_2_stages[0].id,
        )
        self.assertEqual(
            private_tasks[1].with_user(user_2.id).triage_id.id,
            user_2_stages[1].id,
        )

        user_2_stages[2].with_user(user_2.id).unlink()
        self.assertEqual(
            self.env["project.triage"]
            .with_user(user_2.id)
            .search_count([("user_id", "=", user_2.id)]),
            2,
            "A user should be able to unlink its own (empty) personal stage.",
        )

        private_tasks.invalidate_recordset(["triage_id"])
        user_1_stages[2].with_user(user_1.id).unlink()
        self.assertEqual(
            self.env["project.triage"]
            .with_user(user_1.id)
            .search_count([("user_id", "=", user_1.id)]),
            4,
            "A user should be able to unlink its own personal stage.",
        )
        self.assertEqual(
            self.env["project.task"]
            .with_user(user_1.id)
            .search_count([("user_ids", "in", user_1.ids)]),
            4,
            "Tasks in a removed personal stage should not be unlinked.",
        )
        self.assertEqual(
            private_tasks[0].with_user(user_1.id).triage_id.id,
            user_1_stages[1].id,
            "Tasks in a removed personal stage should be moved to the stage following it sequence-wise",
        )

        user_1_stages.filtered(
            lambda s: s.id in [user_1_stages[1].id, user_1_stages[3].id]
        ).with_user(user_1.id).unlink()
        self.assertEqual(
            self.env["project.triage"]
            .with_user(user_1.id)
            .search_count([("user_id", "=", user_1.id)]),
            2,
            "A user should be able to unlink its own personal stage in batch.",
        )
        self.assertEqual(
            self.env["project.task"]
            .with_user(user_1.id)
            .search_count([("user_ids", "in", user_1.ids)]),
            4,
            "Tasks in personal stages removed in batch should not be unlinked.",
        )
        for i in range(2):
            self.assertEqual(
                private_tasks[i].with_user(user_1.id).triage_id.id,
                user_1_stages[0].id,
                "Tasks in a personal stage removed in batch should be moved to the stage following it sequence-wise",
            )

        (user_1_stages[0] | user_2_stages[1]).sudo().unlink()
        self.assertEqual(
            self.env["project.triage"]
            .with_user(user_1.id)
            .search_count([("user_id", "=", user_1.id)]),
            1,
            "Superuser should be able to delete personal stages in batch.",
        )
        self.assertEqual(
            self.env["project.triage"]
            .with_user(user_2.id)
            .search_count([("user_id", "=", user_2.id)]),
            1,
            "Superuser should be able to delete personal stages in batch.",
        )
        self.assertEqual(
            self.env["project.task"]
            .with_user(user_1.id)
            .search_count([("user_ids", "in", user_1.ids)]),
            4,
            "Tasks in personal stages removed in batch by superuser should not be unlinked.",
        )
        for private_task in private_tasks:
            self.assertEqual(
                private_task.with_user(user_1.id).triage_id.id,
                user_1_stages[4].id,
                "Tasks in a personal stage removed in batch should be moved to a stage with a higher sequence if no stage with lower sequence have been found",
            )
        private_tasks.invalidate_recordset(["triage_id"])
        self.assertEqual(
            private_tasks[0].with_user(user_2.id).triage_id.id,
            user_2_stages[0].id,
            "Tasks in a personal stage removed in batch by superuser should be moved to the stage following it sequence-wise",
        )
        self.assertEqual(
            private_tasks[1].with_user(user_2.id).triage_id.id,
            user_2_stages[0].id,
            "Tasks in a personal stage removed in batch by superuser should be moved to the stage following it sequence-wise",
        )

        with self.assertRaises(
            UserError,
            msg="Deleting the last personal stage of a user should raise an error",
        ):
            user_2_stages[0].with_user(user_2.id).unlink()
        self.assertEqual(
            self.env["project.triage"]
            .with_user(user_2.id)
            .search_count([("user_id", "=", user_2.id)]),
            1,
            "Last personal stage of a user should not be deleted by unlink method",
        )
        private_tasks.invalidate_recordset(["triage_id"])
        self.assertEqual(
            private_tasks[0].with_user(user_2.id).triage_id.id,
            user_2_stages[0].id,
            "Last personal stage of a user should not be deleted by unlink method",
        )
        self.assertEqual(
            private_tasks[1].with_user(user_2.id).triage_id.id,
            user_2_stages[0].id,
            "Last personal stage of a user should not be deleted by unlink method",
        )

        empty_stage_user_3 = self.env["project.triage"].create(
            {
                "user_id": user_3.id,
                "name": "User 3 - Empty stage",
                "sequence": 10,
            }
        )

        with self.assertRaises(
            UserError,
            msg="Deleting the last personal stage of a user should raise an error, even if the stage is empty",
        ):
            empty_stage_user_3.with_user(user_3.id).unlink()

        empty_triages = self.env["project.triage"].create(
            [
                {
                    "user_id": user_1.id,
                    "name": "User 1 - Empty stage",
                    "sequence": 10,
                },
                {
                    "user_id": user_2.id,
                    "name": "User 2 - Empty stage",
                    "sequence": 10,
                },
            ]
        )
        empty_step = self.env["project.workflow.step"].create(
            {
                "project_ids": self.project_pigs,
                "name": "Empty stage in project Pigs",
                "sequence": 10,
            }
        )
        empty_triages.sudo().unlink()
        empty_step.sudo().unlink()
        self.assertFalse(
            self.env["project.triage"].search_count([("id", "in", empty_triages.ids)]),
            "Personal triage stages should be deletable in batch",
        )
        self.assertFalse(
            self.env["project.workflow.step"].search_count(
                [("id", "=", empty_step.id)]
            ),
            "Workflow steps should also be deletable",
        )

    def test_new_personal_stages_created_for_new_users(self) -> None:
        ProjectTaskType = self.env["project.triage"]

        internal_user = new_test_user(
            self.env,
            login="internal_user",
            groups="base.group_user",
        )
        self.assertEqual(
            7,
            ProjectTaskType.search_count([("user_id", "=", internal_user.id)]),
            "Personal stages seems to have a wrong count",
        )

        portal_user = new_test_user(
            self.env,
            login="portal_user",
            groups="base.group_portal",
        )
        self.assertEqual(
            0,
            ProjectTaskType.search_count([("user_id", "=", portal_user.id)]),
            "Portal users should never have personal stages when created",
        )

        public_user = new_test_user(
            self.env,
            login="public_user",
            groups="base.group_public",
        )
        self.assertEqual(
            0,
            ProjectTaskType.search_count([("user_id", "=", public_user.id)]),
            "Public users should never have personal stages when created",
        )


@tagged("-at_install", "post_install")
class TestPersonalStageTour(HttpCase, TestProjectCommon):
    def test_personal_stage_tour(self) -> None:
        self.env["project.workflow.step"].create(
            {
                "name": "Doing",
                "project_ids": [Command.link(self.project_pigs.id)],
            }
        )
        self.start_tour("/odoo", "personal_stage_tour", login="armandel")
