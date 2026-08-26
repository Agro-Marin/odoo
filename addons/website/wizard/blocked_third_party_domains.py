from urllib3.exceptions import LocationParseError
from urllib3.util import parse_url

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class WebsiteCustom_Blocked_Third_Party_Domains(models.TransientModel):
    _name = "website.custom_blocked_third_party_domains"
    _description = "User list of blocked 3rd-party domains"

    content = fields.Text(
        default=lambda s: (
            s.env["website"].get_current_website().custom_blocked_third_party_domains
        )
    )

    def action_save(self):
        domains = []
        if self.content:
            for line in self.content.split("\n"):
                domain = line.strip().lower()
                if not domain:
                    continue

                if domain[0] == "#":
                    domains.append(domain)
                    continue

                try:
                    domain = parse_url(domain).host
                except LocationParseError:
                    raise ValidationError(
                        _("The following domain is not valid:") + "\n" + domain
                    ) from None
                if domain:
                    domains.append(domain)

        self.env[
            "website"
        ].get_current_website().custom_blocked_third_party_domains = "\n".join(domains)
        return {"type": "ir.actions.act_window_close"}
