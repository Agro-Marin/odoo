from odoo import fields, models


class MailingContact(models.Model):
    _name = "mailing.contact"
    _inherit = ["mailing.contact", "mixin.mail.thread.phone"]

    phone_ids = fields.Many2many(
        "phone.number",
        "mailing_contact_phone_number_rel",
        "contact_id",
        "phone_number_id",
        string="Phone Numbers",
    )
