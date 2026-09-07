from odoo import Command
from odoo.tests.common import TransactionCase


class TestRecipients(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"].with_context(
            {
                "mail_create_nolog": True,
                "mail_create_nosubscribe": True,
                "mail_notrack": True,
                "no_reset_password": True,
            }
        )
        cls.partner_1 = Partner.create(
            {
                "name": "Valid Lelitre",
                "email": "valid.lelitre@agrolait.com",
                "country_id": cls.env.ref("base.be").id,
                "phone_ids": [
                    Command.create({"number": "0456001122", "type": "landline"})
                ],
            }
        )
        cls.partner_2 = Partner.create(
            {
                "name": "Valid Poilvache",
                "email": "valid.other@gmail.com",
                "country_id": cls.env.ref("base.be").id,
                "phone_ids": [
                    Command.create({"number": "+32 456 22 11 00", "type": "landline"})
                ],
            }
        )
