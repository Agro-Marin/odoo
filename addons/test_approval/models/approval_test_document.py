from typing import Any

from odoo import fields, models


class ApprovalTestDocument(models.Model):
    _name = "approval.test.document"
    _description = "Test Document for Approval Mixin"
    _inherit = ["mixin.mail.thread", "mixin.approval"]

    name = fields.Char(required=True, tracking=True)
    description = fields.Text()
    amount = fields.Float(tracking=True)
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    amount_total = fields.Monetary(currency_field="currency_id")
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="draft",
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self.env.company,
    )
    hook_call_count = fields.Integer(
        default=0,
        help="Tracks how many times _on_approval_state_changed was called",
    )
    last_approval_state = fields.Char(
        help="Records the last state received by _on_approval_state_changed",
    )
    test_category_id = fields.Many2one(
        comodel_name="approval.category",
        help="Category to use for approval (for testing)",
    )

    def _get_domain_approval_category(self) -> list[Any]:
        if self.test_category_id:
            return [("id", "=", self.test_category_id.id)]
        return []

    def _get_fields_approval_required(self) -> list[str]:
        return ["name", "partner_id"]

    def _get_approval_request_name(self) -> str:
        return f"Test Document Approval: {self.name}"

    def _on_approval_state_changed(self, new_state: str) -> None:
        self.sudo().write(
            {
                "hook_call_count": self.hook_call_count + 1,
                "last_approval_state": new_state,
            }
        )

        if new_state == "approved":
            self.sudo().state = "approved"
        elif new_state == "refused":
            self.sudo().state = "rejected"

        super()._on_approval_state_changed(new_state)
