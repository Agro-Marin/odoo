from typing import Any, Self

from odoo import api, fields, models


class ResUsersSettings(models.Model):
    _name = "res.users.settings"
    _description = "User Settings"
    _rec_name = "user_id"

    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        index=False,
        ondelete="cascade",
        domain=[("res_users_settings_id", "=", False)],
    )

    _unique_user_id = models.Constraint(
        "UNIQUE(user_id)",
        "One user should only have one user settings.",
    )

    @api.model
    def _get_fields_blacklist(self) -> list[str]:
        return ["display_name"]

    @api.model
    def _find_or_create_for_user(self, user: Any) -> Self:
        settings = user.sudo().res_users_settings_ids
        if not settings:
            if self.env.cr.readonly:
                settings = self.sudo().new({"user_id": user.id})
            else:
                settings = self.sudo().create({"user_id": user.id})
        return settings

    def _res_users_settings_format(
        self, fields_to_format: list[str] | None = None
    ) -> dict[str, Any]:
        self.ensure_one()
        fields_blacklist = self._get_fields_blacklist()
        if fields_to_format:
            fields_to_format = [
                field for field in fields_to_format if field not in fields_blacklist
            ]
        else:
            fields_to_format = [
                name
                for name in self._fields
                if name == "id"
                or (name not in models.MAGIC_COLUMNS and name not in fields_blacklist)
            ]
        return self._format_settings(fields_to_format)

    def _format_settings(self, fields_to_format: list[str]) -> dict[str, Any]:
        res = self._read_format(
            fnames=[fname for fname in fields_to_format if fname != "user_id"]
        )[0]
        if "user_id" in fields_to_format:
            res["user_id"] = {"id": self.user_id.id}
        return res

    _PROTECTED_SETTINGS_FIELDS = frozenset({"user_id", "id", *models.MAGIC_COLUMNS})

    def set_res_users_settings(self, new_settings: dict[str, Any]) -> dict[str, Any]:
        self.ensure_one()
        changed_settings = {}
        for setting, new_value in new_settings.items():
            if setting in self._PROTECTED_SETTINGS_FIELDS:
                continue
            field = self._fields.get(setting)
            if not field or (field.compute and not field.inverse):
                continue
            if self._is_setting_changed(setting, new_value):
                changed_settings[setting] = new_value
        self.write(changed_settings)
        return self._res_users_settings_format([*changed_settings.keys(), "id"])

    def _is_setting_changed(self, fname: str, new_value: Any) -> bool:
        self.ensure_one()
        current_value = self[fname]
        match self._fields[fname].type:
            case "many2one":
                return (new_value or False) != (current_value.id or False)
            case "one2many" | "many2many":
                current_ids = set(current_value.ids)
                target_ids = self._x2many_command_target_ids(current_ids, new_value)
                return target_ids is None or target_ids != current_ids
            case _:
                return new_value != current_value

    @api.model
    def _x2many_command_target_ids(
        self, current_ids: set[int], value: Any
    ) -> set[int] | None:
        if not isinstance(value, (list, tuple)):
            return None
        target_ids = set(current_ids)
        for command in value:
            match command:
                case int() if not isinstance(command, bool):
                    target_ids.add(command)
                case [fields.Command.CREATE, *_] | [fields.Command.UPDATE, *_]:
                    return None
                case [fields.Command.DELETE, int() as res_id, *_] | [
                    fields.Command.UNLINK,
                    int() as res_id,
                    *_,
                ]:
                    target_ids.discard(res_id)
                case [fields.Command.LINK, int() as res_id, *_]:
                    target_ids.add(res_id)
                case [fields.Command.CLEAR, *_]:
                    target_ids = set()
                case [fields.Command.SET, _, [*res_ids]]:
                    target_ids = set(res_ids)
                case _:
                    return None
        return target_ids
