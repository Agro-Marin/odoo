"""Which task fields a portal user may read and write."""

from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestPortalWritableFields(TestProjectCommon):
    """The portal allowlist must not grant writes the ORM will honour."""

    def test_status_timestamp_is_not_portal_writable(self) -> None:
        """``readonly=True`` is a client hint, not an ORM guard: listing this
        field let a portal collaborator stamp any value onto the timestamp that
        drives rotting, stage-duration tracking and the burndown chart."""
        Task = self.env["project.task"]
        self.assertNotIn("date_last_status_change", Task.TASK_PORTAL_WRITABLE_FIELDS)
        self.assertIn("date_last_status_change", Task.TASK_PORTAL_READABLE_FIELDS)

    def test_is_closed_is_not_portal_writable(self) -> None:
        """A non-stored compute with no inverse: the write was accepted and
        silently did nothing."""
        Task = self.env["project.task"]
        self.assertNotIn("is_closed", Task.TASK_PORTAL_WRITABLE_FIELDS)

    def test_every_portal_writable_field_can_actually_be_written(self) -> None:
        Task = self.env["project.task"]
        for fname in Task.TASK_PORTAL_WRITABLE_FIELDS:
            field = Task._fields[fname]
            with self.subTest(field=fname):
                self.assertFalse(
                    field.readonly and not field.inverse,
                    f"{fname} is readonly with no inverse",
                )
                self.assertFalse(
                    field.compute and not field.store and not field.inverse,
                    f"{fname} is a non-stored compute with no inverse",
                )
