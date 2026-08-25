import logging
import uuid
from typing import Any, Self

from odoo import api, fields, models
from odoo.api import ValuesType
from odoo.db import insert_or_existing
from odoo.exceptions import ValidationError
from odoo.tools import config, mute_logger, ormcache

_logger = logging.getLogger(__name__)


_default_parameters = {
    "database.secret": lambda: str(uuid.uuid4()),
    "database.uuid": lambda: str(uuid.uuid4()),
    "database.create_date": fields.Datetime.now,
    "web.base.url": lambda: f"http://localhost:{config.get('http_port')}",
    "base.login_cooldown_after": lambda: 10,
    "base.login_cooldown_duration": lambda: 60,
}


class IrConfig_Parameter(models.Model):
    _name = "ir.config_parameter"
    _description = "System Parameter"
    _rec_name = "key"
    _order = "key"
    _allow_sudo_commands = False

    key = fields.Char(required=True)
    value = fields.Text(required=True)

    _key_uniq = models.Constraint(
        "unique (key)",
        "Key must be unique.",
    )

    @mute_logger("odoo.addons.base.models.ir_config_parameter")
    def init(self, force: bool = False) -> None:
        self = self.with_context(prefetch_fields=False).sudo()
        # One read for the whole set; searching per key cost a query each,
        # every time the registry initialises this model.
        present = set(
            self.search([("key", "in", list(_default_parameters))]).mapped("key")
        )
        for key, func in _default_parameters.items():
            if force or key not in present:
                self.set_param(key, func())

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        self.env.registry.clear_cache("stable")
        return super().create(vals_list)

    def write(self, vals: dict[str, Any]) -> bool:
        if "key" in vals:
            illegal = _default_parameters.keys() & self.mapped("key")
            if illegal:
                raise ValidationError(
                    self.env._(
                        "You cannot rename config parameters with keys %s",
                        ", ".join(illegal),
                    )
                )
        self.env.registry.clear_cache("stable")
        return super().write(vals)

    def unlink(self) -> bool:
        self.env.registry.clear_cache("stable")
        return super().unlink()

    @api.ondelete(at_uninstall=False)
    def _unlink_except_default_parameter(self) -> None:
        for record in self.filtered(lambda p: p.key in _default_parameters):
            raise ValidationError(
                self.env._("You cannot delete the %s record.", record.key)
            )

    @api.model
    def get_param(self, key: str, default: str | bool = False) -> str | bool:
        self.browse().check_access("read")
        value = self._get_param(key)
        return default if value is None else value

    @api.model
    def get_param_int(self, key: str, default: int) -> int:
        raw = self.get_param(key)
        if raw is False or raw is None or raw == "":
            return default
        try:
            return int(raw)
        except TypeError, ValueError:
            _logger.warning(
                "Invalid %s value: %r, falling back to %r", key, raw, default
            )
            return default

    @api.model
    def get_param_float(self, key: str, default: float) -> float:
        raw = self.get_param(key)
        if raw is False or raw is None or raw == "":
            return default
        try:
            return float(raw)
        except TypeError, ValueError:
            _logger.warning(
                "Invalid %s value: %r, falling back to %r", key, raw, default
            )
            return default

    _FALSY_PARAM_VALUES = frozenset({"", "0", "false", "no", "off", "none"})

    @api.model
    def get_param_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get_param(key)
        if raw is False or raw is None:
            return default
        return str(raw).strip().lower() not in self._FALSY_PARAM_VALUES

    @api.model
    @ormcache("key", cache="stable")
    def _get_param(self, key: str) -> str | None:
        self.flush_model(["key", "value"])
        self.env.cr.execute(
            "SELECT value FROM ir_config_parameter WHERE key = %s", [key]
        )
        result = self.env.cr.fetchone()
        return result and result[0]

    @api.model
    def set_param(self, key: str, value: Any) -> str | bool:
        param = self.search([("key", "=", key)])
        if not param:
            if value is False or value is None:
                return False
            param, created = insert_or_existing(
                self.env.cr,
                lambda: self.create({"key": key, "value": value}),
                lambda: self.search([("key", "=", key)]),
                conflict=f"ir.config_parameter {key!r}",
            )
            if created:
                return False

        old = param.value
        if value is False or value is None:
            param.unlink()
        elif str(value) != old:
            param.write({"value": value})
        return old
