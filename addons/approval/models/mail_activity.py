from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

from odoo.addons.mail.tools.discuss import Store


class MailActivity(models.Model):
    _inherit = "mail.activity"

    approval_request_id = fields.Many2one(
        comodel_name="approval.request",
        compute="_compute_approval_request_id",
        search="_search_approval_request_id",
    )
    approver_id = fields.Many2one(
        comodel_name="approval.approver",
        compute="_compute_approver_id",
    )

    @api.depends("activity_type_id", "res_id", "res_model")
    def _compute_approval_request_id(self):
        activity_type_approval_id = self.env.ref(
            "approval.mail_activity_data_approval",
        )
        for activity in self:
            if (
                activity.res_model == "approval.request"
                and activity.activity_type_id == activity_type_approval_id
            ):
                activity.approval_request_id = self.env["approval.request"].browse(
                    activity.res_id,
                )
            else:
                activity.approval_request_id = None

    @api.depends(
        "user_id",
        "approval_request_id.approver_ids.user_id",
        "approval_request_id.approver_ids.delegate_id",
    )
    def _compute_approver_id(self):
        for activity in self:
            activity.approver_id = activity.approval_request_id.approver_ids.filtered(
                lambda approver, a=activity: (
                    a.user_id == approver._get_effective_approver()
                ),
            )[:1]

    def _search_approval_request_id(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            raise UserError(
                self.env._(
                    "Negative operators (%(operator)s) are not supported for "
                    "searching by approval_request_id. Use positive operators instead.",
                    operator=operator,
                )
            )
        if operator == "any":
            operator = "in"
            if isinstance(value, Domain):
                value = self.env["approval.request"]._search(value)
        activity_type_approval_id = self.env.ref(
            "approval.mail_activity_data_approval",
        )
        return [
            ("res_model", "=", "approval.request"),
            ("activity_type_id", "=", activity_type_approval_id.id),
            ("res_id", operator, value),
        ]

    def _to_store_defaults(self, target):
        return super()._to_store_defaults(target) + [
            Store.One("approver_id", ["state"]),
        ]
