from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain


class HrApplicant(models.Model):
    _inherit = "hr.applicant"

    survey_id = fields.Many2one(
        "survey.survey", related="job_id.survey_id", string="Survey", readonly=True
    )
    response_ids = fields.One2many(
        "survey.user_input", "applicant_id", string="Responses"
    )

    def _expire_interview_links(self):
        """Close the interviews still open for these applications.

        An interview link stays usable until its answer's deadline, so the events
        that end an application have to bring that deadline forward to now.
        Answers reach us either through ``applicant_id`` -- set by our own
        ``survey.invite`` override -- or, when the base wizard created them, only
        through the contact plus the job's survey. Both are matched, and nothing
        else of that contact's is touched.
        """
        answers = self.env["survey.user_input"].search(
            Domain("state", "!=", "done")
            & (
                Domain("applicant_id", "in", self.ids)
                | (
                    Domain("partner_id", "in", self.partner_id.ids)
                    & Domain("survey_id", "in", self.survey_id.ids)
                )
            )
        )
        # A recruitment officer only reads survey.user_input, see
        # security/ir.model.access.csv, so closing the deadline needs sudo. One
        # second back, not now: the controller compares deadline < now and both
        # sides are truncated to the second, so a deadline of now would leave the
        # link usable for the rest of that second.
        answers.sudo().deadline = fields.Datetime.now() - timedelta(seconds=1)

    def write(self, vals):
        res = super().write(vals)
        hired = self.env["hr.recruitment.stage"].browse(vals.get("stage_id"))
        if vals.get("active") is False or hired.hired_stage:
            self._expire_interview_links()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_expire_interview_links(self):
        self._expire_interview_links()

    def action_print_survey(self):
        """If response is available then print this response otherwise print survey form (print template of the survey)"""
        self.ensure_one()
        sorted_interviews = self.response_ids.filtered(
            lambda i: i.survey_id == self.survey_id
        ).sorted(lambda i: i.create_date, reverse=True)
        if not sorted_interviews:
            action = self.survey_id.action_print_survey()
            action["target"] = "new"
            return action

        answered_interviews = sorted_interviews.filtered(lambda i: i.state == "done")
        if answered_interviews:
            action = self.survey_id.action_print_survey(answer=answered_interviews[0])
            action["target"] = "new"
            return action
        action = self.survey_id.action_print_survey(answer=sorted_interviews[0])
        action["target"] = "new"
        return action

    def action_send_survey(self):
        self.ensure_one()

        # if an applicant does not already have an associated partner_id, create it
        if not self.partner_id:
            if not self.partner_name:
                raise UserError(_("Please provide an applicant name."))
            self.partner_id = (
                self.env["res.partner"]
                .sudo()
                .create(
                    {
                        "is_company": False,
                        "name": self.partner_name,
                        "email": self.email_from,
                        "phone": self.partner_phone,
                    }
                )
            )

        self.survey_id.check_validity()
        template = self.env.ref(
            "hr_recruitment_survey.mail_template_applicant_interview_invite",
            raise_if_not_found=False,
        )
        local_context = {
            "default_applicant_id": self.id,
            "default_partner_ids": self.partner_id.ids,
            "default_survey_id": self.survey_id.id,
            "default_use_template": bool(template),
            "default_template_id": (template and template.id) or False,
            "default_email_layout_xmlid": "mail.mail_notification_light",
            "default_deadline": fields.Datetime.now() + timedelta(days=15),
        }

        return {
            "type": "ir.actions.act_window",
            "name": _("Send an interview"),
            "view_mode": "form",
            "res_model": "survey.invite",
            "target": "new",
            "context": local_context,
        }
