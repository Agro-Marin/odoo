from odoo import fields, models


class ResUsersSettings(models.Model):
    _inherit = "res.users.settings"

    voice_notice_acknowledged = fields.Boolean(
        string="Voice Notice Acknowledged",
        help="The user has read what the microphone hears and where it is "
        "processed, which is shown before it first listens.",
    )
