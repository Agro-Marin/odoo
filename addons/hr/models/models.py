from odoo import models, tools

from odoo.addons.mail.tools.alias_error import AliasError


class Base(models.AbstractModel):
    _inherit = "base"

    def _alias_get_error(self, message, message_dict, alias):
        if alias.alias_contact != "employees":
            return super()._alias_get_error(message, message_dict, alias)
        error = AliasError(
            "error_hr_employee_restricted", self.env._("restricted to employees")
        )
        email_address = tools.email_normalize(
            message_dict.get("email_from") or "", strict=False
        )
        if not email_address:
            return error
        # `=ilike`, not `ilike`: `%` and `_` are legal in a local part, and a
        # substring match would let `%@example.com` stand for every employee.
        pattern = tools.escape_psql(email_address)
        employee = self.env["hr.employee"].search(
            [
                "|",
                ("work_email", "=ilike", pattern),
                ("user_id.email", "=ilike", pattern),
            ],
            limit=1,
        )
        return False if employee else error
