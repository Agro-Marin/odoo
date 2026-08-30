from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    applicant_ids = fields.One2many(
        "hr.applicant", "employee_id", "Applicants", groups="hr.group_hr_user"
    )
    applicant_name = fields.Char(
        compute="_compute_applicant_name", groups="hr.group_hr_user"
    )

    @api.depends("applicant_ids.partner_name")
    def _compute_applicant_name(self):
        """Label the smart button: the candidate's name, or how many there are."""
        for employee in self:
            applicants = employee.applicant_ids
            employee.applicant_name = (
                applicants.partner_name
                if len(applicants) == 1
                else str(len(applicants))
            )

    def _get_partner_count_depends(self):
        return super()._get_partner_count_depends() + ["applicant_ids"]

    def _get_related_partners(self):
        partners = super()._get_related_partners()
        return partners | self.sudo().applicant_ids.partner_id

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        for employee_sudo in employees.sudo():
            if employee_sudo.applicant_ids:
                employee_sudo.applicant_ids._message_log_with_view(
                    "hr_recruitment.applicant_hired_template",
                    render_values={"applicant": employee_sudo.applicant_ids},
                )
        return employees

    def action_view_applicant(self):
        self.ensure_one()
        applicants = self.applicant_ids
        action = {
            "type": "ir.actions.act_window",
            "name": self.env._("Applicant"),
            "res_model": "hr.applicant",
        }
        if len(applicants) > 1:
            action["view_mode"] = "list,form"
            action["domain"] = [("id", "in", applicants.ids)]
        else:
            action["view_mode"] = "form"
            action["res_id"] = applicants.id
        return action
