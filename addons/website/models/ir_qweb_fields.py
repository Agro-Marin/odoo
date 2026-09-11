from odoo import api, models

from odoo.addons.website.tools import add_form_signature


class IrQwebFieldHtml(models.AbstractModel):
    _inherit = "ir.qweb.field.html"

    @api.model
    def _post_process_html_body(self, body, options):
        body = super()._post_process_html_body(body, options)
        add_form_signature(body, self.sudo().env)
        return body
