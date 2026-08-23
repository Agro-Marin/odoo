from typing import Any, Self

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain

from .approval_utils import boolean_search_domain, is_approval_manager


class ApprovalApprover(models.Model):
    _name = "approval.approver"
    _description = "Approver"
    _order = "sequence, id"
    _check_company_auto = True

    _request_user_uniq = models.Constraint(
        "unique(request_id, user_id)",
        "You cannot assign the same approver multiple times on the same request.",
    )

    request_id = fields.Many2one(
        comodel_name="approval.request",
        required=True,
        check_company=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="request_id.company_id",
        store=True,
        string="Company",
        readonly=True,
        index=True,
    )
    existing_request_user_ids = fields.Many2many(
        comodel_name="res.users",
        compute="_compute_existing_request_user_ids",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        required=True,
        check_company=True,
        domain="['|', ('id', 'not in', existing_request_user_ids), ('id', '=', user_id)]",
        index=True,
    )
    sequence = fields.Integer(default=10)
    state = fields.Selection(
        selection=[
            ("new", "New"),
            ("pending", "To Approve"),
            ("waiting", "Waiting"),
            ("approved", "Approved"),
            ("refused", "Refused"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="new",
        readonly=True,
        copy=False,
        index=True,
        help="Never copied: _sync_approvers() matches a copied approver "
        "row to its category source by user_id and only ever updates "
        "required/sequence on a match, never state — so a decided row "
        "(approved/refused) copied verbatim would stay decided forever "
        "on a request that was never confirmed.",
    )
    required = fields.Boolean(default=False, readonly=True)
    source_rule_id = fields.Many2one(
        comodel_name="approval.rule",
        readonly=True,
        copy=False,
        ondelete="set null",
        index="btree_not_null",
        help="Conditional rule that injected this approver, if any — an "
        "adding rule or the replacing rule this request fell into (audit + "
        "re-sync provenance). There used to be a second column, "
        "source_tier_id, for the separate approval.tier model.",
    )
    source_synced = fields.Boolean(
        readonly=True,
        copy=False,
        help="Set when this row was produced by the approver sync from an "
        "automated source (category approver, tier, rule, security group, "
        "extension hook such as the HR manager). False on genuinely manual "
        "rows. Drives the orphan-vs-manual classification on re-sync: a "
        "synced row whose source stopped producing it (approver removed "
        "from the category, owner changed away from a manager) is deleted "
        "instead of surviving as a phantom optional approver.",
    )
    pending_since = fields.Datetime(
        readonly=True,
        copy=False,
        index="btree_not_null",
        help="When this row ENTERED the decision window (state became "
        "'pending'). The symmetric half of decision_date, which records "
        "when it left. Approver-response analytics measure "
        "decision_date - pending_since so they report THIS approver's "
        "turnaround; measuring against the request's date_confirmed "
        "instead charged every approver in a sequential chain for the "
        "delays of everyone ahead of them, which made the dashboard's "
        "'Slowest Approver' reliably name whoever sits last in the "
        "chain. Cleared when the row returns to 'new' (reset-to-draft) "
        "and re-stamped on every re-entry, so a withdraw-and-reopen "
        "cycle times the new decision window, not the original one.",
    )
    decided_by_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Decided By",
        readonly=True,
        copy=False,
        index="btree_not_null",
        help="Who actually made the decision recorded in decision_date — "
        "the delegate when the row was decided inside an active delegation "
        "window, otherwise user_id itself. The pair (user_id, "
        "decided_by_user_id) separates WHOSE approval slot this is from WHO "
        "exercised it; every other identity question in the module resolves "
        "the effective approver, and without this column the analytics were "
        "the one place that could not: approver.performance credited the "
        "delegated decision (and its response time) to the absent principal "
        "while the delegate who did the work scored nothing. Left empty for "
        "rows flipped by non-decisions, exactly like decision_date, and "
        "cleared beside it on withdraw and reset-to-draft.",
    )
    decision_date = fields.Datetime(
        readonly=True,
        copy=False,
        index="btree_not_null",
        help="When THIS approver personally approved or refused, stamped "
        "by the decision funnel (_apply_decision). Left empty for rows "
        "flipped by non-decisions — consent auto-approval, sequential/"
        "cascade refusal, owner cancellation, expiration — so the "
        "approver-performance analytics count only genuine decisions and "
        "measure each approver's own response time (cleared on withdraw "
        "and reset-to-draft).",
    )
    can_edit = fields.Boolean(
        compute="_compute_edit_permissions",
    )
    can_edit_user_id = fields.Boolean(
        compute="_compute_edit_permissions",
        help="Simple users should not be able to remove themselves as approvers "
        "because they will lose access to the record if they misclick.",
    )
    delegate_id = fields.Many2one(
        comodel_name="res.users",
        string="Delegate To",
        check_company=True,
        copy=False,
        help="Temporary delegate who can approve on your behalf",
    )
    delegate_start_date = fields.Date(
        string="Delegation Start",
        copy=False,
        help="Start date for delegation period",
    )
    delegate_end_date = fields.Date(
        string="Delegation End",
        copy=False,
        help="End date for delegation period",
    )
    is_delegated = fields.Boolean(
        string="Currently Delegated",
        compute="_compute_is_delegated",
        search="_search_is_delegated",
        copy=False,
        help="Indicates if approval is currently delegated to another user. "
        "Non-stored on purpose: the value is a function of wall-clock "
        "'today' vs the delegation window, and no ORM write happens when "
        "the clock advances past delegate_start_date. A stored compute "
        "would freeze at False forever for any delegation scheduled "
        "in advance. A custom search method keeps the field usable in "
        "domain filters (e.g. the 'Delegated to Me' search view).",
    )

    note = fields.Text(
        copy=False,
        help="Optional note or comment added when approving or refusing the request. "
        "Use this to provide context, conditions, or reasons for your decision.",
    )
    refusal_reason_id = fields.Many2one(
        comodel_name="approval.refusal.reason",
        copy=False,
        help="Structured reason for refusing the request",
    )

    @api.constrains("delegate_id", "delegate_start_date", "delegate_end_date")
    def _check_delegation_dates(self):
        for approver in self:
            if approver.delegate_id:
                if not (approver.delegate_start_date and approver.delegate_end_date):
                    raise ValidationError(
                        self.env._(
                            "Both start and end dates are required for delegation."
                        ),
                    )
                if approver.delegate_end_date < approver.delegate_start_date:
                    raise ValidationError(
                        self.env._("Delegation end date must be after start date."),
                    )

    @api.constrains("delegate_id", "user_id", "request_id")
    def _check_delegate_identity(self):
        for approver in self:
            delegate = approver.delegate_id
            other_approvers = approver.request_id.approver_ids - approver
            if approver.user_id and approver.user_id in other_approvers.delegate_id:
                raise ValidationError(
                    self.env._(
                        "%(user)s already covers another approval on this "
                        "request as a delegate. Holding an approval of their "
                        "own as well would let one person satisfy two "
                        "approvals — end that delegation first.",
                        user=approver.user_id.name,
                    ),
                )
            if not delegate:
                continue
            if delegate == approver.user_id:
                raise ValidationError(
                    self.env._(
                        "You cannot delegate an approval to yourself.",
                    ),
                )
            if delegate == approver.request_id.request_owner_id:
                raise ValidationError(
                    self.env._(
                        "You cannot delegate this approval to the request "
                        "owner (%(owner)s) — they would approve their own "
                        "request.",
                        owner=delegate.name,
                    ),
                )
            if delegate in other_approvers.mapped("user_id"):
                raise ValidationError(
                    self.env._(
                        "%(delegate)s is already an approver on this "
                        "request. Delegating to a co-approver would let "
                        "one person hold two approvals.",
                        delegate=delegate.name,
                    ),
                )

    @api.model_create_multi
    def create(self, vals_list: list[dict]) -> Self:
        self._check_access_create(vals_list)
        self._check_business_rules_create(vals_list)
        return super().create([self._stamp_pending_since(v) for v in vals_list])

    def write(self, vals: dict) -> bool:
        self._check_access_write(vals)
        self._check_business_rules_write(vals)
        return super().write(self._stamp_pending_since(vals))

    def _stamp_pending_since(self, vals: dict) -> dict:
        state = vals.get("state")
        if state == "pending":
            return {**vals, "pending_since": fields.Datetime.now()}
        if state == "new":
            return {**vals, "pending_since": False}
        return vals

    def unlink(self) -> bool:
        self._check_access_unlink()
        self._check_business_rules_unlink()
        return super().unlink()

    @api.depends("request_id.request_owner_id", "request_id.approver_ids.user_id")
    def _compute_existing_request_user_ids(self):
        for approver in self:
            approver.existing_request_user_ids = (
                approver.request_id.approver_ids.mapped("user_id")._origin
                | approver.request_id.request_owner_id._origin
            )

    def _delegation_today(self):
        self.ensure_one()
        return self._delegation_today_by_tz()[self.user_id.tz or "UTC"]

    def _delegation_today_by_tz(self) -> dict:
        return {
            tz or "UTC": fields.Date.context_today(self.with_context(tz=tz or "UTC"))
            for tz in set(self.user_id.mapped("tz"))
        }

    @api.depends(
        "delegate_start_date", "delegate_end_date", "delegate_id", "user_id.tz"
    )
    def _compute_is_delegated(self):
        schedulable = self.filtered(
            lambda a: a.delegate_id and a.delegate_start_date and a.delegate_end_date,
        )
        (self - schedulable).is_delegated = False
        today_by_tz = schedulable._delegation_today_by_tz()
        for approver in schedulable:
            today = today_by_tz[approver.user_id.tz or "UTC"]
            approver.is_delegated = (
                approver.delegate_start_date <= today <= approver.delegate_end_date
            )

    @api.depends_context("uid")
    @api.depends("user_id", "delegate_id", "is_delegated")
    def _compute_edit_permissions(self) -> None:
        is_manager = is_approval_manager(self.env)
        current_user = self.env.user
        for approval in self:
            effective_approver = approval._get_effective_approver()
            approval.can_edit = is_manager or effective_approver == current_user
            approval.can_edit_user_id = is_manager

    @api.model
    def _delegation_date_buckets(self) -> dict:
        cache = self.env.cr.cache
        if "approval_delegation_tz_buckets" in cache:
            return cache["approval_delegation_tz_buckets"]
        buckets: dict = {}
        rows = (
            self.env["res.users"]
            .sudo()
            .with_context(active_test=False)
            ._read_group([], ["tz"])
        )
        for (tz,) in rows:
            local = fields.Date.context_today(self.with_context(tz=tz or "UTC"))
            buckets.setdefault(local, []).append(tz)
        cache["approval_delegation_tz_buckets"] = buckets
        return buckets

    @api.model
    def _search_is_delegated(self, operator, value):
        active = Domain.FALSE
        for local_date, tz_names in self._delegation_date_buckets().items():
            active |= Domain(
                [
                    ("user_id.tz", "in", tz_names),
                    ("delegate_id", "!=", False),
                    ("delegate_start_date", "<=", local_date),
                    ("delegate_end_date", ">=", local_date),
                ],
            )
        return boolean_search_domain(operator, value, active, ~active)

    def _fan_in_siblings(self) -> Self:
        return self.request_id._get_current_pending_approver(
            self._get_effective_approver(),
        )

    def action_approve(self) -> dict[str, Any] | None:
        self.ensure_one()
        return self.request_id.action_approve(self._fan_in_siblings())

    def action_refuse(self) -> dict[str, Any]:
        self.ensure_one()

        if self.env.context.get("skip_wizard"):
            return self.request_id.action_refuse(self._fan_in_siblings())

        return self.request_id._get_decision_wizard_action("refuse")

    def _create_activity(self):
        if not self:
            return
        if self.env.context.get("mail_activity_automation_skip"):
            return
        activity_type = self.env.ref("approval.mail_activity_data_approval")
        model_id = self.env["ir.model"]._get("approval.request").id
        date_deadline = fields.Date.context_today(self)

        taken = {
            (activity.res_id, activity.user_id.id)
            for activity in self.request_id.activity_ids
            if activity.activity_type_id == activity_type
        }
        create_vals_list = []
        for approver in self:
            key = (approver.request_id.id, approver._get_effective_approver().id)
            if key in taken:
                continue
            taken.add(key)
            create_vals_list.append(
                {
                    "activity_type_id": activity_type.id,
                    "summary": activity_type.summary,
                    "automated": True,
                    "note": activity_type.default_note,
                    "date_deadline": date_deadline,
                    "res_model_id": model_id,
                    "res_id": key[0],
                    "user_id": key[1],
                },
            )
        if create_vals_list:
            self.env["mail.activity"].create(create_vals_list)

    def _get_effective_approver(self):
        self.ensure_one()
        if self.is_delegated:
            return self.delegate_id
        return self.user_id

    def _check_access_create(self, vals_list: list[dict]) -> None:
        if self._skip_check_access():
            return

        if not vals_list:
            return
        first_with_request = next(
            (v for v in vals_list if v.get("request_id")),
            None,
        )
        request_name = self.env._("New")
        if first_with_request:
            request = self.env["approval.request"].browse(
                first_with_request["request_id"]
            )
            if request.exists():
                request_name = request._label()
        raise AccessError(
            self.env._(
                "Approvers cannot be added manually.\n\n"
                "Approvers are defined by the approval category and "
                "managed automatically.\n\n"
                "Request: %(name)s",
                name=request_name,
            ),
        )

    def _check_access_unlink(self) -> None:
        if self._skip_check_access():
            return

        approver = self[:1]
        if approver:
            raise AccessError(
                self.env._(
                    "Approvers cannot be removed from requests.\n\n"
                    "Approvers are defined by the approval category and managed "
                    "automatically. Removing them would break the approval workflow.\n\n"
                    "Request: %(name)s\nApprover: %(approver)s",
                    name=approver.request_id._label(),
                    approver=approver.user_id.name,
                ),
            )

    _DELEGATION_ONLY_FIELDS = frozenset(
        {"delegate_id", "delegate_start_date", "delegate_end_date"},
    )

    _SELF_WRITABLE_FIELDS = frozenset({"refusal_reason_id", "note"})

    def _check_access_write(self, vals: dict | None = None) -> None:
        if self._skip_check_access():
            return

        written = set(vals or ())
        if not written:
            return
        delegation_only = bool(written) and written.issubset(
            self._DELEGATION_ONLY_FIELDS,
        )
        decision_metadata_only = bool(written) and written.issubset(
            self._SELF_WRITABLE_FIELDS,
        )

        for approver in self:
            if delegation_only and self.env.user == approver.user_id:
                continue

            effective_approver = approver._get_effective_approver()
            if decision_metadata_only and effective_approver == self.env.user:
                continue

            if delegation_only and self.env.user == approver.delegate_id:
                raise AccessError(
                    self.env._(
                        "Only the original approver (%(approver)s) can "
                        "modify the delegation of this approval.\n\n"
                        "Request: %(name)s",
                        name=approver.request_id._label(),
                        approver=approver.user_id.name,
                    ),
                )
            if effective_approver == self.env.user:
                raise AccessError(
                    self.env._(
                        "These fields are managed by the approval workflow "
                        "and cannot be modified directly (%(fields)s).\n\n"
                        "Use the Approve/Refuse buttons to record a "
                        "decision.\n\n"
                        "Request: %(name)s\nApprover: %(approver)s",
                        fields=", ".join(sorted(written)),
                        name=approver.request_id._label(),
                        approver=approver.user_id.name,
                    ),
                )
            if approver.is_delegated:
                raise AccessError(
                    self.env._(
                        "This approval is currently delegated to %(delegate)s.\n\n"
                        "Request: %(name)s\nOriginal approver: %(approver)s",
                        name=approver.request_id._label(),
                        approver=approver.user_id.name,
                        delegate=approver.delegate_id.name,
                    ),
                )
            raise AccessError(
                self.env._(
                    "Only the assigned approver can modify their approval record.\n\n"
                    "Request: %(name)s\nApprover: %(approver)s",
                    name=approver.request_id._label(),
                    approver=approver.user_id.name,
                ),
            )

    _WORKFLOW_MANAGED_FIELDS = frozenset(
        {
            "state",
            "sequence",
            "required",
            "request_id",
            "user_id",
            "source_rule_id",
            "source_synced",
            "pending_since",
            "decision_date",
            "decided_by_user_id",
        },
    )

    def _check_business_rules_write(self, vals: dict) -> None:
        if self.env.su:
            return
        forced = set(vals) & self._WORKFLOW_MANAGED_FIELDS
        if forced:
            raise ValidationError(
                self.env._(
                    "%(fields)s cannot be modified directly — they are "
                    "managed by the approval workflow.\n\n"
                    "Use the Approve/Refuse buttons to record a decision, "
                    "or reconfigure the category/tier/rule that governs "
                    "this approver instead.",
                    fields=", ".join(sorted(forced)),
                ),
            )
        decision_metadata = set(vals) & self._SELF_WRITABLE_FIELDS
        if decision_metadata:
            terminal = self.env["approval.request"]._TERMINAL_STATES
            frozen = self.filtered(lambda a: a.request_id.state in terminal)
            if frozen:
                raise ValidationError(
                    self.env._(
                        "%(fields)s cannot be changed once the request is "
                        "approved, refused or cancelled — the decision record "
                        "is part of the audit trail.",
                        fields=", ".join(sorted(decision_metadata)),
                    ),
                )

    def _check_business_rules_create(self, vals_list: list[dict]) -> None:
        if self.env.su and self.env.context.get("approver_ids_computation"):
            return

        for vals in vals_list:
            request_id = vals.get("request_id")
            if not request_id:
                continue

            request = self.env["approval.request"].browse(request_id)
            if not request.exists():
                continue

            if request.state != "new":
                raise ValidationError(
                    self.env._(
                        "Cannot add approvers to requests in %(state)s state.\n\n"
                        "Request: %(name)s\n\n"
                        "Approvers can only be modified while the request is "
                        "a draft. Reset a decided request to draft first — "
                        "the approver list is recomputed there.",
                        name=request._label(),
                        state=request.state,
                    ),
                )

    def _check_business_rules_unlink(self) -> None:
        if self.env.su and self.env.context.get("approver_ids_computation"):
            return

        for approver in self:
            if approver.request_id.state != "new":
                raise ValidationError(
                    self.env._(
                        "Cannot remove approvers from submitted requests.\n\n"
                        "Request: %(name)s\nApprover: %(approver)s\n"
                        "Current state: %(state)s\n\n"
                        "Approvers can only be removed from draft requests "
                        "to preserve the audit trail. Reset a decided "
                        "request to draft first — the approver list is "
                        "recomputed there.",
                        name=approver.request_id._label(),
                        approver=approver.user_id.name,
                        state=approver.request_id.state,
                    ),
                )

    def _skip_check_access(self) -> bool:
        return self.env.su or is_approval_manager(self.env)
