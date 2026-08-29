from odoo import api, fields, models


class HrEmployeeCreateVersionWizard(models.TransientModel):
    _name = "hr.employee.create.version.wizard"
    _description = "Create a Version for Several Employees"

    def _default_employee_ids(self):
        # Same guard as hr.departure.wizard: a selection carried in the context
        # must not reach employees of a company the user is not working in.
        active_ids = self.env.context.get("active_ids", [])
        if not active_ids:
            return self.env["hr.employee"]
        return (
            self.env["hr.employee"]
            .browse(active_ids)
            .filtered(lambda employee: employee.company_id in self.env.companies)
        )

    employee_ids = fields.Many2many(
        "hr.employee", string="Employees", default=_default_employee_ids
    )
    employee_count = fields.Integer(compute="_compute_employee_count")
    date_version = fields.Date(string="Start Date", required=True)

    @api.depends("employee_ids")
    def _compute_employee_count(self):
        for wizard in self:
            wizard.employee_count = len(wizard.employee_ids)

    def action_create_versions(self):
        self.ensure_one()
        for employee in self.employee_ids:
            employee.create_version({"date_version": self.date_version})
        return {"type": "ir.actions.act_window_close"}
