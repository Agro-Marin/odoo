from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    hr_recruitment_config_id = fields.Many2one(
        comodel_name="hr_recruitment.config",
        compute="_compute_hr_recruitment_config_id",
        search="_search_hr_recruitment_config_id",
    )

    # fields.Properties resolves its `definition` as one hop and one field, so
    # hr.job cannot reach the configuration through the link: the company
    # declares the definition and the configuration stores it
    job_properties_definition = fields.PropertiesDefinition(
        related="hr_recruitment_config_id.job_properties_definition",
        readonly=False,
    )

    def _search_hr_recruitment_config_id(self, operator, value):
        return self._search_config_link("hr_recruitment.config", operator, value)

    def _compute_hr_recruitment_config_id(self):
        self._compute_config_link("hr_recruitment_config_id")
