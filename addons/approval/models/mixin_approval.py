from contextlib import contextmanager
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import SQL

if TYPE_CHECKING:
    from odoo.addons.approval.models.approval_category import ApprovalCategory


class MixinApproval(models.AbstractModel):
    _name = "mixin.approval"
    _description = "Approval Mixin for Source Documents"

    approval_request_id = fields.Many2one(
        comodel_name="approval.request",
        copy=False,
        readonly=True,
        index=True,
        tracking=True,
        help="Link to the approval request for this document. Automatically created when approval is requested.",
    )
    approval_state = fields.Selection(
        related="approval_request_id.state",
        string="Approval Status",
        store=True,
        help="""Current approval status:
        • new: Approval created but not submitted
        • pending: Waiting for approvers
        • approved: All required approvals obtained
        • refused: Approval was refused (terminal)
        • cancelled: Approval was retracted or expired (terminal)""",
    )
    date_approval_granted = fields.Datetime(
        related="approval_request_id.date_approval_granted",
        string="Approval Granted Date",
        store=True,
        readonly=True,
        copy=False,
        tracking=True,
        help="Date and time when final approval was granted",
    )
    approval_progress = fields.Float(
        related="approval_request_id.approval_progress",
        help="Percentage of approvals completed (approved / total approvers)",
    )
    pending_approver_ids = fields.Many2many(
        related="approval_request_id.pending_approver_ids",
        string="Pending Approvers",
        help="Users who still need to approve this document",
    )
    date_approval_requested = fields.Datetime(
        related="approval_request_id.date_confirmed",
        string="Approval Requested Date",
        store=True,
        readonly=True,
        copy=False,
        tracking=True,
        help="Date and time when approval was requested for this document",
    )
    approval_user_ids = fields.Many2many(
        related="approval_request_id.user_ids",
        string="Approvers",
        help="Users who need to approve this document",
    )
    approval_required = fields.Boolean(
        compute="_compute_approval_required",
        store=False,
        help="Whether this document requires approval based on current rules",
    )
    can_request_approval = fields.Boolean(
        compute="_compute_can_request_approval",
        help="Whether approval can be requested (all required fields filled)",
    )

    @api.depends_context("uid", "company")
    def _compute_approval_required(self) -> None:
        cache: dict[tuple, bool] = {}
        for record in self:
            company_id = False
            if "company_id" in record._fields:
                company_id = record.company_id.id if record.company_id else False
            key = (repr(record._get_domain_approval_category()), company_id)
            if key not in cache:
                cache[key] = bool(record._get_approval_category())
            record.approval_required = cache[key]

    @api.depends("approval_request_id", "approval_required")
    def _compute_can_request_approval(self) -> None:
        for record in self:
            if record.approval_request_id or not record.approval_required:
                record.can_request_approval = False
                continue

            missing_fields = [
                f for f in record._get_fields_approval_required() if not record[f]
            ]
            record.can_request_approval = not missing_fields

    def _check_can_request_approval(self) -> None:
        self.ensure_one()
        if self.approval_request_id:
            raise UserError(
                self.env._("An approval request already exists for this document."),
            )

        missing_fields = [
            f for f in self._get_fields_approval_required() if not self[f]
        ]
        if missing_fields:
            field_names = ", ".join(
                [self._fields[f].string for f in missing_fields if f in self._fields],
            )
            raise UserError(
                self.env._(
                    "Please fill in the following required fields before requesting approval: %s",
                    field_names,
                ),
            )

        if not self._get_approval_category():
            raise UserError(
                self.env._(
                    "No approval category found for this document type. "
                    "Please configure approval categories first.\n\n"
                    "Go to: Approvals → Configuration → Approval Types",
                ),
            )

        if not self.can_request_approval:
            raise UserError(
                self.env._(
                    "Approval cannot be requested for this document right now.",
                ),
            )

    def action_refuse_approval(self) -> None:
        self.ensure_one()
        self.check_access("write")
        if self.approval_request_id and self.approval_request_id._refuse_cascade():
            self.message_post(
                body=self.env._("Approval request refused (parent document cancelled)"),
                message_type="notification",
            )

    def action_create_approval_request(self) -> dict[str, Any]:
        self.ensure_one()

        self.env.cr.execute(
            SQL(
                "SELECT id FROM %s WHERE id = %s FOR UPDATE",
                SQL.identifier(self._table),
                self.id,
            )
        )
        self.invalidate_recordset(["approval_request_id"])

        self._check_can_request_approval()

        category = self._get_approval_category()
        if not category:
            raise UserError(
                self.env._(
                    "No approval category found for this document type. "
                    "Please configure approval categories first.\n\n"
                    "Go to: Approvals → Configuration → Approval Types",
                ),
            )

        vals = self._prepare_approval_request_values(category)
        approval = self.env["approval.request"].create(vals)
        self.write({"approval_request_id": approval.id})

        self._before_approval_request_submit(approval)

        approval.action_confirm()

        self.message_post(
            body=Markup(
                "<a href='#' data-oe-model='approval.request' data-oe-id='%s'>%s</a> %s"
            )
            % (approval.id, escape(approval.name), self.env._("created")),
            message_type="notification",
        )

        return self._get_approval_submitted_action(approval)

    def _before_approval_request_submit(self, approval) -> None:
        pass

    def _get_approval_submitted_action(self, approval) -> dict[str, Any]:
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": self.env._("Approval Requested"),
                "message": self.env._(
                    "Approval request '%s' has been created and submitted.",
                    approval.name,
                ),
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _approval_rate_limit_rate_date(self):
        self.ensure_one()
        return fields.Date.context_today(self)

    def _approval_rate_limit_exceeded(
        self,
        *,
        hours: int,
        max_count: int,
        max_amount: float,
        under_threshold_amount: float,
        excluded_states: tuple = ("cancel",),
    ) -> bool:
        self.ensure_one()
        company = self.company_id
        company_currency = company.currency_id
        rate_date = self._approval_rate_limit_rate_date()

        policed_user = self.create_uid or self.env.user
        window = Domain(
            [
                ("company_id", "=", company.id),
                ("create_uid", "=", policed_user.id),
                ("create_date", ">=", fields.Datetime.now() - timedelta(hours=hours)),
                ("state", "not in", list(excluded_states)),
            ],
        )
        if self.id:
            window &= Domain([("id", "!=", self.id)])

        currencies = self.env["res.currency"].browse(
            [
                currency.id
                for (currency,) in self.sudo()._read_group(window, ["currency_id"], [])
                if currency
            ],
        )

        count = 0
        cumulative = 0.0
        if currencies:
            under_threshold = Domain.FALSE
            for currency in currencies:
                under_threshold |= Domain(
                    [
                        ("currency_id", "=", currency.id),
                        (
                            "amount_total",
                            "<",
                            company_currency._convert(
                                under_threshold_amount, currency, company, rate_date
                            ),
                        ),
                    ],
                )
            for currency, group_count, group_total in self.sudo()._read_group(
                window & under_threshold,
                ["currency_id"],
                ["__count", "amount_total:sum"],
            ):
                count += group_count
                cumulative += currency._convert(
                    group_total or 0.0, company_currency, company, rate_date
                )

        if count >= max_count:
            return True

        own_amount = self.currency_id._convert(
            self.amount_total, company_currency, company, rate_date
        )
        return cumulative + own_amount >= max_amount

    def _get_fields_approval_protected(self) -> list[str]:
        return []

    def write(self, vals: dict[str, Any]) -> bool:
        if not self.env.su:
            protected = set(self._get_fields_approval_protected())
            touched = protected & vals.keys()
            if touched:
                blocked = self.filtered(lambda r: r.approval_state == "pending")
                if blocked:
                    raise UserError(
                        self.env._(
                            "Cannot modify %(fields)s while approval is "
                            "pending — approvers are deciding on the current "
                            "values. Withdraw or refuse the approval first.\n\n"
                            "Document: %(name)s",
                            fields=", ".join(sorted(touched)),
                            name=blocked[:1].display_name,
                        ),
                    )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_pending_approval(self) -> None:
        for record in self:
            if record.approval_state == "pending":
                raise UserError(
                    self.env._(
                        "Cannot delete %(name)s: it has a pending approval "
                        "request (%(request)s). Cancel or refuse the "
                        "approval first.",
                        name=record.display_name,
                        request=record.approval_request_id.display_name,
                    ),
                )

    def unlink(self) -> bool:
        draft_requests = self.env["approval.request"]
        for record in self:
            if record.approval_request_id and record.approval_state == "new":
                draft_requests |= record.approval_request_id
        res = super().unlink()
        if draft_requests:
            draft_requests.sudo().unlink()
        return res

    def action_view_approval_request(self) -> dict[str, Any]:
        self.ensure_one()
        return self._get_approval_request_view_action()

    def _clear_refused_approval_link(self) -> None:
        for record in self:
            if record.approval_request_id and record.approval_state in (
                "refused",
                "cancelled",
            ):
                approval_name = record.approval_request_id.name
                record.approval_request_id = False
                record.message_post(
                    body=record.env._(
                        "Approval link cleared (previous approval: %s). "
                        "A new approval can be requested when confirming.",
                        approval_name,
                    ),
                    message_type="notification",
                )

    def _get_domain_approval_category(self) -> list[Any]:
        return []

    def _get_approval_category(self) -> "ApprovalCategory | bool":  # noqa: UP037 — ORM methods are runtime-introspected (api_doc, /json/2); the TYPE_CHECKING import means the class isn't in the runtime namespace, so the annotation must stay quoted.
        self.ensure_one()
        domain = self._get_domain_approval_category()
        if not domain:
            return False

        company_id = False
        if "company_id" in self._fields:
            company_id = self.company_id.id if self.company_id else False

        categories = self.env["approval.category"].search(
            domain
            + [
                ("company_id", "in", (company_id, False)),
            ],
        )
        if not categories:
            self._raise_approval_category_not_configured()
            return False

        for category in categories:
            if category._is_applicable_for(self):
                return category

        fallback = self._get_approval_category_fallback(categories)
        if fallback:
            return fallback

        self._raise_approval_category_not_matched(categories)
        return False

    def _get_approval_category_fallback(self, categories):
        self.ensure_one()
        return self.env["approval.category"].browse()

    def _raise_approval_category_not_configured(self) -> None:
        pass

    def _raise_approval_category_not_matched(self, categories) -> None:
        pass

    def _get_approval_reason_html(self) -> str:
        self.ensure_one()
        return self.env._("Approval requested for %s", self.display_name)

    def _get_approval_request_name(self) -> str:
        return self.env._("Approval for %s", self.display_name)

    def _get_approval_request_view_action(self) -> dict[str, Any]:
        self.ensure_one()
        return {
            "name": self.env._("Approval Request"),
            "type": "ir.actions.act_window",
            "res_model": "approval.request",
            "res_id": self.approval_request_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def _get_fields_approval_required(self) -> list[str]:
        return []

    def _prepare_approval_request_values(self, category: Any) -> dict[str, Any]:
        company_id = False
        if "company_id" in self._fields:
            company_id = self.company_id.id if self.company_id else False

        vals = {
            "category_id": category.id,
            "request_owner_id": self.env.user.id,
            "company_id": company_id or self.env.company.id,
            "res_model": self._name,
            "res_id": self.id,
            "reason": self._get_approval_reason_html(),
        }

        field_mapping = {
            "partner_id": "partner_id",
            "amount_total": "amount",
            "date_order": "date",
            "currency_id": "currency_id",
        }

        for source_field, target_field in field_mapping.items():
            if source_field in self._fields and self[source_field]:
                value = self[source_field]
                if hasattr(value, "id"):
                    vals[target_field] = value.id
                else:
                    vals[target_field] = value

        return vals

    def _on_approval_state_changed(self, new_state: str) -> None:
        if new_state == "approved":
            self._on_approval_approved()
        elif new_state == "refused":
            self._on_approval_refused()
        elif new_state == "cancelled":
            self._on_approval_cancelled()
        elif new_state == "pending":
            self._on_approval_revoked()
        elif new_state == "new":
            self._on_approval_reset()

    def _approval_decider_names(self, state: str = "approved") -> str:
        self.ensure_one()
        deciders = self.approval_request_id.approver_ids.filtered(
            lambda approver: approver.state == state and approver.decision_date,
        )
        return ", ".join(
            (approver.decided_by_user_id or approver.user_id).name
            for approver in deciders
        )

    @contextmanager
    def _approval_side_effect(self, failure_note: str):
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                yield
        except (UserError, ValidationError) as error:
            self.message_post(
                body=failure_note % {"error": str(error)},
                message_type="notification",
            )

    def _on_approval_approved(self) -> None:
        self.ensure_one()
        self.message_post(
            body=self.env._("Approval granted"),
            message_type="notification",
        )

    def _on_approval_refused(self) -> None:
        self.ensure_one()
        self.message_post(
            body=self.env._("Approval refused"),
            message_type="notification",
        )

    def _on_approval_cancelled(self) -> None:
        self.ensure_one()
        self.message_post(
            body=self.env._(
                "Approval cancelled (retracted or expired — not a refusal)."
            ),
            message_type="notification",
        )

    def _on_approval_revoked(self) -> None:
        self.ensure_one()
        self.message_post(
            body=self.env._(
                "An approver withdrew their approval — the approval "
                "is pending again. Review this document before "
                "processing it further.",
            ),
            message_type="notification",
        )
        if "activity_ids" in self._fields:
            responsible = getattr(self, "user_id", None) or self.create_uid
            self.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=responsible.id,
                summary=self.env._("Approval was withdrawn"),
                note=self.env._(
                    "The approval linked to this document returned to "
                    "pending after a withdrawal. Confirm whether the "
                    "document should proceed.",
                ),
            )

    def _on_approval_reset(self) -> None:
        self.ensure_one()
        self.message_post(
            body=self.env._(
                "The approval linked to this document was reset to draft — "
                "the prior approval is no longer valid. Review this document "
                "before processing it further.",
            ),
            message_type="notification",
        )
