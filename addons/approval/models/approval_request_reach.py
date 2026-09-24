from odoo import api, fields, models
from odoo.fields import Domain


class ApprovalRequest(models.Model):
    _inherit = "approval.request"

    pending_user_ids = fields.Many2many(
        comodel_name="res.users",
        relation="approval_request_pending_user_rel",
        column1="request_id",
        column2="user_id",
        string="Deciding Now",
        compute="_compute_pending_user_ids",
        store=True,
        help="Who holds an undecided row of this pending request, or stands in for "
        "someone who does. An approver reads the document they are asked about "
        "through it, and stops reading it once they have decided.",
    )

    @api.depends(
        "state",
        "approver_ids.state",
        "approver_ids.user_id",
        "approver_ids.delegate_id",
    )
    def _compute_pending_user_ids(self) -> None:
        for request in self:
            if request.state != "pending":
                request.pending_user_ids = False
                continue
            rows = request.approver_ids.filtered(
                lambda row: row.state in ("pending", "waiting")
            )
            request.pending_user_ids = rows.user_id | rows.delegate_id


DECIDER_SYNC = "approval.decider_sync"
DECIDER_CAUSES = ("approval_step", "approval_delegation", "migration")


def _sync_decider_grants(env, users) -> None:
    """Keep the Decider group on whoever a step names or an approver delegates to,
    and off whoever neither names any more.

    Done when the transaction flushes, not in the middle of the write that names
    them: a membership change clears the access caches and flushes, which would
    check a half-built step against its own constraints.
    """
    if not users:
        return
    pending = env.cr.precommit.data.setdefault(DECIDER_SYNC, set())
    if not pending:
        env.cr.precommit.add(lambda: _flush_decider_sync(env))
    pending.update(users.ids)


def _flush_decider_sync(env) -> None:
    user_ids = sorted(env.cr.precommit.data.pop(DECIDER_SYNC, set()))
    env["res.users.grant"].sudo()._sync_decider_grants(
        env["res.users"].sudo().browse(user_ids).exists()
    )


class ResUsersGrant(models.Model):
    _inherit = "res.users.grant"

    cause = fields.Selection(
        selection_add=[
            ("approval_step", "Approval step member"),
            ("approval_delegation", "Approval delegation"),
        ],
        ondelete={"approval_step": "cascade", "approval_delegation": "cascade"},
    )

    @api.model
    def _sync_decider_grants(self, users) -> None:
        group = self.env.ref("approval.group_approval_decider")
        members = (
            self.env["approval.category.step.member"]
            .sudo()
            .search([("user_id", "in", users.ids), ("step_id.active", "=", True)])
        )
        delegations = (
            self.env["approval.approver"]
            .sudo()
            .search(
                [
                    ("delegate_id", "in", users.ids),
                    ("state", "in", ("pending", "waiting")),
                    ("request_id.state", "=", "pending"),
                ]
            )
        )
        ours = self.sudo().search(
            self._live_domain()
            & Domain("user_id", "in", users.ids)
            & Domain("group_id", "=", group.id)
            & Domain("cause", "in", DECIDER_CAUSES)
        )
        step_of = {member.user_id: member.step_id for member in reversed(members)}
        delegation_of = {row.delegate_id: row for row in reversed(delegations)}
        held_by = ours.grouped("user_id")
        for user in users.filtered(lambda user: not user.share):
            if cause_ref := step_of.get(user) or delegation_of.get(user):
                self._grant(
                    user,
                    group,
                    cause="approval_step"
                    if cause_ref._name == "approval.category.step"
                    else "approval_delegation",
                    cause_ref=cause_ref,
                )
            elif held := held_by.get(user):
                held.action_revoke(
                    self.env._("No longer in an approval step or delegation.")
                )

    @api.model
    def _cron_sync_decider_grants(self) -> None:
        group = self.env.ref("approval.group_approval_decider")
        holders = (
            self.sudo()
            .search(
                self._live_domain()
                & Domain("group_id", "=", group.id)
                & Domain("cause", "in", DECIDER_CAUSES)
            )
            .user_id
        )
        self._sync_decider_grants(holders)


class ApprovalApprover(models.Model):
    _inherit = "approval.approver"

    _delegate_idx = models.Index("(delegate_id) WHERE delegate_id IS NOT NULL")

    def write(self, vals):
        before = self.delegate_id if "delegate_id" in vals else self.env["res.users"]
        result = super().write(vals)
        if "delegate_id" in vals:
            _sync_decider_grants(self.env, before | self.delegate_id)
        return result


class ApprovalCategoryStepMember(models.Model):
    _inherit = "approval.category.step.member"

    @api.model_create_multi
    def create(self, vals_list):
        members = super().create(vals_list)
        _sync_decider_grants(self.env, members.user_id)
        return members

    def write(self, vals):
        before = self.user_id if "user_id" in vals else self.env["res.users"]
        result = super().write(vals)
        if "user_id" in vals:
            _sync_decider_grants(self.env, before | self.user_id)
        return result

    def unlink(self):
        users = self.user_id
        result = super().unlink()
        _sync_decider_grants(self.env, users)
        return result
