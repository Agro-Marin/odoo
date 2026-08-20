import logging
from collections import defaultdict
from typing import Any, Literal, Self

from odoo import api, models
from odoo.api import ValuesType

_logger = logging.getLogger(__name__)


class IrConfig_Parameter(models.Model):
    _inherit = "ir.config_parameter"

    @api.model
    def _get_int_param(self, key: str, default: int) -> int:
        return self.sudo().get_param_int(key, default)

    @api.model
    def _get_positive_int_param(self, key: str, default: int) -> int:
        value = self._get_int_param(key, default)
        if value < 1:
            if value != 0:
                _logger.warning(
                    "Ignoring %s = %s: a count below one has no meaning here, "
                    "falling back to %s",
                    key,
                    value,
                    default,
                )
            return default
        return value

    @api.model
    def _get_bool_param(self, key: str, default: bool = False) -> bool:
        return self.sudo().get_param_bool(key, default)

    @api.model
    def set_param(self, key: str, value: Any) -> Literal[True]:
        if key == "mail.restrict.template.rendering":
            group_user = self.env.ref("base.group_user")
            group_mail_template_editor = self.env.ref("mail.group_mail_template_editor")

            if not value and group_mail_template_editor not in group_user.implied_ids:
                group_user._apply_group(group_mail_template_editor)

            elif value and group_mail_template_editor in group_user.implied_ids:
                group_user._remove_group(group_mail_template_editor)
        elif key == "mail.catchall.domain.allowed":
            value = (
                self.env["mail.alias.domain"]._sanitize_allowed_domains(value)
                if value
                else False
            )

        return super().set_param(key, value)

    def _sanitize_param_value(self, key: str, value: Any) -> str:
        if key == "mail.catchall.domain.allowed" and value:
            return self.env["mail.alias.domain"]._sanitize_allowed_domains(value)
        return value

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        for vals in vals_list:
            if vals.get("key") and "value" in vals:
                vals["value"] = self._sanitize_param_value(vals["key"], vals["value"])
        return super().create(vals_list)

    def write(self, vals: ValuesType) -> Literal[True]:
        if "value" in vals:
            records_by_value = defaultdict(self.browse)
            for record in self:
                key = vals.get("key", record.key)
                records_by_value[self._sanitize_param_value(key, vals["value"])] |= (
                    record
                )
            result = True
            for value, records in records_by_value.items():
                result = (
                    super(IrConfig_Parameter, records).write({**vals, "value": value})
                    and result
                )
            return result
        return super().write(vals)
