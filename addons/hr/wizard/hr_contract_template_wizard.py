# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class HrContractTemplateWizard(models.TransientModel):
    _name = "hr.version.wizard"
    _description = "Contract Template Wizard"

    contract_template_id = fields.Many2one(
        "hr.version",
        string="Contract Template",
        groups="hr.group_hr_user",
        required=True,
        domain=lambda self: [
            ("company_id", "=", self.env.company.id),
            ("employee_id", "=", False),
        ],
        help="Select a contract template to auto-fill the contract form with predefined values. You can still edit the fields as needed after applying the template.",
    )

    def action_load_template(self):
        self.ensure_one()
        employee_id = self.env.context.get("active_id")
        if not employee_id or not self.contract_template_id:
            return
        employee = self.env["hr.employee"].browse(employee_id)
        # Reuse the single source of truth (applies the template's company context
        # and sudo's the restricted-field read) instead of re-deriving it here.
        val_list = self.env["hr.version"].get_values_from_contract_template(
            self.contract_template_id
        )
        employee.write(val_list)
        employee.version_id.contract_template_id = self.contract_template_id
        return
