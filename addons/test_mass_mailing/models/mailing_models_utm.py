# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class UtmTestSourceMixin(models.Model):
    """ Test mixin.utm.source """
    _name = 'utm.test.source.mixin'
    _description = "UTM Source Mixin Test Model"
    _order = "id DESC"
    _rec_name = "title"
    _inherit = [
        "mixin.utm.source",
    ]

    name = fields.Char(inherited=True)
    title = fields.Char()


class UtmTestSourceMixinOther(models.Model):
    """ Test mixin.utm.source, similar to the other one, allowing also to test
    cross model uniqueness check """
    _name = 'utm.test.source.mixin.other'
    _description = "UTM Source Mixin Test Model (another)"
    _order = "id DESC"
    _rec_name = "title"
    _inherit = [
        "mixin.mail.thread",
        "mixin.utm.source",
    ]

    name = fields.Char(inherited=True)
    title = fields.Char()
