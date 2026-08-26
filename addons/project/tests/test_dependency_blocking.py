from odoo import Command
from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestPredecessorBlockAtCreate(TestProjectCommon):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.project_pigs.allow_dependencies = True

    def _predecessor(self):
        return self.env["project.task"].create(
            {"name": "Predecessor", "project_id": self.project_pigs.id}
        )

    def test_blocked_when_predecessor_given_at_create(self) -> None:
        predecessor = self._predecessor()
        task = self.env["project.task"].create(
            {
                "name": "Successor",
                "project_id": self.project_pigs.id,
                "predecessor_ids": [Command.link(predecessor.id)],
            }
        )
        self.assertTrue(task.is_blocked_by_predecessors())
        self.assertEqual(task.state, "blocked")

    def test_blocked_with_command_set(self) -> None:
        predecessor = self._predecessor()
        task = self.env["project.task"].create(
            {
                "name": "Successor",
                "project_id": self.project_pigs.id,
                "predecessor_ids": [Command.set([predecessor.id])],
            }
        )
        self.assertEqual(task.state, "blocked")

    def test_blocked_through_the_import_path(self) -> None:
        predecessor = self._predecessor()
        self.env["ir.model.data"].create(
            [
                {
                    "module": "__test_batch_e__",
                    "name": "project",
                    "model": "project.project",
                    "res_id": self.project_pigs.id,
                },
                {
                    "module": "__test_batch_e__",
                    "name": "predecessor",
                    "model": "project.task",
                    "res_id": predecessor.id,
                },
            ]
        )
        result = self.env["project.task"].load(
            ["name", "project_id/id", "predecessor_ids/id"],
            [
                [
                    "Imported successor",
                    "__test_batch_e__.project",
                    "__test_batch_e__.predecessor",
                ]
            ],
        )
        self.assertFalse(
            [m for m in result["messages"] if m.get("type") == "error"],
            result["messages"],
        )
        imported = self.env["project.task"].browse(result["ids"])
        self.assertEqual(imported.state, "blocked")

    def test_closed_task_is_not_reopened_into_blocked(self) -> None:
        predecessor = self._predecessor()
        task = self.env["project.task"].create(
            {
                "name": "Already done",
                "project_id": self.project_pigs.id,
                "state": "done",
                "predecessor_ids": [Command.link(predecessor.id)],
            }
        )
        self.assertEqual(task.state, "done")

    def test_not_blocked_when_the_feature_is_off(self) -> None:
        self.project_pigs.allow_dependencies = False
        predecessor = self._predecessor()
        task = self.env["project.task"].create(
            {
                "name": "Successor",
                "project_id": self.project_pigs.id,
                "predecessor_ids": [Command.link(predecessor.id)],
            }
        )
        self.assertNotEqual(task.state, "blocked")

    def test_closed_predecessor_count_reacts_to_state_change(self) -> None:
        self.project_goats.allow_dependencies = True
        (self.task_1 + self.task_2).write({"project_id": self.project_goats.id})
        self.task_1.predecessor_ids = self.task_2
        self.assertEqual(self.task_1.closed_predecessor_count, 0)
        self.task_2.state = "done"
        self.assertEqual(
            self.task_1.closed_predecessor_count,
            1,
            "closing a predecessor must update closed_predecessor_count",
        )

    def test_successor_count_on_new_record(self) -> None:
        project = self.env["project.project"].create(
            {"name": "NewSucc", "allow_dependencies": True}
        )
        existing = self.env["project.task"].create(
            {"name": "existing", "project_id": project.id}
        )
        new_task = self.env["project.task"].new(
            {
                "name": "new",
                "project_id": project.id,
                "successor_ids": [(4, existing.id)],
            }
        )
        self.assertEqual(new_task.successor_count, 1)

    def test_report_successor_ids_is_queryable(self) -> None:
        project = self.env["project.project"].create(
            {"name": "RepProj", "allow_dependencies": True}
        )
        a = self.env["project.task"].create({"name": "A", "project_id": project.id})
        b = self.env["project.task"].create({"name": "B", "project_id": project.id})
        b.write({"predecessor_ids": [(4, a.id)]})
        self.env.flush_all()
        report = self.env["report.project.task.user"]
        rows = report.search([("task_id", "=", a.id)])
        self.assertIn(b, rows.successor_ids)

    def test_typed_dependency_write_resyncs_m2m(self) -> None:
        self.project_pigs.allow_dependencies = True
        a, b, c = self.env["project.task"].create(
            [{"name": n, "project_id": self.project_pigs.id} for n in ("A", "B", "C")]
        )
        dep = self.env["project.task.dependency"].create(
            {"task_id": b.id, "depends_on_id": a.id, "dependency_type": "fs"}
        )
        b.invalidate_recordset(["predecessor_ids"])
        self.assertEqual(b.predecessor_ids, a)
        dep.depends_on_id = c.id
        b.invalidate_recordset(["predecessor_ids"])
        self.assertEqual(
            b.predecessor_ids,
            c,
            "editing the dependency must move the M2M link from A to C",
        )

    def test_batch_typed_dependencies_sync_all(self) -> None:
        project = self.env["project.project"].create(
            {"name": "BatchDep", "allow_dependencies": True}
        )
        a, b, c, d = self.env["project.task"].create(
            [{"name": n, "project_id": project.id} for n in ("A", "B", "C", "D")]
        )
        self.env["project.task.dependency"].create(
            [
                {"task_id": b.id, "depends_on_id": a.id},
                {"task_id": c.id, "depends_on_id": a.id},
                {"task_id": d.id, "depends_on_id": b.id},
            ]
        )
        (b + c + d).invalidate_recordset(["predecessor_ids"])
        self.assertEqual(b.predecessor_ids, a)
        self.assertEqual(c.predecessor_ids, a)
        self.assertEqual(d.predecessor_ids, b)

    def test_project_copy_remaps_subtask_dependencies(self) -> None:
        project = self.env["project.project"].create(
            {"name": "DepCopy", "allow_dependencies": True}
        )
        parent = self.env["project.task"].create(
            {"name": "P", "project_id": project.id}
        )
        a = self.env["project.task"].create(
            {"name": "A", "project_id": project.id, "parent_id": parent.id}
        )
        b = self.env["project.task"].create(
            {"name": "B", "project_id": project.id, "parent_id": parent.id}
        )
        a.write({"predecessor_ids": [(4, b.id)]})
        copy = project.copy()
        copied_a = copy.task_ids.filtered(lambda t: t.name == "A")
        copied_b = copy.task_ids.filtered(lambda t: t.name == "B")
        self.assertTrue(copied_a and copied_b, "both subtasks must be copied")
        self.assertEqual(
            copied_a.predecessor_ids,
            copied_b,
            "copied A must depend on the COPIED B, not the original",
        )
        self.assertNotIn(
            b, copied_a.predecessor_ids, "must not reference the original task"
        )
