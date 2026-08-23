from collections import Counter
from typing import Any, Self

from odoo import api, fields, models


class ApprovalRequest(models.Model):
    _name = "approval.request"
    _description = "Approval Request"
    _inherit = ["mixin.mail.thread.main.attachment", "mixin.mail.activity"]
    _check_company_auto = True
    _mail_post_access = "read"
    _order = "create_date desc, id desc"

    ESCALATION_RULES = {
        "3": {
            "first_reminder": 4,
            "escalation": 8,
        },
        "2": {
            "first_reminder": 24,
            "escalation": 48,
        },
        "1": {
            "first_reminder": 48,
            "escalation": 96,
        },
        "0": {
            "first_reminder": 72,
            "escalation": 168,
        },
    }

    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self.env.company,
        index=True,
    )
    category_id = fields.Many2one(
        comodel_name="approval.category",
        required=True,
        index=True,
        domain="""
            [
                '|', '|', '&',
                ('allowed_user_ids', '=', False),
                ('allowed_group_ids', '=', False),
                ('allowed_user_ids', '=', uid),
                ('allowed_group_ids.all_user_ids', '=', uid)
            ]
        """,
    )
    category_image = fields.Binary(related="category_id.image")
    request_owner_id = fields.Many2one(
        comodel_name="res.users",
        required=True,
        default=lambda self: self.env.user,
        check_company=True,
        domain="[('company_ids', 'in', company_id)]",
        index=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        check_company=True,
        index="btree_not_null",
    )
    name = fields.Char(
        tracking=True,
        copy=False,
        help="Empty until the request is confirmed, then set to the "
        "category's sequence consecutive (deferred so discarded drafts "
        "never burn sequence numbers). Draft requests display a "
        "translated 'New' placeholder via display_name. The column "
        "itself stays language-neutral: storing a translated "
        "placeholder made the numbering check fail when the creator "
        "and the confirmer used different languages.",
    )
    priority = fields.Selection(
        selection=[
            ("0", "Low"),
            ("1", "Normal"),
            ("2", "High"),
            ("3", "Urgent"),
        ],
        default="1",
        required=True,
        tracking=True,
        index=True,
        help="Priority drives how quickly reminders and manager escalation "
        "fire for pending approvals (see the escalation schedule in the "
        "category/cron documentation; configurable via system parameters). "
        "Indexed because cron_smart_escalation filters and groups pending "
        "requests by (state, priority) every 4 hours.",
    )

    last_reminder_date = fields.Datetime(
        readonly=True,
        copy=False,
        help="Timestamp of last escalation reminder sent to approvers",
    )
    reminder_count = fields.Integer(
        default=0,
        readonly=True,
        copy=False,
        help="Number of escalation reminders sent for this request",
    )
    escalated_to_manager = fields.Boolean(
        default=False,
        readonly=True,
        copy=False,
        help="Whether this request has been escalated to approver's manager",
    )
    date = fields.Datetime()
    date_start = fields.Datetime()
    date_end = fields.Datetime()
    date_deadline = fields.Datetime()
    date_planned = fields.Datetime()
    date_confirmed = fields.Datetime(
        index=True,
        copy=False,
        help="Set at confirmation (action_confirm). Never copied: a "
        "duplicated request is a fresh draft and must not inherit the "
        "source's submission time, which would skew SLA/deadline "
        "arithmetic and the analytics views.",
    )
    date_approval_granted = fields.Datetime(
        compute="_compute_date_approval_granted",
        store=True,
        readonly=True,
        copy=False,
        index=True,
        help="Date and time when final approval was granted",
    )
    date_refused = fields.Datetime(
        compute="_compute_date_refused",
        store=True,
        readonly=True,
        copy=False,
        index=True,
        help="Date and time when request reached the terminal refused state "
        "(set on refuse).",
    )
    date_cancelled = fields.Datetime(
        compute="_compute_date_cancelled",
        store=True,
        readonly=True,
        copy=False,
        index=True,
        help="Date and time when the request reached the terminal cancelled "
        "state (owner cancellation or auto-expiration).",
    )
    refusal_reason_id = fields.Many2one(
        comodel_name="approval.refusal.reason",
        readonly=True,
        copy=False,
        tracking=True,
        help="Canonical reason for the terminal refused transition. "
        "For refused requests it stores the deciding approver's choice.",
    )
    refusal_note = fields.Text(
        readonly=True,
        copy=False,
        tracking=True,
        help="Free-text note attached to the terminal refused transition.",
    )
    pending_change_field = fields.Selection(
        selection=[
            ("date", "Date"),
            ("reason", "Description"),
        ],
        string="Requested Change",
        readonly=True,
        copy=False,
        help="Field the requester must update before approval can resume. "
        "Set by the approver via the decision wizard; cleared by the "
        "requester through the Re-submit button. The approver's note "
        "explaining the change lives in the chatter.",
    )
    location = fields.Char()
    reference = fields.Char()
    reason = fields.Html()
    quantity = fields.Float()
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
        help="Currency the request amount is expressed in. Defaults to the "
        "company currency; set from the source document by approval.mixin. "
        "Tiers and conditional rules convert this amount into their own "
        "reference currency before comparing thresholds, so a shared "
        "category's amount routing is correct across companies with "
        "different currencies.",
    )
    amount = fields.Monetary(
        currency_field="currency_id",
        help="Request amount, in currency_id. Monetary (currency-rounded) "
        "so amount-based tier/rule routing is currency-aware.",
    )
    approver_ids = fields.One2many(
        comodel_name="approval.approver",
        inverse_name="request_id",
        readonly=False,
        check_company=True,
    )
    user_ids = fields.Many2many(
        comodel_name="res.users",
        compute="_compute_user_ids",
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ("new", "To Submit"),
            ("pending", "Submitted"),
            ("approved", "Approved"),
            ("refused", "Refused"),
            ("cancelled", "Cancelled"),
        ],
        default="new",
        compute="_compute_state",
        store=True,
        tracking=True,
        group_expand=True,
        index=True,
    )
    user_approver_state = fields.Selection(
        selection=[
            ("new", "New"),
            ("pending", "To Approve"),
            ("waiting", "Waiting"),
            ("approved", "Approved"),
            ("refused", "Refused"),
            ("cancelled", "Cancelled"),
        ],
        compute="_compute_user_approver_state",
    )

    is_terminal = fields.Boolean(
        compute="_compute_is_terminal",
        help="True once the request reaches approved, refused or cancelled. "
        "Exists so views can express 'this is over' by NAME: the membership "
        "test was written out as a literal triple in four `invisible` "
        "expressions, which is a second copy of _TERMINAL_STATES that no "
        "amount of Python discipline keeps in step.",
    )
    has_access_to_request = fields.Boolean(
        compute="_compute_request_access_rights",
    )
    can_change_request_owner = fields.Boolean(
        compute="_compute_request_access_rights",
    )
    has_automation = fields.Selection(related="category_id.has_automation")
    has_date = fields.Selection(related="category_id.has_date")
    has_date_deadline = fields.Selection(related="category_id.has_date_deadline")
    has_date_planned = fields.Selection(related="category_id.has_date_planned")
    has_date_range = fields.Selection(related="category_id.has_date_range")
    has_quantity = fields.Selection(related="category_id.has_quantity")
    has_amount = fields.Selection(related="category_id.has_amount")
    has_reference = fields.Selection(related="category_id.has_reference")
    has_partner = fields.Selection(related="category_id.has_partner")
    has_payment_method = fields.Selection(related="category_id.has_payment_method")
    has_location = fields.Selection(related="category_id.has_location")
    has_document = fields.Selection(related="category_id.has_document")
    document_requirement_ids = fields.One2many(
        related="category_id.document_requirement_ids",
        string="Required Documents",
        help="The category's document requirements, related onto the request "
        "so the Documents page can offer exactly those in the 'Satisfies "
        "Requirement' dropdown beside each attachment.",
    )
    approval_minimum = fields.Integer(
        default=1,
        readonly=True,
        copy=True,
        help="Effective minimum approvals needed. Defaults from category, "
        "overridden by matching tier when applicable.",
    )
    approve_sequentially = fields.Boolean(related="category_id.approve_sequentially")
    group_approval = fields.Selection(related="category_id.group_approval")
    approver_group_id = fields.Many2one(related="category_id.approver_group_id")
    approval_type = fields.Selection(
        related="category_id.approval_type",
        store=True,
        help="Category for filtering (e.g., purchase, expense)",
    )
    target_model = fields.Selection(
        related="category_id.target_model",
        store=True,
        help="Model to create when approval is granted (if any)",
    )

    approval_progress = fields.Float(
        compute="_compute_approval_progress",
        help="Percentage of approvals completed (approved / total approvers)",
    )
    pending_approver_ids = fields.Many2many(
        comodel_name="res.users",
        compute="_compute_pending_approver_ids",
        help="Users who still need to approve this request",
    )

    approval_deadline = fields.Datetime(
        compute="_compute_approval_deadline",
        store=True,
        index=True,
        help="Deadline for approval decision based on category settings",
    )
    is_overdue = fields.Boolean(
        compute="_compute_is_overdue",
        search="_search_is_overdue",
        help="True if approval deadline has passed and request still pending",
    )
    hours_until_deadline = fields.Float(
        compute="_compute_hours_until_deadline",
        help="Hours remaining until approval deadline (negative if overdue)",
    )

    sla_status = fields.Selection(
        selection=[
            ("on_track", "On Track"),
            ("at_risk", "At Risk"),
            ("breached", "SLA Breached"),
            ("met", "SLA Met"),
            ("no_sla", "No SLA"),
        ],
        compute="_compute_sla_status",
        search="_search_sla_status",
        help="SLA compliance status for this request. Non-stored: the "
        "value tracks the wall clock (see _compute_sla_status); "
        "filtering goes through _search_sla_status.",
    )
    sla_elapsed_hours = fields.Float(
        compute="_compute_sla_elapsed_hours",
        help="Hours elapsed since request was submitted",
    )
    sla_remaining_hours = fields.Float(
        compute="_compute_sla_remaining_hours",
        help="Hours remaining until SLA target (negative if breached)",
    )

    can_withdraw = fields.Boolean(
        compute="_compute_can_withdraw",
        help="Whether current user can withdraw their approval on this request.",
    )
    is_pending_my_review = fields.Boolean(
        string="Awaiting My Decision",
        compute="_compute_is_pending_my_review",
        search="_search_is_pending_my_review",
        help="True when this request is pending AND the current user is the "
        "effective approver of a row that is itself still pending. "
        "Exists so XML domains (menu actions, search filters) can express "
        "'awaiting my decision' by NAME instead of re-typing the leaves: "
        "hand-written copies drifted from _get_domain_pending_review() and "
        "inverted delegation — the delegate's inbox came up empty while "
        "the delegator, who can no longer act, still saw the request.",
    )
    template_id = fields.Many2one(
        comodel_name="approval.template",
        readonly=True,
        copy=False,
        index="btree_not_null",
        help="Template this request was created from (if any)",
    )
    applied_rule_ids = fields.Many2many(
        comodel_name="approval.rule",
        readonly=True,
        copy=False,
        help="Conditional rules that added approvers to this request",
    )
    category_snapshot = fields.Json(
        readonly=True,
        copy=False,
        help="Snapshot of category configuration at confirmation time",
    )

    predicted_outcome = fields.Selection(
        selection=[
            ("approve", "Likely Approved"),
            ("refuse", "Likely Refused"),
            ("uncertain", "Uncertain"),
        ],
        compute="_compute_outcome_prediction",
        help="Prediction based on similar historical requests",
    )
    prediction_confidence = fields.Float(
        compute="_compute_outcome_prediction",
        help="Confidence score (0-1) for the predicted outcome",
    )

    res_model = fields.Char(
        readonly=True,
        index=True,
        copy=False,
        help="Model name of the source document (e.g., 'purchase.order', "
        "'sale.order'). Never copied: a duplicated request is a fresh, "
        "unlinked draft — inheriting the source pointer would make the "
        "clone's decision drive a document it does not own (see "
        "_notify_source_document_state_change, which additionally "
        "verifies the reverse link before firing any hook).",
    )
    res_id = fields.Many2oneReference(
        model_field="res_model",
        readonly=True,
        copy=False,
        help="Reference to the source document that requested this "
        "approval. Never copied (see res_model).",
    )
    res_model_id = fields.Many2one(
        comodel_name="ir.model",
        string="Source Model",
        compute="_compute_res_model_id",
        store=True,
        help="Technical model reference for filtering",
    )
    res_name = fields.Char(
        compute="_compute_res_name",
        help="Display name of the source document",
    )

    attachment_ids = fields.One2many(
        comodel_name="ir.attachment",
        inverse_name="res_id",
        domain=[("res_model", "=", "approval.request")],
    )
    count_attachment = fields.Integer(
        compute="_compute_count_attachment",
    )

    automation_id = fields.Many2one(
        related="category_id.automation_id",
    )
    automation_runtime_id = fields.Many2one(
        comodel_name="automation.runtime",
        index="btree_not_null",
    )

    @api.model
    def _get_fields_approver_sync_trigger(self) -> frozenset[str]:
        return self._get_routing_fields_frozen() | self._get_routing_fields_live()

    @api.model
    def _get_routing_fields_live(self) -> frozenset[str]:
        return frozenset({"priority", "date", "date_start", "date_end"})

    @api.model
    def _get_routing_fields_frozen(self) -> frozenset[str]:
        declared = (
            frozenset({"category_id", "request_owner_id"})
            | self.env["approval.rule"]._get_fields_request_trigger()
        )
        return declared - self._get_routing_fields_live()

    @api.model_create_multi
    def create(self, vals_list: list[dict[str, Any]]) -> Self:
        categories = self.env["approval.category"].browse(
            {vals["category_id"] for vals in vals_list if vals.get("category_id")},
        )
        minimum_by_category = {
            category.id: category.approval_minimum for category in categories
        }
        for vals in vals_list:
            self._check_no_forged_computed_fields(vals)
            if not vals.get("category_id"):
                continue
            if "approval_minimum" not in vals:
                vals["approval_minimum"] = minimum_by_category[vals["category_id"]]

        created_requests = super().create(vals_list)

        created_requests._subscribe_owners()

        created_requests._sync_approvers()

        return created_requests

    def _subscribe_owners(self) -> None:
        by_partner: dict[int, list[int]] = {}
        for request in self:
            partner_id = request.request_owner_id.partner_id.id
            if partner_id:
                by_partner.setdefault(partner_id, []).append(request.id)
        for partner_id, request_ids in by_partner.items():
            self.browse(request_ids).message_subscribe(partner_ids=[partner_id])

    def write(self, vals: dict[str, Any]) -> bool:
        self._check_access_write()

        self._check_no_forged_computed_fields(vals)

        self._check_locked_fields(vals)

        if "category_id" in vals:
            new_category_id = vals["category_id"] or False
            for request in self:
                if request.state != "new" and request.category_id.id != new_category_id:
                    request._raise_category_change_blocked(request.category_id)

        if "request_owner_id" in vals:
            outgoing: dict[int, list[int]] = {}
            for approval in self:
                partner_id = approval.request_owner_id.partner_id.id
                if partner_id:
                    outgoing.setdefault(partner_id, []).append(approval.id)
            for partner_id, request_ids in outgoing.items():
                self.browse(request_ids).message_unsubscribe(partner_ids=[partner_id])

        if "approver_ids" in vals:
            self._check_access_approver_ids(vals["approver_ids"])
            self._check_approver_ids_business_rules(vals["approver_ids"])

        res = super().write(vals)

        if self._get_fields_approver_sync_trigger() & vals.keys():
            self._sync_approvers()
            self._extend_approvers_live()

        if "request_owner_id" in vals:
            self._subscribe_owners()

        return res

    def _recent_approved_by_owner(self, limit: int = 10) -> Self:
        self.ensure_one()
        return self._recent_approved_by_category(
            self.category_id,
            self.request_owner_id,
            limit=limit,
        )[self.category_id.id]

    def _recent_approved_by_category(self, categories, owner, limit: int = 10) -> dict:
        by_category: dict[int, list[int]] = {
            category_id: [] for category_id in categories.ids
        }
        if not categories or not owner:
            return {category_id: self.browse() for category_id in by_category}
        candidates = self.search(
            [
                ("request_owner_id", "=", owner.id),
                ("category_id", "in", categories.ids),
                ("state", "=", "approved"),
            ],
            order="date_confirmed desc",
            limit=limit * len(categories),
        )
        for request in candidates:
            bucket = by_category[request.category_id.id]
            if len(bucket) < limit:
                bucket.append(request.id)
        return {
            category_id: self.browse(ids) for category_id, ids in by_category.items()
        }

    def _smart_clone_defaults(self, recent=None) -> dict[str, Any]:
        self.ensure_one()
        category = self.category_id
        smart: dict[str, Any] = {}
        if recent is None:
            recent = self._recent_approved_by_owner(limit=10)

        if category.has_amount != "no":
            amounts = [r.amount for r in recent if r.amount]
            if amounts:
                smart["amount"] = sum(amounts) / len(amounts)

        if category.has_partner != "no" and recent:
            partners = recent.mapped("partner_id").filtered(bool)
            if partners:
                smart["partner_id"] = Counter(partners).most_common(1)[0][0].id

        return smart

    def copy_data(self, default: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        explicit = dict(default or {})
        vals_list = super().copy_data(default=explicit)
        recent_by_owner = {
            owner.id: self._recent_approved_by_category(
                self.filtered(lambda r, o=owner: r.request_owner_id == o).category_id,
                owner,
            )
            for owner in self.request_owner_id
        }
        for source, vals in zip(self, vals_list, strict=True):
            recent = recent_by_owner.get(source.request_owner_id.id, {}).get(
                source.category_id.id, self.browse()
            )
            for key, value in source._smart_clone_defaults(recent).items():
                if key not in explicit:
                    vals[key] = value
        return vals_list

    def copy(self, default: dict[str, Any] | None = None) -> Self:
        new_records = super().copy(default=default)
        for source, new in zip(self, new_records, strict=True):
            new._message_log(
                body=self.env._("Duplicated from %s", source._get_html_link()),
            )
        return new_records

    def unlink(self) -> bool:
        self._check_access_unlink()
        self._check_business_rules_unlink()
        return super().unlink()

    @api.ondelete(at_uninstall=False)
    def unlink_attachments(self) -> None:
        attachment_ids = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "approval.request"),
                ("res_id", "in", self.ids),
            ],
        )
        if attachment_ids:
            attachment_ids.unlink()

    def _track_subtype(self, init_values: dict[str, Any]) -> str | bool:
        self.ensure_one()
        if "state" in init_values:
            return self.env.ref("approval.mt_approval_state")

        return super()._track_subtype(init_values)
