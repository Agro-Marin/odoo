from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestStatusChangeStamp(TestProjectCommon):
    def _task(self, **vals):
        return self.env["project.task"].create(
            {"name": "T", "project_id": self.project_pigs.id, **vals}
        )

    def _age(self, task, days=30):
        old = fields.Datetime.now() - timedelta(days=days)
        self.env.cr.execute(
            "UPDATE project_task SET date_last_status_change=%s WHERE id=%s",
            (old, task.id),
        )
        task.invalidate_recordset(["date_last_status_change"])
        return old

    def test_restating_the_current_state_does_not_stamp(self):
        task = self._task()
        old = self._age(task)
        task.write({"state": task.state})
        self.assertEqual(task.date_last_status_change, old)

    def test_restating_the_current_step_does_not_stamp(self):
        task = self._task()
        old = self._age(task)
        task.write({"step_id": task.step_id.id})
        self.assertEqual(task.date_last_status_change, old)

    def test_an_unrelated_write_does_not_stamp(self):
        task = self._task()
        old = self._age(task)
        task.write({"name": "renamed"})
        self.assertEqual(task.date_last_status_change, old)

    def test_a_real_state_change_stamps(self):
        task = self._task()
        old = self._age(task)
        task.write({"state": "done"})
        self.assertGreater(task.date_last_status_change, old)

    def test_a_real_step_change_stamps(self):
        task = self._task()
        other_step = self.env["project.workflow.step"].create(
            {"name": "Other", "project_ids": [(4, self.project_pigs.id)]}
        )
        old = self._age(task)
        task.write({"step_id": other_step.id})
        self.assertGreater(task.date_last_status_change, old)

    def test_a_mixed_batch_stamps_only_what_moved(self):
        moving = self._task()
        staying = self._task(state="done")
        old_moving = self._age(moving)
        old_staying = self._age(staying)
        (moving | staying).write({"state": "done"})
        self.assertGreater(moving.date_last_status_change, old_moving)
        self.assertEqual(staying.date_last_status_change, old_staying)

    def test_a_noop_write_does_not_un_rot_a_task(self):
        task = self._task()
        task.step_id.write({"rotting_threshold_days": 5})
        self._age(task, days=60)
        task.invalidate_recordset()
        self.assertTrue(task.is_rotting, "precondition: the task is rotting")
        task.write({"state": task.state})
        task.invalidate_recordset()
        self.assertTrue(task.is_rotting)
