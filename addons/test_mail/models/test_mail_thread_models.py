from odoo import fields, models


class MailTestCc(models.Model):
    _name = "mail.test.cc"
    _description = "Test Email CC Thread"
    _inherit = ["mixin.mail.thread.cc"]

    name = fields.Char()
