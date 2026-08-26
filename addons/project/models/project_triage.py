from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ProjectTriage(models.Model):
    _name = "project.triage"
    _description = "Personal Task Triage Bucket"
    _inherit = ["mixin.project.pm"]
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
        ondelete="cascade",
        default=lambda self: self.env.user,
    )

    @api.ondelete(at_uninstall=False)
    def _unlink_if_remaining_triage_buckets(self) -> None:
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
