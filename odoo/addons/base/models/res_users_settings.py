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
        """Get list of fields that won't be formatted."""
        return ["display_name"]

    @api.model
    def _find_or_create_for_user(self, user: Any) -> Self:
        """Return the settings record for *user*, creating one if absent.

        On a read-only cursor (e.g. a readonly HTTP route) fall back to an
        in-memory record so callers can format settings without writing on the
        RO cursor.
        """
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

    # Fields that must never be set via `set_res_users_settings`.
    _PROTECTED_SETTINGS_FIELDS = frozenset({"user_id", "id", *models.MAGIC_COLUMNS})

    def set_res_users_settings(self, new_settings: dict[str, Any]) -> dict[str, Any]:
        """Apply ``new_settings`` to this settings record and return the changes.

        Skips protected fields (``_PROTECTED_SETTINGS_FIELDS``), unknown fields
        and inverse-less computes, and only writes values that actually changed.

        :param dict new_settings: field name -> new value to apply.
        :return: the formatted subset of changed fields (+ ``id``).
        """
        self.ensure_one()
        # Ownership is enforced by the `res_users_settings_rule_user` record
        # rule, NOT here: the write runs without sudo so a group_user cannot
        # reach another user's record (RUSET-L1). Do NOT wrap this in sudo() --
        # it would bypass the rule. `user_id` is also in
        # `_PROTECTED_SETTINGS_FIELDS` so a row cannot be re-pointed at another
        # user.
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
        """Return whether writing ``new_value`` to ``fname`` would change it.

        Comparison is per field type: many2one compares ids (both normalized so
        ``None``/``False``/empty compare equal); x2many compares the id-set that
        applying the commands would yield against the current one (create/update
        commands, whose outcome isn't statically known, always count as
        changed); other fields compare by value.
        """
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
        """Return the id-set an x2many holding ``current_ids`` would contain
        after writing ``value`` (a list of x2many commands and/or bare ids).

        Return ``None`` when the outcome cannot be determined statically
        (create/update payloads, malformed commands, or a non-list value) --
        callers then treat the value as changed and let ``write()`` validate it.
        """
        if not isinstance(value, (list, tuple)):
            return None
        target_ids = set(current_ids)
        for command in value:
            match command:
                case int() if not isinstance(command, bool):
                    # bare id: linked to the relation (ORM shorthand)
                    target_ids.add(command)
                case [fields.Command.CREATE, *_] | [fields.Command.UPDATE, *_]:
                    # create/update: resulting relation can't be compared statically
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
