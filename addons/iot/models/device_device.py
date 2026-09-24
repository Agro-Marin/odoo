from odoo import fields, models


class DeviceDevice(models.Model):
    _inherit = "device.device"

    iot_box_ids = fields.One2many(comodel_name="iot.box", inverse_name="device_id")
    iot_device_ids = fields.One2many(
        comodel_name="iot.device", inverse_name="device_id"
    )
