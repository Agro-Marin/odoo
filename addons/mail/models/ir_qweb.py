import re
from typing import Any

from lxml import etree

from odoo import models

STATIC_EXPRESSION_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\Z")


class IrQweb(models.AbstractModel):
    _inherit = "ir.qweb"

    allowed_directives = (
        "out",
        "inner-content",
        "att",
        "tag-open",
        "tag-close",
    )

    def _get_template_cache_keys(self) -> list[str]:
        return super()._get_template_cache_keys() + [
            "raise_on_forbidden_code_for_model"
        ]

    def _compile_directive(
        self,
        el: etree._Element,
        compile_context: dict[str, Any],
        directive: str,
        level: int,
    ) -> list[str]:
        if (
            "raise_on_forbidden_code_for_model" in compile_context
            and directive not in self.allowed_directives
        ):
            raise PermissionError(
                "This directive is not allowed for this rendering mode."
            )
        return super()._compile_directive(el, compile_context, directive, level)

    def _compile_directive_att(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        if "raise_on_forbidden_code_for_model" in compile_context:
            if set(el.attrib) - {
                "t-out",
                "t-tag-open",
                "t-tag-close",
                "t-inner-content",
            }:
                raise PermissionError(
                    "This directive is not allowed for this rendering mode."
                )
        return super()._compile_directive_att(el, compile_context, level)

    def _compile_expr(self, expr: str, raise_on_missing: bool = False) -> str:
        model = self.env.context.get("raise_on_forbidden_code_for_model")
        if model is not None and not self._is_expression_allowed(expr, model):
            raise PermissionError(
                "This directive is not allowed for this rendering mode."
            )
        return super()._compile_expr(expr, raise_on_missing)

    def _compile_directive_out(
        self, el: etree._Element, compile_context: dict[str, Any], level: int
    ) -> list[str]:
        if "raise_on_forbidden_code_for_model" in compile_context:
            if len(el) != 0:
                raise PermissionError("No child allowed for t-out.")
            if set(el.attrib) - {"t-out", "t-tag-open", "t-tag-close"}:
                raise PermissionError("No other attribute allowed for t-out.")
        return super()._compile_directive_out(el, compile_context, level)

    def _is_expression_allowed(self, expression: str, model: str) -> bool:
        expression = expression.strip()
        return bool(
            model
            and STATIC_EXPRESSION_RE.match(expression)
            and expression in self.env[model].mail_allowed_qweb_expressions()
        )
