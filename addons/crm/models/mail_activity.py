from odoo import models


class MailActivity(models.Model):
    _inherit = "mail.activity"

    def action_create_calendar_event(self):
        action = super().action_create_calendar_event()
        opportunity = self.calendar_event_id.opportunity_id
        if opportunity:
            opportunity_action_context = opportunity.action_schedule_meeting(
                smart_calendar=False
            ).get("context", {})
            opportunity_action_context["initial_date"] = self.calendar_event_id.start

            action["context"].update(opportunity_action_context)

        return action
