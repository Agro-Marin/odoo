from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    delay_alert_contract = fields.Integer(
        string="Delay alert contract outdated",
        default=30,
        config_parameter="hr_fleet.delay_alert_contract",
    )
