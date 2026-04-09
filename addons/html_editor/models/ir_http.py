"""Extend ir.http with HTML editor context propagation."""

from odoo import models
from odoo.http import request

CONTEXT_KEYS = ["editable", "edit_translations", "translatable"]


class IrHttp(models.AbstractModel):
    """Extend ir.http to propagate editor query-string flags into the context."""

    _inherit = "ir.http"

    @classmethod
    def _get_editor_context(cls) -> dict[str, bool]:
        """Return editor context flags extracted from the query-string."""
        return {
            key: True
            for key in CONTEXT_KEYS
            if key in request.httprequest.args and key not in request.env.context
        }

    @classmethod
    def _pre_dispatch(cls, rule: object, args: dict) -> None:
        super()._pre_dispatch(rule, args)
        ctx = cls._get_editor_context()
        request.update_context(**ctx)

    @classmethod
    def _get_translation_frontend_modules_name(cls) -> list[str]:
        """Return frontend module names that provide translations."""
        return ["html_editor", *super()._get_translation_frontend_modules_name()]
