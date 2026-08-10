# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import UTC, datetime, time

from odoo import fields, models
from odoo.libs.datetime import timezone


class MailActivityTodoCreate(models.TransientModel):
    _name = 'mail.activity.todo.create'
    _description = 'Create activity and todo at the same time'

    summary = fields.Char()
    date_deadline = fields.Date('Due Date', required=True, default=fields.Date.context_today)
    user_id = fields.Many2one('res.users', 'Assigned to', default=lambda self: self.env.user, required=True, readonly=True)
    note = fields.Html(sanitize_style=True)

    def _deadline_as_datetime(self):
        """Return ``date_deadline`` as the end of that day, in UTC.

        ``project.task.date_end`` is a Datetime while this wizard collects a
        Date. Handing the Date straight over stores naive UTC midnight, which
        renders as the *previous* evening for every user west of UTC — a to-do
        due "Aug 10" shows up as "Yesterday". Anchor it to the end of the
        picked day in the user's own timezone instead, so the deadline reads
        back as the day the user chose and does not fall due at 00:01.

        :rtype: datetime
        """
        self.ensure_one()
        tz = timezone(self.env.user.tz or 'UTC')
        local_end_of_day = datetime.combine(self.date_deadline, time.max, tzinfo=tz)
        return local_end_of_day.astimezone(UTC).replace(tzinfo=None, microsecond=0)

    def create_todo_activity(self):
        self.ensure_one()
        todo = self.env['project.task'].create({
            'name': self.summary,
            'description': self.note,
            'date_end': self._deadline_as_datetime(),
            'user_ids': self.user_id.ids,
        })
        self.env['mail.activity'].create({
            'res_model_id': self.env['ir.model']._get('project.task').id,
            'res_id': todo.id,
            'summary': self.summary,
            'user_id': self.user_id.id,
            'date_deadline': self.date_deadline,
            'activity_type_id': self.env['mail.activity']._default_activity_type_for_model('project.task').id,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': self.env._("Your to-do has been successfully added to your pipeline."),
            },
        }
