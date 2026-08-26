from odoo import models

from . import ir_http


class Base(models.AbstractModel):
    _inherit = "base"

    def get_base_url(self):
        if not self:
            return super().get_base_url()
        self.ensure_one()

        if self._name == "website":
            return self.domain or super().get_base_url()
        if "website_id" in self and self.sudo().website_id.domain:
            return self.sudo().website_id.domain
        if "company_id" in self and self.company_id.website_id.domain:
            return self.company_id.website_id.domain
        return super().get_base_url()

    def get_website_meta(self):
        return {}

    def _get_base_lang(self):
        website = ir_http.get_request_website()
        if website:
            return website.default_lang_id.code
        return super()._get_base_lang()
