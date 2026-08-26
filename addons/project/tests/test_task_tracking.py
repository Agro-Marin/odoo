from odoo.tests import tagged

from odoo.addons.project.tests.test_project_base import TestProjectCommon


@tagged("-at_install", "post_install")
class TestTaskTracking(TestProjectCommon):
    def flush_tracking(self) -> None:
        self.env.flush_all()
        self.cr.precommit.run()

    def test_many2many_tracking(self) -> None:
        self.cr.precommit.clear()
        self.task_1.user_ids += self.user_projectmanager
        self.flush_tracking()
        self.assertEqual(
            len(self.task_1.message_ids),
            1,
            "Assigning a new user should log a message.",
        )
        self.task_1.user_ids += self.user_projectmanager
        self.flush_tracking()
        self.assertEqual(
            len(self.task_1.message_ids),
            1,
            "Assigning an already assigned user should not log a message.",
        )
        self.task_1.user_ids = False
        self.flush_tracking()
        self.assertEqual(
            len(self.task_1.message_ids),
            2,
            "Removing both assignees should only log one message.",
        )

    def test_many2many_tracking_context(self) -> None:
        self.task_1.with_context(
            default_parent_id=-1
        ).user_ids += self.user_projectmanager
