from odoo.http import request

from odoo.addons.website.controllers.form import WebsiteForm


class ContactController(WebsiteForm):
    def _handle_website_form(self, model_name, **kwargs):
        if model_name == "crm.lead":
            request.params["reveal_ip"] = request.httprequest.remote_addr

        return super()._handle_website_form(model_name, **kwargs)
