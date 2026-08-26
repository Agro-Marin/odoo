from odoo import api, models

from odoo.addons.website.tools import add_form_signature


class IrQwebFieldHtml(models.AbstractModel):
    _inherit = "ir.qweb.field.html"

    @api.model
    def _post_process_html_body(self, body, options):
        # Inside the converter's own parse. This used to re-parse and
        # re-serialise the finished string -- and said so, in a comment
        # noting it was "replicating what is done in the super()
        # implementation" -- so every html field carrying a <form> paid two
        # extra round-trips and a magic [6:-7] slice.
        body = super()._post_process_html_body(body, options)
        add_form_signature(body, self.sudo().env)
        return body
