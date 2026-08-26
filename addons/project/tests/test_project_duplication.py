from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestProjectDuplication(TestProjectCommon):
    def test_copy_data_preserves_defaults_across_batch(self) -> None:
        project = self.project_pigs
        parent = self.env["project.task"].create(
            {
                "name": "Parent with child",
                "project_id": project.id,
            }
        )
        self.env["project.task"].create(
            {
                "name": "Child",
                "project_id": project.id,
                "parent_id": parent.id,
            }
        )
        sibling = self.env["project.task"].create(
            {
                "name": "Sibling",
                "project_id": project.id,
            }
        )
        self.assertGreater(sibling.id, parent.id, "parent must be processed first")
        copies = (parent + sibling).copy({"name": "RenamedCopy"})
        self.assertEqual(
            copies[1].name,
            "RenamedCopy",
            "The sibling copy must honour the passed default name, not fall back "
            "to '<name> (copy)' because default was narrowed by the parent's "
            "child-copy branch",
        )

    def test_mass_rename_projects_with_analytic_account(self) -> None:
        p1 = self.env["project.project"].create({"name": "P1"})
        p2 = self.env["project.project"].create({"name": "P2"})
        p1._create_analytic_account()
        p2._create_analytic_account()
        self.assertTrue(p1.account_id and p2.account_id)
        (p1 + p2).write({"name": "Renamed"})
        self.assertEqual(p1.name, "Renamed")
        self.assertEqual(p2.name, "Renamed")
        self.assertEqual(p1.account_id.name, "Renamed")

    def test_unlink_keeps_shared_analytic_account(self) -> None:
        plan = self.env["account.analytic.plan"].search([], limit=1)
        account = self.env["account.analytic.account"].create(
            {"name": "Shared", "plan_id": plan.id}
        )
        p1 = self.env["project.project"].create(
            {"name": "S1", "account_id": account.id}
        )
        p2 = self.env["project.project"].create(
            {"name": "S2", "account_id": account.id}
        )
        p1.unlink()
        self.assertTrue(
            account.exists(), "shared account must survive while a sibling uses it"
        )
        self.assertEqual(p2.account_id, account, "sibling must keep its account")
        p2.unlink()
        self.assertFalse(
            account.exists(), "account must be removed once no project uses it"
        )

    def test_task_count_archived_project_in_mixed_recordset(self) -> None:
        active = self.env["project.project"].create({"name": "ActiveP"})
        archived = self.env["project.project"].create({"name": "ArchP"})
        self.env["project.task"].create({"name": "a", "project_id": active.id})
        self.env["project.task"].create(
            [
                {"name": "b1", "project_id": archived.id},
                {"name": "b2", "project_id": archived.id},
            ]
        )
        archived.active = False
        batch = active | archived
        batch.invalidate_recordset(["task_count"])
        self.assertEqual(active.task_count, 1)
        self.assertEqual(
            archived.task_count, 2, "archived project must still count its tasks"
        )
