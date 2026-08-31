from odoo import api, fields, models
from odoo.fields import Domain

_SKILL_COMMAND_FIELDS = frozenset({"current_job_skill_ids", "job_skill_ids"})


class HrJob(models.Model):
    _inherit = "hr.job"

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

    @api.depends("job_skill_ids")
    def _compute_current_job_skill_ids(self):
        for job in self:
            job.current_job_skill_ids = job.job_skill_ids.filtered(
                lambda skill: (
                    not skill.valid_to or skill.valid_to >= fields.Date.today()
                )
            )

    def _get_domain_for_current_job_skills(self, skill_domain):
        domain = Domain.AND(
            [
                Domain.OR(
                    [
                        Domain("valid_to", "=", False),
                        Domain("valid_to", ">=", fields.Date.today()),
                    ]
                ),
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

    @api.depends("job_skill_ids.skill_id", "job_skill_ids.valid_to")
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals_job_skill = vals.pop("current_job_skill_ids", []) + vals.get(
                "job_skill_ids", []
            )
            if vals_job_skill:
                vals["job_skill_ids"] = self.env[
                    "hr.job.skill"
                ]._get_transformed_commands(vals_job_skill, self.env["hr.job"])
            else:
                vals.pop("job_skill_ids", None)
        return super().create(vals_list)

    def write(self, vals):
        if not (_SKILL_COMMAND_FIELDS & vals.keys()):
            return super().write(vals)
        vals_job_skill = vals.pop("current_job_skill_ids", []) + vals.pop(
            "job_skill_ids", []
        )
        if len(self) > 1:
            result = super().write(vals) if vals else True
            for job in self:
                job.write(
                    {
                        "job_skill_ids": self.env[
                            "hr.job.skill"
                        ]._commands_for_individual(vals_job_skill, job)
                    }
                )
            return result
        vals["job_skill_ids"] = self.env["hr.job.skill"]._get_transformed_commands(
            vals_job_skill, self
        )
        return super().write(vals)
