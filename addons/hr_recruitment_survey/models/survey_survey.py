from odoo import api, fields, models


class SurveySurvey(models.Model):
    _inherit = "survey.survey"

    survey_type = fields.Selection(
        selection_add=[("recruitment", "Recruitment")],
        ondelete={"recruitment": "set default"},
    )
    hr_job_ids = fields.One2many("hr.job", "survey_id", string="Job Position")
    job_count = fields.Integer(string="Job Count", compute="_compute_job_count")

    @api.depends_context("uid")
    def _compute_allowed_survey_types(self):
        super()._compute_allowed_survey_types()
        if self.env.user.has_group(
            "hr_recruitment.group_hr_recruitment_interviewer"
        ) or self.env.user.has_group("survey.group_survey_user"):
            self.allowed_survey_types = (self.allowed_survey_types or []) + [
                "recruitment"
            ]

    def _compute_job_count(self):
        job_data = self.env["hr.job"]._read_group(
            [("survey_id", "in", self.ids)],
            ["survey_id"],
            ["__count"],
        )
        result = {survey.id: count for survey, count in job_data}
        for survey in self:
            survey.job_count = result.get(survey.id, 0)

    def get_formview_id(self, access_uid=None):
        if self.survey_type == "recruitment":
            access_user = (
                self.env["res.users"].browse(access_uid)
                if access_uid
                else self.env.user
            )
            if not access_user.has_group("survey.group_survey_user"):
                if view := self.env.ref(
                    "hr_recruitment_survey.survey_survey_view_form",
                    raise_if_not_found=False,
                ):
                    return view.id
        return super().get_formview_id(access_uid=access_uid)

    def action_survey_user_input_completed(self):
        action = super().action_survey_user_input_completed()
        if self.survey_type == "recruitment":
            action.update({"domain": [("survey_id.survey_type", "=", "recruitment")]})
        return action

    def action_open_jobs(self):
        self.ensure_one()
        if self.job_count == 1:
            return {
                "name": self.env._("Job Position"),
                "type": "ir.actions.act_window",
                "res_model": "hr.job",
                "view_mode": "form",
                "res_id": self.hr_job_ids.id,
            }
        return {
            "name": self.env._("Job Positions"),
            "type": "ir.actions.act_window",
            "res_model": "hr.job",
            "view_mode": "list,kanban,form",
            "domain": [("id", "in", self.hr_job_ids.ids)],
        }
