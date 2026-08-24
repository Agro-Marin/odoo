from odoo.addons.website_event.controllers.main import WebsiteEventController


class EventOnlineController(WebsiteEventController):
    def _get_registration_confirm_values(self, event, attendees_sudo):
        values = super()._get_registration_confirm_values(event, attendees_sudo)
        values["hide_sponsors"] = True
        return values
