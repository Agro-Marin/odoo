from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.libs.text import nl2br


class ApprovalDecisionWizard(models.TransientModel):
    _name = "approval.decision.wizard"
    _description = "Approval Decision Wizard"

    approver_id = fields.Many2one(
        comodel_name="approval.approver",
        readonly=True,
        required=True,
        help="The approver record making this decision.",
    )
    request_id = fields.Many2one(
        comodel_name="approval.request",
        string="Approval Request",
        compute="_compute_request_id",
        precompute=True,
        store=True,
        readonly=True,
        required=True,
        help="The approval request being decided. Auto-populated from ``approver_id``.",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        related="approver_id.user_id",
        readonly=True,
    )
    decision_type = fields.Selection(
        selection=[
            ("refuse", "Refuse"),
            ("change", "Request Change"),
        ],
        string="Decision",
        required=True,
        readonly=True,
        help="Type of decision being made",
    )

    refusal_reason_id = fields.Many2one(
        comodel_name="approval.refusal.reason",
        help="Select the primary reason for ending this request",
    )
    refusal_reason_description = fields.Text(
        related="refusal_reason_id.description",
        readonly=True,
        help="Internal guidance shown to the approver to clarify when "
        "this reason applies. Rendered as a read-only info banner in "
        "the wizard; never persisted on the request or sent to the "
        "requester.",
    )
    change_field = fields.Selection(
        selection=[
            ("date", "Date"),
            ("reason", "Description"),
        ],
        string="Field to Modify",
        help="Field the requester must update before the approver can "
        "decide. Only date and description (reason) are eligible; "
        "amount, lines and other structural data cannot be changed "
        "in-flight.",
    )

    note = fields.Text(
        help="Free-text message to the requester. Required when "
        "requesting a change; optional when refusing.",
    )
    request_name = fields.Char(
        string="Request",
        related="request_id.name",
        readonly=True,
    )
    request_owner_id = fields.Many2one(
        comodel_name="res.users",
        string="Request Owner",
        related="request_id.request_owner_id",
        readonly=True,
    )
    category_id = fields.Many2one(
        comodel_name="approval.category",
        string="Category",
        related="request_id.category_id",
        readonly=True,
    )

    @api.depends("approver_id")
    def _compute_request_id(self):
        for wiz in self:
            if wiz.approver_id:
                wiz.request_id = wiz.approver_id.request_id

    def _decision_verb(self, decision_type: str) -> str:
        return {
            "refuse": self.env._("refuse"),
            "change": self.env._("request a change on"),
        }[decision_type]

    def _check_decision_allowed(self, action_verb: str) -> None:
        self.ensure_one()

        if self.approver_id.state != "pending":
            raise UserError(
                self.env._(
                    "This approval is no longer pending. Current state: %(state)s",
                    state=self.approver_id.state,
                ),
            )

        effective_approver = self.approver_id._get_effective_approver()
        if self.env.user == effective_approver:
            return

        if self.approver_id.is_delegated:
            raise UserError(
                self.env._(
                    "This approval is currently delegated to %(delegate)s.\n"
                    "You cannot %(verb)s this request while delegation is active.",
                    delegate=self.approver_id.delegate_id.name,
                    verb=action_verb,
                ),
            )
        raise UserError(
            self.env._(
                "You are not authorized to %(verb)s this request.\n"
                "Assigned approver: %(approver)s",
                verb=action_verb,
                approver=self.approver_id.user_id.name,
            ),
        )

    def _check_refusal_reason_applicable(self) -> None:
        self.ensure_one()
        reason = self.refusal_reason_id
        request = self.request_id
        if reason.category_ids and request.category_id not in reason.category_ids:
            raise UserError(
                self.env._(
                    "The reason '%(reason)s' is not available for the "
                    "'%(category)s' category.",
                    reason=reason.name,
                    category=request.category_id.name,
                ),
            )
        if reason.company_id and reason.company_id != request.company_id:
            raise UserError(
                self.env._(
                    "The reason '%(reason)s' is restricted to another "
                    "company and cannot be used on this request.",
                    reason=reason.name,
                ),
            )

    def action_confirm_refuse(self):
        self.ensure_one()
        self._check_decision_allowed(self._decision_verb("refuse"))

        if not self.refusal_reason_id:
            raise UserError(
                self.env._("Please select a reason for refusing this request.")
            )
        self._check_refusal_reason_applicable()

        self.approver_id.write(
            {
                "refusal_reason_id": self.refusal_reason_id.id,
                "note": self.note or False,
            }
        )
        request_vals = {}
        if not self.request_id.refusal_reason_id:
            request_vals["refusal_reason_id"] = self.refusal_reason_id.id
        if not self.request_id.refusal_note:
            request_vals["refusal_note"] = self.note or False
        if request_vals:
            self.request_id.sudo().write(request_vals)

        self.approver_id.with_context(skip_wizard=True).action_refuse()
        return {"type": "ir.actions.act_window_close"}

    def action_confirm_change(self):
        self.ensure_one()
        self._check_decision_allowed(self._decision_verb("change"))

        if not self.change_field:
            raise UserError(
                self.env._(
                    "Select which field the requester must update "
                    "(date or description).",
                ),
            )
        if not self.note:
            raise UserError(
                self.env._(
                    "Explain what the requester should change.",
                ),
            )

        self.request_id.with_context(
            skip_wizard=True,
            requested_change_field=self.change_field,
        ).action_request_change(approver=self.approver_id)

        field_label = dict(
            self._fields["change_field"]._description_selection(self.env)
        )[self.change_field]
        self.request_id.activity_schedule(
            "approval.mail_activity_data_change_request",
            user_id=self.request_id.request_owner_id.id,
            summary=self.env._("Change requested on %s", field_label),
            note=nl2br(self.note),
        )
        return {"type": "ir.actions.act_window_close"}

    def action_cancel(self):
        return {"type": "ir.actions.act_window_close"}
