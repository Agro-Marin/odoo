from collections import Counter

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class HrEmployeeChangeRequest(models.Model):
    _name = "hr.employee.change.request"
    _description = "Employee Personal Information Change Request"
    _order = "create_date desc, id desc"
    _rec_name = "employee_id"

    _PROPOSED_FIELDS = (
        "private_street",
        "private_street2",
        "private_city",
        "private_state_id",
        "private_zip",
        "private_country_id",
        "private_email",
        "private_phone_ids",
        "emergency_contact",
        "emergency_phone_ids",
    )

    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        ondelete="cascade",
        index=True,
        default=lambda self: self.env.user.employee_id,
    )
    company_id = fields.Many2one(related="employee_id.company_id", store=True)
    state = fields.Selection(
        [("pending", "Pending"), ("approved", "Approved"), ("refused", "Refused")],
        default="pending",
        required=True,
        index=True,
    )
    requested_by_uid = fields.Many2one(
        "res.users", default=lambda self: self.env.user, readonly=True
    )
    reviewed_by_uid = fields.Many2one("res.users", readonly=True)
    reviewed_on = fields.Datetime(readonly=True)
    refusal_reason = fields.Char()

    private_street = fields.Char("Private Street")
    private_street2 = fields.Char("Private Street2")
    private_city = fields.Char("Private City")
    private_state_id = fields.Many2one("res.country.state", string="Private State")
    private_zip = fields.Char("Private Zip")
    private_country_id = fields.Many2one("res.country", string="Private Country")
    private_email = fields.Char("Private Email")
    private_phone_ids = fields.Many2many(
        "phone.number", "hr_change_request_private_phone_rel", string="Private Phone"
    )
    emergency_contact = fields.Char("Emergency Contact")
    emergency_phone_ids = fields.Many2many(
        "phone.number",
        "hr_change_request_emergency_phone_rel",
        string="Emergency Phone",
    )

    # A partial unique index would say this in SQL, but EXCLUDE needs
    # btree_gist and this template does not carry it.
    @api.constrains("employee_id", "state")
    def _check_one_pending_request_per_employee(self):
        pending = self.filtered(lambda request: request.state == "pending")
        if not pending:
            return
        # One query for the batch, and count the batch itself too: two pending
        # requests created together for one employee clash with each other and
        # neither is in the database yet to be found by the other.
        counts = Counter(pending.employee_id.ids)
        already = self.sudo().search(
            [
                ("employee_id", "in", pending.employee_id.ids),
                ("state", "=", "pending"),
                ("id", "not in", pending.ids),
            ]
        )
        counts.update(already.employee_id.ids)
        clashing = [employee_id for employee_id, seen in counts.items() if seen > 1]
        if clashing:
            raise ValidationError(
                self.env._(
                    "%(employee)s already has a change request awaiting review.",
                    employee=self.env["hr.employee"]
                    .sudo()
                    .browse(clashing[0])
                    .display_name,
                )
            )

    def _proposed_values(self):
        """The fields this request actually changes, as employee write values."""
        self.check_singleton()
        values = {}
        for fname in self._PROPOSED_FIELDS:
            field = self._fields[fname]
            proposed = self[fname]
            current = self.employee_id.sudo()[fname]
            if field.type == "many2many":
                if set(proposed.ids) != set(current.ids):
                    values[fname] = [Command.set(proposed.ids)]
            elif field.type == "many2one":
                if proposed.id != current.id:
                    values[fname] = proposed.id
            elif proposed != current:
                values[fname] = proposed
        return values

    def _check_reviewer(self):
        if not self.env.user.has_group("hr.group_hr_user"):
            raise AccessError(
                self.env._("Only an HR user may review a change request.")
            )

    def action_approve(self):
        self._check_reviewer()
        for request in self:
            if request.state != "pending":
                raise UserError(self.env._("Only a pending request can be approved."))
            values = request._proposed_values()
            if values:
                request.employee_id.sudo().write(values)
            request.write(
                {
                    "state": "approved",
                    "reviewed_by_uid": self.env.user.id,
                    "reviewed_on": fields.Datetime.now(),
                }
            )
        return True

    def action_refuse(self):
        self._check_reviewer()
        for request in self:
            if request.state != "pending":
                raise UserError(self.env._("Only a pending request can be refused."))
        return self.write(
            {
                "state": "refused",
                "reviewed_by_uid": self.env.user.id,
                "reviewed_on": fields.Datetime.now(),
            }
        )

    @api.model
    def action_open_my_request(self):
        """Open the caller's pending request, seeded from what they hold today."""
        employee = self.env.user.employee_id
        if not employee:
            raise UserError(
                self.env._("You have no employee record to raise a request about.")
            )
        request = self.search(
            [("employee_id", "=", employee.id), ("state", "=", "pending")], limit=1
        )
        if not request:
            seed = {"employee_id": employee.id}
            for fname in self._PROPOSED_FIELDS:
                value = employee.sudo()[fname]
                seed[fname] = (
                    [Command.set(value.ids)]
                    if self._fields[fname].type == "many2many"
                    else value.id
                    if self._fields[fname].type == "many2one"
                    else value
                )
            request = self.create(seed)
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": request.id,
            "view_mode": "form",
            "target": "new",
            "name": self.env._("Request a change to my information"),
        }
