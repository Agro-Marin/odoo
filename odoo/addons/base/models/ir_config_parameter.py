import logging
import uuid
from typing import Any, Self

import psycopg.errors

from odoo import api, fields, models
from odoo.api import ValuesType
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
        """Initialize the parameters in _default_parameters, overriding
        existing ones when ``force`` is True."""
        # avoid prefetching during module installation, as the res_users table
        # may not have all prescribed columns
        self = self.with_context(prefetch_fields=False)
        for key, func in _default_parameters.items():
            # force re-applies the default; otherwise seed only missing keys.
            params = self.sudo().search([("key", "=", key)])  # noqa: E8507 — bounded: _default_parameters is a small fixed dict
            if force or not params:
                params.set_param(key, func())

    @api.model
    def get_param(self, key: str, default: str | bool = False) -> str | bool:
        """Retrieve the value for a given key.

        :param str key: The key of the parameter value to retrieve.
        :param str | bool default: default value if parameter is missing.
        :return: The value of the parameter, or ``default`` if it does not exist.
        :rtype: str | bool
        """
        self.browse().check_access("read")
        value = self._get_param(key)
        return default if value is None else value

    @api.model
    @ormcache("key", cache="stable")
    def _get_param(self, key: str) -> str | None:
        # we bypass the ORM because get_param() is used in some field's depends,
        # and must therefore work even when the ORM is not ready to work
        self.flush_model(["key", "value"])
        self.env.cr.execute(
            "SELECT value FROM ir_config_parameter WHERE key = %s", [key]
        )
        result = self.env.cr.fetchone()
        return result and result[0]

    @api.model
    def set_param(self, key: str, value: Any) -> str | bool:
        """Sets the value of a parameter.

        :param str key: The key of the parameter value to set.
        :param Any value: The value to set.
        :return: the previous value of the parameter or False if it did
                 not exist.
        :rtype: str | bool
        """
        param = self.search([("key", "=", key)])
        if param:
            old = param.value
            if value is not False and value is not None:
                if str(value) != old:
                    param.write({"value": value})
            else:
                param.unlink()
            return old
        if value is False or value is None:
            return False
        try:
            # ICP-C1: the search-then-create pair is not atomic; a concurrent
            # transaction may commit the same key in between, tripping the unique
            # constraint. The savepoint lets losing the race degrade into the
            # update path below instead of aborting the whole transaction.
            with self.env.cr.savepoint():
                self.create({"key": key, "value": value})
        except psycopg.errors.UniqueViolation:
            param = self.search([("key", "=", key)])
            if not param:
                # the winning row was removed in the meantime; retry the create
                self.create({"key": key, "value": value})
                return False
            old = param.value
            if str(value) != old:
                param.write({"value": value})
            return old
        return False

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
    def unlink_default_parameters(self) -> None:
        for record in self.filtered(lambda p: p.key in _default_parameters):
            raise ValidationError(
                self.env._("You cannot delete the %s record.", record.key)
            )
