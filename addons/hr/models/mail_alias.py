from odoo import fields, models


class MailAlias(models.Model):
    _inherit = "mail.alias"

    alias_contact = fields.Selection(
        selection_add=[
            ("employees", "Authenticated Employees"),
        ],
        ondelete={"employees": "cascade"},
    )

    def _get_alias_contact_description(self):
        if self.alias_contact == "employees":
            return self.env._("addresses linked to registered employees")
        return super()._get_alias_contact_description()
