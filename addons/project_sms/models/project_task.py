# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models


class ProjectTask(models.Model):
    _name = 'project.task'
    _inherit = "project.task"

    def _send_sms(self):
        for task in self:
            if task.partner_id and task.step_id and task.step_id.sms_template_id and not task.is_template:
                task._message_sms_with_template(
                    template=task.step_id.sms_template_id,
                    partner_ids=task.partner_id.ids,
                )

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        tasks._send_sms()
        return tasks

    def write(self, vals):
        res = super().write(vals)

        if 'step_id' in vals:
            # sudo as sms template model is protected
            self.sudo()._send_sms()
        return res
