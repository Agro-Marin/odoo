from lxml import etree
from markupsafe import Markup

from odoo import api, models

from odoo.addons.website.tools import add_form_signature


class IrQwebFieldHtml(models.AbstractModel):
    _inherit = "ir.qweb.field.html"

    @api.model
    def value_to_html(self, value, options):
        res = super().value_to_html(value, options)

        if res and "<form" in res:
            body = etree.fromstring("<body>%s</body>" % res, etree.HTMLParser())[0]
            add_form_signature(body, self.sudo().env)
            res = Markup(etree.tostring(body, encoding="unicode", method="html")[6:-7])

        return res
