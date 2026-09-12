from odoo import models, tools

from ..tools import debug_log as dbg
from odoo.addons.mail.tools.alias_error import AliasError


class Base(models.AbstractModel):
    _inherit = "base"

    def _alias_resolve_error(self, message, message_dict, alias):
        if alias.alias_contact != "employees":
            return super()._alias_resolve_error(message, message_dict, alias)
        error = AliasError(
            "error_hr_employee_restricted", self.env._("restricted to employees")
        )
        email_address = tools.email_normalize(
            message_dict.get("email_from") or "", strict=False
        )
        if not email_address:
            dbg.logic.debug(
                "[alias:%s] employees-only, no sender address: refused", alias.id
            )
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
        dbg.logic.debug(
            "[alias:%s] employees-only, sender %s -> employee %s: %s",
            alias.id,
            email_address,
            employee.id,
            "accepted" if employee else "refused",
        )
        return False if employee else error
