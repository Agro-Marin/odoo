from odoo import models


class ChatbotScriptStep(models.Model):
    _inherit = "chatbot.script.step"

    def _chatbot_prepare_customer_values(
        self, discuss_channel, create_partner=True, update_partner=True
    ):
        values = super()._chatbot_prepare_customer_values(
            discuss_channel, create_partner, update_partner
        )
        if visitor_sudo := discuss_channel.livechat_visitor_id.sudo():
            if not values.get("email") and visitor_sudo.email:
                values["email"] = visitor_sudo.email
            if not values.get("phone") and visitor_sudo.partner_id.phone_ids:
                values["phone"] = visitor_sudo.partner_id.phone_ids._primary(
                    "mobile"
                ).number
            values["country"] = (
                {"id": visitor_sudo.country_id} if visitor_sudo.country_id else False
            )

        return values
