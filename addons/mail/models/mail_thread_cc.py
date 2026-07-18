from odoo import api, fields, models, tools


class MailThreadCc(models.AbstractModel):
    _name = "mail.thread.cc"
    _inherit = ["mail.thread"]
    _description = "Email CC management"

    email_cc = fields.Char("Email cc")

    def _mail_cc_sanitized_raw_dict(self, cc_string):
        """return a dict of sanitize_email:raw_email from a string of cc"""
        if not cc_string:
            return {}
        # email_split_tuples accepts any token containing '@', but email_normalize
        # returns False when it cannot extract a valid address (e.g. a bare "a@").
        # Feeding False to formataddr raises AttributeError, which aborts the whole
        # inbound route (attacker-controllable DoS via a crafted Cc header) and also
        # collapses every unparseable entry onto the same False key. Skip them.
        sanitized = {}
        for name, email in tools.mail.email_split_tuples(cc_string):
            normalized = tools.email_normalize(email)
            if not normalized:
                continue
            sanitized[normalized] = tools.formataddr((name, normalized))
        return sanitized

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        if custom_values is None:
            custom_values = {}
        cc_values = {
            "email_cc": ", ".join(
                self._mail_cc_sanitized_raw_dict(msg_dict.get("cc")).values()
            ),
        }
        cc_values.update(custom_values)
        return super().message_new(msg_dict, cc_values)

    def message_update(self, msg_dict, update_vals=None):
        # Adds cc email to self.email_cc while trying to keep email as raw as possible but unique
        if update_vals is None:
            update_vals = {}
        cc_values = {}
        new_cc = self._mail_cc_sanitized_raw_dict(msg_dict.get("cc"))
        if new_cc:
            old_cc = self._mail_cc_sanitized_raw_dict(self.email_cc)
            new_cc.update(old_cc)
            cc_values["email_cc"] = ", ".join(new_cc.values())
        cc_values.update(update_vals)
        return super().message_update(msg_dict, cc_values)

    def _message_add_suggested_recipients(self, force_primary_email=False):
        suggested = super()._message_add_suggested_recipients(
            force_primary_email=force_primary_email
        )
        for record in self.filtered("email_cc"):
            suggested[record.id]["email_to_lst"] += (
                tools.mail.email_split_and_format_normalize(record.email_cc)
            )
        return suggested
