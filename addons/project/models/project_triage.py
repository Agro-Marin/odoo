"""Personal task triage buckets (PMI terminology alignment).

Triage buckets are private to each user — they express *when* the user plans
to work on tasks, not *where* in the project workflow those tasks are.

Default buckets per user: Inbox, Today, This Week, This Month, Later,
Done, Cancelled.
"""

from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ProjectTriage(models.Model):
    """A personal time-horizon bucket for tasks assigned to a user.

    Buckets are never linked to projects (that is the job of workflow steps).
    Each user maintains their own independent ordered list of triage buckets.
    """

    _name = "project.triage"
    _description = "Personal Task Triage Bucket"
    _inherit = ["project.pm.mixin"]
    _order = "sequence, id"

    active = fields.Boolean("Active", default=True, export_string_translation=False)
    name = fields.Char(string="Name", required=True, translate=True)
    sequence = fields.Integer(default=1)
    color = fields.Integer(string="Color Index", default=0)
    fold = fields.Boolean(string="Folded")
    user_id = fields.Many2one(
        "res.users",
        string="Triage Owner",
        required=True,
        index=True,
        # Triage buckets are personal: creating one without an explicit owner
        # (e.g. the kanban column quick-create in My Tasks, which only sends a
        # name) must assign the current user, not crash on the NOT NULL.
        default=lambda self: self.env.user,
    )

    @api.ondelete(at_uninstall=False)
    def _unlink_if_remaining_triage_buckets(self) -> None:
        """Ensure each user always has at least one triage bucket after deletion.

        Tasks in the deleted buckets are moved to the nearest remaining bucket
        by sequence order (lower sequence preferred).
        """
        remaining_all = self.env["project.triage"]._read_group(
            [
                ("user_id", "in", self.user_id.ids),
                ("id", "not in", self.ids),
            ],
            groupby=["user_id", "sequence", "id"],
            order="user_id,sequence DESC",
        )
        remaining_by_user: dict = defaultdict(list)
        for user, sequence, bucket in remaining_all:
            remaining_by_user[user].append({"id": bucket.id, "seq": sequence})

        triage_to_update = self.env["project.task.triage"]._read_group(
            [("triage_id", "in", self.ids)],
            ["triage_id"],
            ["id:recordset"],
        )
        for user in self.user_id:
            if not user.active or user.share:
                continue
            user_buckets_to_unlink = self.filtered(lambda b, u=user: b.user_id == u)
            user_remaining = remaining_by_user[user]
            if not user_remaining:
                raise UserError(
                    _(
                        "Each user must have at least one triage bucket. "
                        "Create a replacement bucket before deleting the selected ones."
                    )
                )
            user_buckets_to_unlink._prepare_triage_deletion(
                user_remaining, triage_to_update
            )

    def _prepare_triage_deletion(
        self, remaining_buckets: list[dict], triage_to_update
    ) -> None:
        """Reassign task triage entries when buckets are deleted.

        Tasks are moved to the nearest remaining bucket by sequence order,
        preferring the next-lower sequence (i.e. the bucket just before the
        deleted one, falling back to the next-higher).

        :param remaining_buckets: Sorted list of dicts ``{"id": int, "seq": int}``
            representing the buckets that will survive, in descending sequence
            order. Must not be empty.
        :param triage_to_update: ``_read_group`` result of ``project.task.triage``
            records grouped by ``triage_id`` for the buckets being deleted.
        """
        buckets_to_delete = sorted(
            [{"id": b.id, "seq": b.sequence} for b in self],
            key=lambda b: b["seq"],
        )
        replacement_id = remaining_buckets.pop()["id"]
        next_replacement = remaining_buckets and remaining_buckets.pop()

        triage_by_bucket = {
            bucket.id: task_triages for bucket, task_triages in triage_to_update
        }
        for bucket in buckets_to_delete:
            while next_replacement and next_replacement["seq"] < bucket["seq"]:
                replacement_id = next_replacement["id"]
                next_replacement = remaining_buckets and remaining_buckets.pop()
            if bucket["id"] in triage_by_bucket:
                triage_by_bucket[bucket["id"]].triage_id = replacement_id
