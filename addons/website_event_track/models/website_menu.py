from odoo import models


class WebsiteMenu(models.Model):
    _inherit = "website.menu"

    def unlink(self):
        event_updates = {}
        website_event_menus = self.env["website.event.menu"].search(
            [("menu_id", "in", self.ids)]
        )
        for event_menu in website_event_menus:
            to_update = event_updates.setdefault(event_menu.event_id, [])
            if event_menu.menu_type == "track" and "/track" in event_menu.menu_id.url:
                to_update.append("website_track")

        res = super().unlink()

        for event, to_update in event_updates.items():
            if to_update:
                event.write(dict.fromkeys(to_update, False))

        return res
