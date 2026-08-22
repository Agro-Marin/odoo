from odoo import models
from odoo.tools import is_html_empty, lazy


class IrQweb(models.AbstractModel):

    _inherit = "ir.qweb"

    def _prepare_frontend_environment(self, values):
        irQweb = super()._prepare_frontend_environment(values)
        values.update(
            is_html_empty=is_html_empty,
            frontend_languages=lazy(lambda: irQweb.env["res.lang"]._get_frontend()),  # noqa: PLW0108
        )
        for key in irQweb.env.context:
            if key not in values:
                values[key] = irQweb.env.context[key]

        return irQweb
