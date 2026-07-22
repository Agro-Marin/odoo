from odoo import models
from odoo.http import request

CONTEXT_KEYS = ['editable', 'edit_translations', 'translatable']


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _get_editor_context(cls):
        """Return editor context keys enabled via query-string args."""
        return {
            key: True
            for key in CONTEXT_KEYS
            if key in request.httprequest.args and key not in request.env.context
        }

    @classmethod
    def _pre_dispatch(cls, rule, args):
        super()._pre_dispatch(rule, args)
        ctx = cls._get_editor_context()
        request.update_context(**ctx)

    @classmethod
    def _get_translation_frontend_modules_name(cls):
        return ["html_editor", *super()._get_translation_frontend_modules_name()]
