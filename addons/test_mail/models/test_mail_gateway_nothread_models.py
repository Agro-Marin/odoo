from odoo import api, fields, models


class MailTestGatewayNothread(models.Model):
    _name = "mail.test.gateway.nothread"
    _description = "Alias owner that is not a thread but takes incoming mail"
    _inherit = ["mixin.mail.alias"]

    name = fields.Char()
    received_subjects = fields.Text()

    def _alias_get_creation_values(self):
        values = super()._alias_get_creation_values()
        values["alias_model_id"] = (
            self.env["ir.model"]._get("mail.test.gateway.nothread").id
        )
        if self.id:
            values["alias_force_thread_id"] = self.id
        return values

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        return self.create({"name": msg_dict.get("subject"), **(custom_values or {})})

    def message_update(self, msg_dict, update_vals=None):
        return True

    def message_post(self, *, subject=None, **kwargs):
        for record in self:
            record.received_subjects = "\n".join(
                filter(None, [record.received_subjects, subject])
            )
        return self.env["mail.message"]
