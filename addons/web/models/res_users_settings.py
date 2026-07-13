from typing import Any

from odoo import api, fields, models


class ResUsersSettings(models.Model):
    _inherit = "res.users.settings"

    embedded_actions_config_ids = fields.One2many(
        "res.users.settings.embedded.action", "user_setting_id"
    )
    density = fields.Selection(
        [
            ("default", "Default"),
            ("compact", "Compact"),
            ("condensed", "Condensed"),
        ],
        default="default",
        required=True,
        string="Content Density",
    )

    @api.model
    def _format_settings(self, fields_to_format: list[str]) -> dict[str, Any]:
        res = super()._format_settings(fields_to_format)
        if "embedded_actions_config_ids" in fields_to_format:
            res["embedded_actions_config_ids"] = (
                self.embedded_actions_config_ids._embedded_action_settings_format()
            )
        return res

    def get_embedded_actions_settings(self) -> dict[str, Any]:
        self.ensure_one()
        return self.embedded_actions_config_ids._embedded_action_settings_format()

    def set_embedded_actions_setting(
        self, action_id: int, res_id: int, vals: dict[str, Any]
    ) -> None:
        self.ensure_one()
        embedded_actions_config = self.env["res.users.settings.embedded.action"].search(
            [
                ("user_setting_id", "=", self.id),
                ("action_id", "=", action_id),
                ("res_id", "=", res_id),
            ],
            limit=1,
        )
        # Whitelist the client-settable fields. Without this, an arbitrary key
        # in ``vals`` flows straight into ``write()``; in particular a caller
        # could pass ``user_setting_id`` to RE-POINT their own config row onto
        # another user's settings — the ir.rule (web_security.xml) only checks
        # the pre-image, which is the caller's own row — polluting the victim's
        # embedded-actions bar and squatting their ``(user_setting_id,
        # action_id, res_id)`` unique slot. The identity fields
        # (``user_setting_id``/``action_id``/``res_id``) are set explicitly on
        # create below and must never be writable from the client.
        _ID_LIST_FIELDS = ("embedded_actions_order", "embedded_actions_visibility")
        _SETTABLE_FIELDS = (*_ID_LIST_FIELDS, "embedded_visibility", "res_model")
        new_vals = {}
        for field, value in vals.items():
            if field not in _SETTABLE_FIELDS:
                continue
            if field in _ID_LIST_FIELDS:
                new_vals[field] = ",".join(
                    "false" if act_id is False else str(act_id) for act_id in value
                )
            else:
                new_vals[field] = value
        if embedded_actions_config:
            embedded_actions_config.write(new_vals)
        else:
            self.env["res.users.settings.embedded.action"].create(
                {
                    **new_vals,
                    "user_setting_id": self.id,
                    "action_id": action_id,
                    "res_id": res_id,
                }
            )
