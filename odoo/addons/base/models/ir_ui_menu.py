import base64
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Self

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import ValidationError
from odoo.http import request

MENU_ITEM_SEPARATOR = "/"
# anchored at the end of the name: only a trailing "(N)" is a copy counter
NUMBER_PARENS = re.compile(r"\((\d+)\)\s*$")


class IrUiMenu(models.Model):
    _name = "ir.ui.menu"
    _description = "Menu"
    _order = "sequence,id"
    _parent_store = True
    _allow_sudo_commands = False

    name = fields.Char(string="Menu", required=True, translate=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    parent_id = fields.Many2one(
        "ir.ui.menu", string="Parent Menu", index=True, ondelete="restrict"
    )
    parent_path = fields.Char(index=True)
    child_id = fields.One2many("ir.ui.menu", "parent_id", string="Child IDs")
    group_ids = fields.Many2many(
        "res.groups",
        "ir_ui_menu_group_rel",
        "menu_id",
        "gid",
        string="Groups",
        help="If you have groups, the visibility of this menu will be based on these groups. "
        "If this field is empty, Odoo will compute visibility based on the related object's read access.",
    )
    complete_name = fields.Char(
        string="Full Path", compute="_compute_complete_name", recursive=True
    )
    # display_name embeds the parent's value, so an ancestor rename must cascade
    # invalidation down; the ORM only cascades through recursive fields.
    display_name = fields.Char(recursive=True)
    web_icon = fields.Char(string="Web Icon File")
    action = fields.Reference(
        selection=[
            ("ir.actions.report", "ir.actions.report"),
            ("ir.actions.act_window", "ir.actions.act_window"),
            ("ir.actions.act_url", "ir.actions.act_url"),
            ("ir.actions.server", "ir.actions.server"),
            ("ir.actions.client", "ir.actions.client"),
        ]
    )

    web_icon_data = fields.Binary(string="Web Icon Image", attachment=True)

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self) -> None:
        self._set_full_name("complete_name")

    def _set_full_name(self, fname: str) -> None:
        """Assign each record's full hierarchical name to field ``fname``.

        Building each path from the parent's own ``fname`` (not by walking
        ``name`` up the chain) caches every ancestor's value, which is what
        lets recursive invalidation cascade to descendants on a rename. Shared
        by the ``complete_name`` and ``display_name`` computes.
        """
        for menu in self:
            if menu.parent_id:
                menu[fname] = (
                    (menu.parent_id[fname] or "")
                    + MENU_ITEM_SEPARATOR
                    + (menu.name or "")
                )
            else:
                menu[fname] = menu.name

    def _read_image(self, path: str) -> bytes | bool:
        if not path:
            return False
        path_info = path.split(",")
        # An image web icon is "module,path"; anything else isn't a readable image.
        if len(path_info) != 2:
            return False
        icon_path = str(Path(path_info[0]) / path_info[1])
        try:
            with tools.file_open(
                icon_path,
                "rb",
                filter_ext=(
                    ".png",
                    ".gif",
                    ".ico",
                    ".jfif",
                    ".jpeg",
                    ".jpg",
                    ".svg",
                    ".webp",
                ),
            ) as icon_file:
                return base64.encodebytes(icon_file.read())
        except FileNotFoundError, ValueError:
            return False

    @api.constrains("parent_id")
    def _check_parent_id(self) -> None:
        if self._has_cycle():
            raise ValidationError(
                self.env._("Error! You cannot create recursive menus.")
            )

    @api.model
    @tools.ormcache("frozenset(self.env.user._get_group_ids())", "debug")
    def _visible_menu_ids(self, debug: bool = False) -> frozenset[int]:
        """Return the ids of the menu items visible to the user."""
        group_ids = set(self.env.user._get_group_ids())
        if not debug:
            group_ids.discard(
                self.env["ir.model.data"]._xmlid_to_res_id(
                    "base.group_no_one", raise_if_not_found=False
                )
            )

        # filter out menus with groups the user does not have
        menus = (
            self.with_context({})
            .search_fetch(
                # Don't use 'any' operator in the domain to avoid ir.rule
                [
                    "|",
                    ("group_ids", "=", False),
                    ("group_ids", "in", tuple(group_ids)),
                ],
                ["parent_id", "action"],
                order="id",
            )
            .sudo()
        )

        # take apart menus that have an action
        action_ids_by_model = defaultdict(list)
        for action in menus.mapped("action"):
            if action:
                action_ids_by_model[action._name].append(action.id)

        MODEL_BY_TYPE = {
            "ir.actions.act_window": "res_model",
            "ir.actions.report": "model",
            "ir.actions.server": "model_name",
        }

        def exists_actions(model_name, action_ids):
            """Return existing actions and fetch model name field if exists"""
            if model_name not in MODEL_BY_TYPE:
                return self.env[model_name].browse(action_ids).exists()
            records = (
                self.env[model_name]
                .sudo()
                .with_context(active_test=False)
                .search_fetch(
                    [("id", "in", action_ids)],
                    [MODEL_BY_TYPE[model_name]],
                    order="id",
                )
            )
            if model_name == "ir.actions.server":
                # Because it is computed, `search_fetch` doesn't fill the cache for it
                records.mapped("model_name")
            return records

        existing_actions = {
            action
            for model_name, action_ids in action_ids_by_model.items()
            for action in exists_actions(model_name, action_ids)
        }
        menu_ids = set(menus._ids)
        visible_ids = set()
        access = self.env["ir.model.access"]
        # process action menus, check whether their action is allowed
        for menu in menus:
            action = menu.action
            if not action or action not in existing_actions:
                continue
            model_fname = MODEL_BY_TYPE.get(action._name)
            # action[model_fname] has been fetched in batch in `exists_actions`
            if model_fname and not access.check(action[model_fname], "read", False):
                continue
            # make menu visible, and its folder ancestors, too
            menu_id = menu.id
            while menu_id not in visible_ids and menu_id in menu_ids:
                visible_ids.add(menu_id)
                menu = menu.parent_id
                menu_id = menu.id

        return frozenset(visible_ids)

    def _filter_visible_menus(self) -> Self:
        """Filter `self` to the menu items visible to the current user (cached)."""
        visible_ids = self._visible_menu_ids(self._get_session_debug())
        return self.filtered(lambda menu: menu.id in visible_ids)

    # mirror _compute_complete_name's triggers (see _set_full_name)
    @api.depends("name", "parent_id.display_name")
    def _compute_display_name(self) -> None:
        self._set_full_name("display_name")

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        if not vals_list:
            # nothing to create: don't wipe the registry-wide caches
            return self.browse()
        self.env.registry.clear_cache()
        for values in vals_list:
            if "web_icon" in values:
                values["web_icon_data"] = self._compute_web_icon_data(
                    values.get("web_icon")
                )
        return super().create(vals_list)

    def write(self, vals: dict[str, Any]) -> bool:
        if self and vals:
            # only a real write invalidates the registry-wide caches
            self.env.registry.clear_cache()
        if "web_icon" in vals:
            vals["web_icon_data"] = self._compute_web_icon_data(vals.get("web_icon"))
        return super().write(vals)

    def _compute_web_icon_data(self, web_icon: str | None) -> bytes | bool:
        """Returns the image associated to ``web_icon``.

        :param str | None web_icon: a comma-separated value string for either:

          * an image icon: ``f"{module},{path}"``
          * a built icon: ``f"{icon_class},{icon_color},{background_color}"``

        The ``web_icon_data`` computed field uses :meth:`_read_image` for image
        web icons, and is ``False`` for built icons.
        """
        # A 2-part value is an image icon "module,path"; a built icon has 3
        # parts. A 2-part built icon (no bg) is indistinguishable here, but
        # _read_image returns False and the JS rebuilds it from web_icon.
        if web_icon and len(web_icon.split(",")) == 2:
            return self._read_image(web_icon)
        return False

    def unlink(self) -> bool:
        if not self:
            # nothing to unlink: don't wipe the registry-wide caches
            return True
        # Detach children and promote them to top-level rather than cascade-delete.
        # ondelete="set null" isn't an option: it's unsupported with _parent_store.
        # TODO: ideally move them under a generic "Orphans" menu somewhere?
        direct_children = self.with_context(active_test=False).search(
            [("parent_id", "in", self.ids)]
        )
        direct_children.write({"parent_id": False})

        self.env.registry.clear_cache()
        return super().unlink()

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        # Suffix the copies' names with a "(N)" counter at insert time. Renaming
        # after the copy fired one cache-wiping write() per copied menu.
        vals_list = super().copy_data(default=default)
        for vals in vals_list:
            if name := vals.get("name"):
                if match := NUMBER_PARENS.search(name):
                    next_num = int(match.group(1)) + 1
                    vals["name"] = NUMBER_PARENS.sub(f"({next_num})", name, count=1)
                else:
                    vals["name"] = name + " (1)"
        return vals_list

    @api.model
    def get_user_roots(self) -> Self:
        """Return all root menus visible to the user."""
        return self.search([("parent_id", "=", False)])._filter_visible_menus()

    def _load_menus_blacklist(self) -> list[int]:
        return []

    def _get_session_debug(self) -> str | bool:
        """Return ``request.session.debug``, or ``False`` off-request.

        Exposed so :meth:`load_menus_root` can key its ormcache on the debug
        state without taking a parameter.
        """
        return request.session.debug if request else False

    @api.model
    @tools.ormcache("self.env.uid", "self.env.lang", "self._get_session_debug()")
    def load_menus_root(self) -> dict[str, Any]:
        fields = ["name", "sequence", "parent_id", "action", "web_icon_data"]
        menu_roots = self.get_user_roots()
        menu_roots_data = menu_roots.read(fields) if menu_roots else []

        menu_root = {
            "id": False,
            "name": "root",
            "parent_id": [-1, ""],
            "children": menu_roots_data,
            "all_menu_ids": menu_roots.ids,
        }

        xmlids = menu_roots._get_menuitems_xmlids()
        for menu in menu_roots_data:
            menu["xmlid"] = xmlids.get(menu["id"], "")

        return menu_root

    @api.model
    @tools.ormcache("self.env.uid", "debug", "self.env.lang")
    def load_menus(self, debug: bool) -> dict[str | int, Any]:
        blacklisted_menu_ids = self._load_menus_blacklist()
        visible_menus = self.search_fetch(
            [("id", "not in", blacklisted_menu_ids)],
            ["name", "parent_id", "action", "web_icon"],
        )._filter_visible_menus()

        children_dict = defaultdict(
            list
        )  # {parent_id: []} / parent_id == False for root menus
        for menu in visible_menus:
            children_dict[menu.parent_id.id].append(menu.id)

        app_info = {}

        # recursively set app ids to related children
        def _set_app_id(menu_app_id, menu_id):
            if menu_id in app_info:
                return  # cycle guard
            app_info[menu_id] = menu_app_id
            for child_id in children_dict[menu_id]:
                _set_app_id(menu_app_id, child_id)

        for root_menu_id in children_dict[False]:
            _set_app_id(root_menu_id, root_menu_id)

        # Filter out menus not related to an app; happens when a parent menu is
        # not visible for the user's groups.
        visible_menus = visible_menus.filtered(lambda menu: menu.id in app_info)

        xmlids = visible_menus._get_menuitems_xmlids()
        icon_attachments = (
            self.env["ir.attachment"]
            .sudo()
            .search_read(
                domain=[
                    ("res_model", "=", "ir.ui.menu"),
                    ("res_id", "in", visible_menus._ids),
                    ("res_field", "=", "web_icon_data"),
                ],
                fields=["res_id", "datas", "mimetype"],
            )
        )
        icon_attachments_res_id = {
            attachment["res_id"]: attachment for attachment in icon_attachments
        }

        menus_dict = {}
        action_ids_by_type = defaultdict(list)
        for menu in visible_menus:
            menu_id = menu.id
            attachment = icon_attachments_res_id.get(menu_id)

            if action := menu.action:
                action_model = action._name
                action_id = action.id
                action_ids_by_type[action_model].append(action_id)
            else:
                action_model = False
                action_id = False

            menus_dict[menu_id] = {
                "id": menu_id,
                "name": menu.name,
                "app_id": app_info[menu_id],
                "action_model": action_model,
                "action_id": action_id,
                "web_icon": menu.web_icon,
                "web_icon_data": (
                    attachment["datas"].decode()
                    if attachment and attachment["datas"]
                    else False
                ),
                "web_icon_data_mimetype": (
                    attachment["mimetype"] if attachment else False
                ),
                "xmlid": xmlids.get(menu_id, ""),
            }

        # Batch-fetch action.path into a (model, id) -> path map so the per-menu
        # loop reads from memory instead of re-browsing one action at a time.
        action_path_by_action = {}
        for model_name, action_ids in action_ids_by_type.items():
            actions = self.env[model_name].sudo().browse(action_ids)
            actions.fetch(["path"])
            for action in actions:
                action_path_by_action[model_name, action.id] = action.path

        # set children + model_path
        for menu_dict in menus_dict.values():
            if menu_dict["action_model"]:
                menu_dict["action_path"] = action_path_by_action.get(
                    (menu_dict["action_model"], menu_dict["action_id"]), False
                )
            else:
                menu_dict["action_path"] = False
            menu_dict["children"] = children_dict[menu_dict["id"]]

        menus_dict["root"] = {
            "id": False,
            "name": "root",
            "children": children_dict[False],
        }
        return menus_dict

    def _get_menuitems_xmlids(self) -> dict[int, str]:
        menuitems = (
            self.env["ir.model.data"]
            .sudo()
            .search_fetch(
                [("res_id", "in", self.ids), ("model", "=", "ir.ui.menu")],
                ["res_id", "complete_name"],
            )
        )

        return {menu.res_id: menu.complete_name for menu in menuitems}
