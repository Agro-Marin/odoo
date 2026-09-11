from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools.translate import _


def get_employee_from_context(values, context, user_employee_id):
    employee_ids_list = [
        value[2]
        for value in values.get("employee_ids", [])
        if len(value) == 3 and value[0] == Command.SET
    ]
    employee_ids = employee_ids_list[-1] if employee_ids_list else []
    employee_id_value = employee_ids[0] if employee_ids else False
    return employee_id_value or context.get(
        "default_employee_id", context.get("employee_id", user_employee_id)
    )


class MixinHrLeaveApproval(models.AbstractModel):
    _name = "mixin.hr.leave.approval"
    _inherit = ["mixin.approval"]
    _description = "Time Off Approval Workflow"

    can_approve = fields.Boolean(
        compute="_compute_approval_rights", export_string_translation=False
    )
    can_validate = fields.Boolean(
        compute="_compute_approval_rights", export_string_translation=False
    )
    can_refuse = fields.Boolean(
        compute="_compute_approval_rights", export_string_translation=False
    )

    @api.depends("state", "employee_id.leave_manager_id", "validation_type")
    @api.depends_context("uid")
    def _compute_approval_rights(self):
        if self.env.is_superuser():
            self.can_approve = self.can_validate = self.can_refuse = True
            return
        self.check_access("read")
        for record in self:
            next_states = record._get_next_states_by_state()
            record.can_approve = record._is_approval_update_allowed(
                "validate1", next_states
            )
            record.can_validate = record._is_approval_update_allowed(
                "validate", next_states
            )
            record.can_refuse = record._is_approval_update_allowed(
                "refuse", next_states
            )

    def _get_next_states_by_state(self):
        raise NotImplementedError

    def _get_approval_precheck_error(self, state):
        return ""

    def _get_approval_transition_error(self, state, is_time_off_manager):
        raise NotImplementedError

    def _approval_update_needs_write_access(self, state):
        return True

    def _get_approval_update_error(self, state, next_states):
        self.check_singleton()
        if self.state == state:
            return _("You can't do the same action twice.")
        if error := self._get_approval_precheck_error(state):
            return error
        if state not in next_states.get(self.state, ()):
            return self._get_approval_transition_error(
                state, self.employee_id.leave_manager_id == self.env.user
            )
        return ""

    def _is_approval_update_allowed(self, state, next_states):
        if self._get_approval_update_error(state, next_states):
            return False
        if not self._approval_update_needs_write_access(state):
            return True
        return self.has_access("write")

    def _check_approval_update(self, state, raise_if_not_possible=True):
        if self.env.is_superuser():
            return True
        self.check_access("read")
        for record in self:
            error = record._get_approval_update_error(
                state, record._get_next_states_by_state()
            )
            if error:
                if raise_if_not_possible:
                    raise UserError(error)
                return False
            if not record._approval_update_needs_write_access(state):
                continue
            try:
                record.check_access("write")
            except UserError:
                if raise_if_not_possible:
                    raise
                return False
        return True

    def _get_responsible_for_approval(self):
        self.check_singleton()
        responsible = self.env["res.users"]
        if self.validation_type == "manager" or (
            self.validation_type == "both" and self.state == "confirm"
        ):
            if self.employee_id.leave_manager_id:
                responsible = self.employee_id.leave_manager_id
            elif self.employee_id.parent_id.user_id:
                responsible = self.employee_id.parent_id.user_id
        elif self.validation_type == "hr" or (
            self.validation_type == "both" and self.state == "validate1"
        ):
            if self.holiday_status_id.responsible_ids:
                responsible = self.holiday_status_id.responsible_ids
        return responsible

    def _get_approval_activity_xmlids(self):
        raise NotImplementedError

    def _get_to_clean_activities(self):
        return list(self._get_approval_activity_xmlids())

    def _get_approval_activity_note(self):
        raise NotImplementedError

    def _get_approval_activity_deadline(self, activity_type):
        return False

    def activity_update(self):
        if self.env.context.get("mail_activity_automation_skip"):
            return
        records = self.filtered(lambda record: not record.sudo().approval_request_id)
        if not records:
            return
        confirm_xmlid, second_xmlid = self._get_approval_activity_xmlids()
        confirm_activity = self.env.ref(confirm_xmlid)
        second_activity = self.env.ref(second_xmlid)
        to_clean = to_do = to_do_second = self.browse()
        activity_vals = []
        model_id = self.env["ir.model"]._get_id(self._name)
        for record in records:
            if record.state in ("confirm", "validate1"):
                if record.validation_type == "no_validation":
                    continue
                if record.state == "confirm":
                    activity_type = confirm_activity
                else:
                    activity_type = second_activity
                    to_do_second |= record
                note = record._get_approval_activity_note()
                deadline = record._get_approval_activity_deadline(activity_type)
                for user_id in record.sudo()._get_responsible_for_approval().ids:
                    vals = {
                        "activity_type_id": activity_type.id,
                        "automated": True,
                        "note": note,
                        "user_id": user_id,
                        "res_id": record.id,
                        "res_model_id": model_id,
                    }
                    if deadline:
                        vals["date_deadline"] = deadline
                    activity_vals.append(vals)
            elif record.state == "validate":
                to_do |= record
            elif record.state in ("refuse", "cancel"):
                to_clean |= record
        if to_clean:
            to_clean.activity_unlink(
                self._get_to_clean_activities(), only_automated=False
            )
        if to_do_second:
            to_do_second.activity_feedback([confirm_xmlid])
        if to_do:
            to_do.activity_feedback([confirm_xmlid, second_xmlid])
        if activity_vals:
            self.env["mail.activity"].with_context(short_name=False).create(
                activity_vals
            )

    def add_follower(self, employee_id):
        employee = self.env["hr.employee"].browse(employee_id)
        if employee.user_id:
            self.message_subscribe(partner_ids=employee.user_id.partner_id.ids)

    def _get_approval_sudo_subscribe_states(self):
        return ("validate",)

    def message_subscribe(self, partner_ids=None, subtype_ids=None):
        sudo_states = self._get_approval_sudo_subscribe_states()
        if any(record.state in sudo_states for record in self):
            self.check_access("read")
            return super(MixinHrLeaveApproval, self.sudo()).message_subscribe(
                partner_ids=partner_ids, subtype_ids=subtype_ids
            )
        return super().message_subscribe(
            partner_ids=partner_ids, subtype_ids=subtype_ids
        )

    def _get_validated_notif_subtype(self):
        raise NotImplementedError

    def _track_subtype(self, init_values):
        if "state" in init_values and self.state == "validate":
            return self._get_validated_notif_subtype()
        return super()._track_subtype(init_values)

    def onchange(self, values, field_names, fields_spec):
        if (
            values
            and "employee_id" in fields_spec
            and "employee_id" not in self.env.context
        ):
            employee_id = get_employee_from_context(
                values, self.env.context, self.env.user.employee_id.id
            )
            self = self.with_context(employee_id=employee_id)
        return super().onchange(values, field_names, fields_spec)

    def _get_redirect_suggested_company(self):
        return self.holiday_status_id.company_id

    def write(self, vals):
        if "state" not in vals:
            return super().write(vals)
        synced = self.env.context.get("hr_holidays_approval_sync", ())
        previous_states = {
            record.id: record.state
            for record in self.sudo()
            if record.approval_request_id
            and record.approval_request_id.id not in synced
        }
        result = super().write(vals)
        if previous_states:
            self.filtered(
                lambda record: (
                    record.id in previous_states
                    and record.state != previous_states[record.id]
                )
            )._sync_approval_request()
        return result

    def unlink(self):
        for record in self.sudo().filtered(
            lambda record: record.approval_request_id.state == "pending"
        ):
            record._get_synced_approval_request()._force_terminal(
                "cancelled",
                self.env._(
                    "%(user)s deleted %(record)s.",
                    user=self.env.user.name,
                    record=record.display_name,
                ),
            )
        return super().unlink()

    def _get_approval_category_xmlid(self):
        raise NotImplementedError

    def _get_domain_approval_category(self):
        category = self.env.ref(
            self._get_approval_category_xmlid(), raise_if_not_found=False
        )
        return [("id", "=", category.id)] if category else []

    def _prepare_approval_request_values(self, category):
        vals = super()._prepare_approval_request_values(category)
        vals["request_owner_id"] = (self.employee_id.user_id or self.env.user).id
        return vals

    def _create_approval_requests(self):
        # The superuser is the system: what it creates (crons, fast paths) keeps the
        # direct flow. A user's sudo() keeps their uid, so it still raises a request.
        if self.env.uid == SUPERUSER_ID or self.env.context.get("import_file"):
            return
        for record in self.sudo():
            if (
                record.state == "confirm"
                and record.validation_type != "no_validation"
                and not record.approval_request_id
                and record.approval_required
            ):
                record.action_create_approval_request()

    def _get_synced_approval_request(self):
        self.check_singleton()
        request = self.sudo().approval_request_id
        synced = self.env.context.get("hr_holidays_approval_sync", ())
        return request.with_context(hr_holidays_approval_sync=(*synced, request.id))

    def _is_synced_with_approval_request(self):
        self.check_singleton()
        return self.approval_request_id.id in self.env.context.get(
            "hr_holidays_approval_sync", ()
        )

    def _restart_approval_request(self, request):
        if request.state != "new":
            request._force_draft()
        request.action_confirm()

    def _sync_approval_request(self):
        user = self.env.user
        decides = self.env.uid != SUPERUSER_ID
        for record in self:
            request = record._get_synced_approval_request()
            if record.state == "confirm":
                record._restart_approval_request(request)
            elif record.state in ("validate1", "validate"):
                record._sync_approval_request_approval(request, user, decides)
            elif record.state in ("refuse", "cancel"):
                record._sync_approval_request_ending(request, user, decides)

    def _sync_approval_request_approval(self, request, user, decides):
        self.check_singleton()
        if request.state in ("new", "refused", "cancelled"):
            self._restart_approval_request(request)
        if request.state != "pending":
            return
        rows = (
            request._get_rows_decidable_by(user)
            if decides
            else request.approver_ids.browse()
        )
        if self.state == "validate1":
            steps = request._get_open_steps()
            rows = rows.filtered(lambda row: steps <= row.step_ids)
            if rows:
                request.action_approve(approver=rows, steps=steps)
            return
        if rows:
            request.action_approve(approver=rows)
        if request.state == "pending":
            request._approve_without_decision(
                self.env._(
                    "%(user)s validated %(record)s without an approver's decision.",
                    user=user.name,
                    record=self.display_name,
                )
            )

    def _sync_approval_request_ending(self, request, user, decides):
        self.check_singleton()
        refused = self.state == "refuse"
        if request.state == "approved":
            request._revoke(
                "refused" if refused else "cancelled",
                self.env._(
                    "%(user)s refused %(record)s after it was approved.",
                    user=user.name,
                    record=self.display_name,
                )
                if refused
                else self.env._(
                    "%(user)s cancelled %(record)s after it was approved.",
                    user=user.name,
                    record=self.display_name,
                ),
            )
            return
        if request.state not in ("new", "pending"):
            return
        rows = (
            request._get_current_pending_approver(user)
            if decides and refused and request.state == "pending"
            else request.approver_ids.browse()
        )
        if rows:
            request.action_refuse(approver=rows)
            return
        request._force_terminal(
            "refused" if refused else "cancelled",
            self.env._(
                "%(user)s refused %(record)s.", user=user.name, record=self.display_name
            )
            if refused
            else self.env._(
                "%(user)s cancelled %(record)s.",
                user=user.name,
                record=self.display_name,
            ),
        )

    def _get_approval_cancelled_state(self):
        raise NotImplementedError

    def _apply_approval_state(self, state):
        raise NotImplementedError

    def _apply_approval_outcome(self, state, decided=True):
        self.check_singleton()
        if decided and self.env.uid != SUPERUSER_ID:
            self.sudo(False)._check_approval_update(state)
        synced = self.env.context.get("hr_holidays_approval_sync", ())
        self.with_context(
            hr_holidays_approval_sync=(*synced, self.approval_request_id.id)
        )._apply_approval_state(state)

    def _on_approval_progress(self):
        if not self._is_synced_with_approval_request() and self.state == "confirm":
            self._apply_approval_outcome("validate1")

    def _on_approval_approved(self):
        if not self._is_synced_with_approval_request() and self.state != "validate":
            self._apply_approval_outcome("validate")

    def _on_approval_refused(self):
        if not self._is_synced_with_approval_request() and self.state != "refuse":
            self._apply_approval_outcome("refuse")

    def _on_approval_cancelled(self):
        state = self._get_approval_cancelled_state()
        if not self._is_synced_with_approval_request() and self.state != state:
            self._apply_approval_outcome(state, decided=False)

    def _on_approval_reset(self):
        if not self._is_synced_with_approval_request():
            super()._on_approval_reset()

    def _on_approval_revoked(self):
        if not self._is_synced_with_approval_request():
            super()._on_approval_revoked()
