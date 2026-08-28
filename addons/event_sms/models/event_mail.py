from odoo import models


class EventMail(models.Model):
    _inherit = 'event.mail'

    def _execute_event_based_for_registrations(self, registrations):
        if self.notification_type == "sms":
            self._send_sms(registrations)
        return super()._execute_event_based_for_registrations(registrations)

    def _send_sms(self, registrations):
        """ SMS action: send SMS to attendees """
        registrations._message_sms_schedule_mass(
            template=self.template_ref,
            mass_keep_log=True
        )
