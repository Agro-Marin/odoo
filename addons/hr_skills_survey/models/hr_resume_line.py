# Part of Odoo. See LICENSE file for full copyright and licensing details.

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class HrResumeLine(models.Model):
    _inherit = "hr.resume.line"

    department_id = fields.Many2one(related="employee_id.department_id", store=True)
    survey_id = fields.Many2one("survey.survey", string="Certification", readonly=True)
    expiration_status = fields.Selection(
        [("expired", "Expired"), ("expiring", "Expiring"), ("valid", "Valid")],
        compute="_compute_expiration_status",
        store=True,
    )

    @api.depends("date_end")
    def _compute_expiration_status(self):
        self.expiration_status = "valid"
        for line in self:
            if line.date_end:
                if line.date_end <= fields.Date.today():
                    line.expiration_status = "expired"
                elif line.date_end + relativedelta(months=-3) <= fields.Date.today():
                    line.expiration_status = "expiring"

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        return [
            dict(vals, name=self.env._("%s (copy)", resume_line.name))
            for resume_line, vals in zip(self, vals_list, strict=True)
        ]

    def copy_translations(self, new, excluded=()):
        # ``copy_data`` renames ``name`` in the duplicating user's language
        # only; without this the copy would keep the source record's exact
        # ``name`` in every other language.
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record.env._("%s (copy)", term)
        )
