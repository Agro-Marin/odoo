from odoo.tests import tagged

from .test_project_base import TestProjectCommon


class TestTaskFollow(TestProjectCommon):
    def test_follow_on_create(self) -> None:
        self.assertTrue(
            self.user_projectuser.partner_id in self.task_1.message_partner_ids
        )

    def test_follow_on_write(self) -> None:
        self.task_2.user_ids += self.user_projectmanager
        self.assertTrue(
            self.user_projectmanager.partner_id in self.task_2.message_partner_ids
        )


@tagged("post_install", "-at_install")
class TestFollowerPropagation(TestProjectCommon):
    def test_unsubscribe_removes_follower_from_closed_task(self) -> None:
        project = self.env["project.project"].create({"name": "FollowP"})
        closed = self.env["project.task"].create(
            {"name": "closed", "project_id": project.id, "state": "done"}
        )
        self.assertTrue(closed.is_closed)
        closed.message_subscribe(partner_ids=self.partner_2.ids)
        self.assertIn(self.partner_2, closed.message_partner_ids)
        project.message_unsubscribe(partner_ids=self.partner_2.ids)
        self.assertNotIn(
            self.partner_2,
            closed.message_partner_ids,
            "follower must be removed from the closed task as well",
        )

    def test_add_followers_covers_closed_tasks(self) -> None:
        project = self.env["project.project"].create(
            {"name": "AddF", "partner_id": self.partner_1.id}
        )
        closed = self.env["project.task"].create(
            {
                "name": "closed",
                "project_id": project.id,
                "partner_id": self.partner_1.id,
                "state": "done",
            }
        )
        self.assertTrue(closed.is_closed)
        project._add_followers(self.partner_1)
        self.assertIn(
            self.partner_1,
            closed.message_partner_ids,
            "partner must follow their closed task after being added",
        )

    def test_message_subscribe_none_safe_and_no_mutation(self) -> None:
        task = self.env["project.task"].create(
            {"name": "sub", "project_id": self.project_pigs.id}
        )
        task.message_subscribe(subtype_ids=None)
        partners = [self.user_projectmanager.partner_id.id]
        original = list(partners)
        task.message_subscribe(partner_ids=partners)
        self.assertEqual(partners, original, "caller's list must not be mutated")
