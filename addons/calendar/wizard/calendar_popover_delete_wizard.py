# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class CalendarPopoverDeleteWizard(models.TransientModel):
    _name = 'calendar.popover.delete.wizard'
    _inherit = ['mail.composer.mixin']
    _description = 'Calendar Popover Delete Wizard'

    calendar_event_id = fields.Many2one('calendar.event', 'Calendar Event')
    delete = fields.Selection([('one', 'Delete this event'), ('next', 'Delete this and following events'), ('all', 'Delete all the events')], default='one')
    recipient_ids = fields.Many2many(
        'res.partner',
        string="Recipients",
        compute='_compute_recipient_ids',
        readonly=False,
    )

    def close(self):
        # Return if there are multiple attendees or if the organizer's partner_id differs
        if self.calendar_event_id.attendees_count != 1 or self.calendar_event_id.user_id.partner_id != self.calendar_event_id.partner_ids:
            return self.calendar_event_id.action_unlink_event(self.delete)
        self.calendar_event_id._unlink_by_recurrence_policy(self.delete)
        return None

    @api.depends('calendar_event_id')
    def _compute_recipient_ids(self):
        """ Compute the recipients by combining the record's partner and attendees partners. """
        for wizard in self:
            wizard.recipient_ids = wizard.calendar_event_id.partner_id | wizard.calendar_event_id.attendee_ids.partner_id

    @api.depends('calendar_event_id')
    def _compute_subject(self):
        """ Compute the subject by rendering the template's subject field based on the event. """
        for wizard in self.filtered('template_id'):
            wizard.subject = wizard.template_id._render_field(
                'subject',
                [wizard.calendar_event_id.id],
                compute_lang=True,
                options={'post_process': True},
            )[wizard.calendar_event_id.id]

    @api.depends('calendar_event_id')
    def _compute_body(self):
        """ Compute the body by rendering the template's body HTML field based on the event. """
        for wizard in self.filtered('template_id'):
            wizard.body = wizard.template_id._render_field(
                'body_html',
                [wizard.calendar_event_id.id],
                compute_lang=True,
                options={'post_process': True},
            )[wizard.calendar_event_id.id]

    def action_delete(self):
        """
        Delete the event based on the specified deletion type.

        :return: Action URL to redirect to the calendar view
        """
        self.ensure_one()
        # The policy reaches this wizard in either vocabulary -- its own
        # 'one'/'next'/'all' from the popover view, or `recurrence_update`'s
        # 'self_only'/'future_events'/'all_events' from the calendar form
        # through action_unlink_event. `_unlink_by_recurrence_policy` accepts
        # both; before it existed, only 'next'/'all' triggered a mass deletion,
        # so "this and following" and "all events" from the form deleted nothing.
        self.calendar_event_id._unlink_by_recurrence_policy(
            self.env.context.get('default_recurrence')
        )

        return {
            'type': 'ir.actions.act_url',
            'target': 'self',
            'url': '/odoo/calendar'
        }

    def action_send_mail_and_delete(self):
        """ Send email notification and delete the event based on the specified deletion type. """
        self.env.ref('calendar.calendar_template_delete_event').send_mail(
            self.calendar_event_id.id, email_layout_xmlid='mail.mail_notification_light', force_send=True
        )
        return self.action_delete()
