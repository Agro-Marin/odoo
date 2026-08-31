from odoo import models


class MailGroup(models.Model):
    _inherit = "mail.group"

    def action_go_to_website(self):
        self.check_singleton()
        return {
            "type": "ir.actions.act_url",
            "target": "self",
            "url": "/groups/%s" % self.env["ir.http"]._slug(self),
        }
