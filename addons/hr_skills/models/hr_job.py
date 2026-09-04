from odoo import api, fields, models
from odoo.fields import Domain


class HrJob(models.Model):
    _inherit = ["mixin.hr.individual.skill.owner", "hr.job"]

    job_skill_ids = fields.One2many(
        comodel_name="hr.job.skill",
        inverse_name="job_id",
        string="Skills",
        domain=[("skill_type_id.active", "=", True)],
    )
    current_job_skill_ids = fields.One2many(
        comodel_name="hr.job.skill",
        compute="_compute_current_job_skill_ids",
        search="_search_current_job_skill_ids",
        readonly=False,
    )
    skill_ids = fields.Many2many(
        comodel_name="hr.skill",
        compute="_compute_skill_ids",
        search="_search_skill_ids",
    )

    def _individual_skill_field_name(self):
        return "job_skill_ids"

    def _individual_skill_command_field_names(self):
        return ("current_job_skill_ids", "job_skill_ids")

    @api.depends("job_skill_ids.valid_to", "job_skill_ids.skill_id")
    def _compute_current_job_skill_ids(self):
        current_by_job = self.job_skill_ids._current_individual_skills().grouped(
            "job_id"
        )
        for job in self:
            job.current_job_skill_ids = current_by_job.get(
                job, self.env["hr.job.skill"]
            )

    def _get_domain_for_current_job_skills(self, skill_domain):
        domain = Domain.AND(
            [
                self.env["hr.job.skill"]._validity_domain(fields.Date.today()),
                skill_domain,
            ]
        )
        job_skill_ids = self.env["hr.job.skill"]._search(domain)
        return Domain("job_skill_ids", "in", job_skill_ids)

    def _search_current_job_skill_ids(self, operator, value):
        if operator not in ("in", "not in", "any"):
            raise NotImplementedError
        if operator == "any" and isinstance(value, Domain):
            skill_domain = value
        else:
            skill_domain = Domain("id", "in", value)
        result = self._get_domain_for_current_job_skills(skill_domain)
        return ~result if operator == "not in" else result

    @api.depends("job_skill_ids.valid_to", "job_skill_ids.skill_id")
    def _compute_skill_ids(self):
        for job in self:
            job.skill_ids = job.current_job_skill_ids.skill_id

    def _search_skill_ids(self, operator, value):
        if operator not in ("in", "not in"):
            raise NotImplementedError
        result = self._get_domain_for_current_job_skills(
            Domain("skill_id", "in", value)
        )
        return ~result if operator == "not in" else result
