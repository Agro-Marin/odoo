from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_APPROVAL_LOCK_EXEMPT_FIELDS = frozenset({"s3_blob_name", "s3_mirror_pending"})


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    approval_requirement_id = fields.Many2one(
        comodel_name="approval.document.requirement",
        string="Satisfies Requirement",
        ondelete="set null",
        index="btree_not_null",
        help="Which of the category's required documents this file IS. The "
        "requester says so; nothing infers it. Before this column the "
        "confirm-time check ran a bipartite matching over file NAMES, "
        "which cannot express the invariant it was asked to enforce: a "
        "file called 'holiday-photo-not-an-invoice.png' satisfied a "
        "requirement named 'Invoice', and a genuine invoice scanned to "
        "'scan001.pdf' did not.",
    )

    @api.constrains("approval_requirement_id", "res_model", "res_id")
    def _check_approval_requirement_belongs_to_the_request(self) -> None:
        for attachment in self.filtered("approval_requirement_id"):
            if attachment.res_model != "approval.request" or not attachment.res_id:
                raise ValidationError(
                    self.env._(
                        "Only a file attached to an approval request can "
                        "satisfy one of its document requirements.",
                    ),
                )
            request = self.env["approval.request"].sudo().browse(attachment.res_id)
            if attachment.approval_requirement_id.category_id != request.category_id:
                raise ValidationError(
                    self.env._(
                        "'%(requirement)s' is a document requirement of "
                        "category '%(other)s', not of this request's "
                        "category '%(category)s'.",
                        requirement=attachment.approval_requirement_id.name,
                        other=attachment.approval_requirement_id.category_id.name,
                        category=request.category_id.name,
                    ),
                )

    def _approval_terminal_parent_ids(self, request_ids):
        if not request_ids:
            return set()
        terminal = self.env["approval.request"]._TERMINAL_STATES
        requests = self.env["approval.request"].sudo().browse(list(request_ids))
        return {r.id for r in requests if r.exists() and r.state in terminal}

    def _approval_res_field_is_real(self, res_model, res_field) -> bool:
        if not res_field:
            return False
        model = self.env.get(res_model)
        if model is None:
            return False
        field = model._fields.get(res_field)
        return bool(
            field
            and field.type == "binary"
            and field.store
            and getattr(field, "attachment", False)
        )

    def _approval_attachments_in_self(self):
        if not self:
            return self.browse()
        return self.sudo().filtered(
            lambda a: (
                a.res_model == "approval.request"
                and not self._approval_res_field_is_real(a.res_model, a.res_field)
            ),
        )

    @api.model_create_multi
    def create(self, vals_list):
        candidate_ids = {
            vals.get("res_id")
            for vals in vals_list
            if vals.get("res_model") == "approval.request"
            and not self._approval_res_field_is_real(
                vals.get("res_model"),
                vals.get("res_field"),
            )
            and vals.get("res_id")
        }
        if self._approval_terminal_parent_ids(candidate_ids):
            raise UserError(
                self.env._(
                    "You cannot attach a document to an approval request "
                    "that has been approved, refused or cancelled.",
                ),
            )
        return super().create(vals_list)

    def write(self, vals):
        if vals and vals.keys() <= _APPROVAL_LOCK_EXEMPT_FIELDS:
            return super().write(vals)
        targeted = self._approval_attachments_in_self()
        blocked_ids = set(targeted.mapped("res_id"))
        if {"res_model", "res_id", "res_field"} & vals.keys():
            for att in self.sudo():
                new_model = vals.get("res_model", att.res_model)
                new_id = vals.get("res_id", att.res_id)
                new_field = vals.get("res_field", att.res_field)
                if (
                    new_model == "approval.request"
                    and new_id
                    and not self._approval_res_field_is_real(new_model, new_field)
                ):
                    blocked_ids.add(new_id)
        if self._approval_terminal_parent_ids(blocked_ids):
            raise UserError(
                self.env._(
                    "You cannot modify an attachment linked to an approval "
                    "request that has been approved, refused or cancelled.",
                ),
            )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_approved_approval_request(self):
        targeted = self._approval_attachments_in_self()
        if targeted and self._approval_terminal_parent_ids(targeted.mapped("res_id")):
            raise UserError(
                self.env._(
                    "You cannot unlink an attachment which is linked to an "
                    "approved, refused or cancelled approval request.",
                ),
            )
