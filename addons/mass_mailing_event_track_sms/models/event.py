# -*- coding: utf-8 -*-
from odoo import models


class EventEvent(models.Model):
    _inherit = "event.event"

    def action_mass_mailing_track_speakers(self):
        # Minimal override: set form view being the one mixing sms and mail (not prioritized one)
        action = super().action_mass_mailing_track_speakers()
        action['view_id'] = self.env.ref('mass_mailing_sms.mailing_mailing_view_form_mixed').id
        return action
