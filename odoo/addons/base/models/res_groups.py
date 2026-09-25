from typing import Any, Self

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.libs.debug_log import DebugLog
from odoo.tools import SetDefinitions

from odoo.addons.base.models.mixin_catalog import name_uniq_index
from odoo.addons.base.models.res_users_grant import projecting

_debug = DebugLog(__name__)


class ResGroups(models.Model):
    _name = "res.groups"
    _access_audit = True
    _description = "Access Groups"
    _rec_name = "full_name"
    _allow_sudo_commands = False
    _order = "privilege_id, sequence, name, id"
    _search_visibility_fields = ()

    name = fields.Char(
        translate=True,
        required=True,
    )
    user_ids = fields.Many2many(
        comodel_name="res.users",
        relation="res_groups_users_rel",
        column1="gid",
        column2="uid",
        help="Users explicitly in this group",
    )
    grant_ids = fields.One2many(
        comodel_name="res.users.grant",
        inverse_name="group_id",
        string="Grants",
    )
    admin_group_id = fields.Many2one(
        comodel_name="res.groups",
        string="Administered By",
        default=lambda self: self.env.ref(
            "base.group_erp_manager", raise_if_not_found=False
        ),
        ondelete="set null",
        help="The members of this group may grant and revoke this one, for "
        "other users and within their own companies. The access administrators "
        "may always.",
    )
    all_user_ids = fields.Many2many(
        comodel_name="res.users",
        string="Users and implied users",
        compute="_compute_all_user_ids",
        inverse="_inverse_all_user_ids",
        search="_search_all_user_ids",
    )

    all_users_count = fields.Integer(
        string="# Users",
        compute="_compute_all_users_count",
        compute_sudo=True,
        help="Number of users having this group (implicitly or explicitly)",
    )

    access_ids = fields.One2many(
        comodel_name="ir.access",
        inverse_name="group_id",
        string="Accesses",
        copy=True,
    )
    menu_access = fields.Many2many(
        comodel_name="ir.ui.menu",
        relation="ir_ui_menu_group_rel",
        column1="gid",
        column2="menu_id",
        string="Access Menu",
    )
    view_access = fields.Many2many(
        comodel_name="ir.ui.view",
        relation="ir_ui_view_group_rel",
        column1="group_id",
        column2="view_id",
        string="Views",
    )
    comment = fields.Text(translate=True)
    full_name = fields.Char(
        string="Group Name",
        compute="_compute_full_name",
        search="_search_full_name",
    )
    is_privilege = fields.Boolean(
        string="Privilege",
        help="A group only code holds, through with_privilege(): its accesses "
        "say exactly what the elevation allows. It is never granted to a user "
        "and never implied. (Unrelated to the privilege a group sits under in "
        "the user form, which is its application.)",
    )
    audit_privilege = fields.Boolean(
        help="Every create, write and delete made under this privilege is "
        "recorded in the authorization log, whatever the model.",
    )
    share = fields.Boolean(
        string="Share Group",
        help="Group created to set access rights for sharing data with some users.",
    )
    api_key_duration = fields.Float(
        string="API Keys maximum duration days",
        help="Determines the maximum duration of an api key created by a user belonging to this group.",
    )

    sequence = fields.Integer()
    privilege_id = fields.Many2one(
        comodel_name="res.groups.privilege",
        index=True,
    )
    view_group_hierarchy = fields.Json(
        string="Technical field for default group setting",
        compute="_compute_view_group_hierarchy",
    )

    _name_src_uniq = name_uniq_index(
        "privilege_id",
        nulls_distinct=True,
        message="The name of the group must be unique within a group privilege!",
    )
    _check_api_key_duration = models.Constraint(
        "CHECK(api_key_duration >= 0)",
        "The api key duration cannot be a negative value.",
    )

    implied_ids = fields.Many2many(
        comodel_name="res.groups",
        relation="res_groups_implied_rel",
        column1="gid",
        column2="hid",
        string="Implied Groups",
        help="Users of this group are also implicitly part of those groups",
    )
    all_implied_ids = fields.Many2many(
        comodel_name="res.groups",
        string="Transitively Implied Groups",
        compute="_compute_all_implied_ids",
        search="_search_all_implied_ids",
        compute_sudo=True,
        recursive=True,
        help="The group itself with all its implied groups.",
    )
    implied_by_ids = fields.Many2many(
        comodel_name="res.groups",
        relation="res_groups_implied_rel",
        column1="hid",
        column2="gid",
        string="Implying Groups",
        help="Users in those groups are implicitly part of this group.",
    )
    all_implied_by_ids = fields.Many2many(
        comodel_name="res.groups",
        string="Transitively Implying Groups",
        compute="_compute_all_implied_by_ids",
        search="_search_all_implied_by_ids",
        compute_sudo=True,
        recursive=True,
    )
    disjoint_ids = fields.Many2many(
        comodel_name="res.groups",
        string="Disjoint Groups",
        compute="_compute_disjoint_ids",
        help="A user may not belong to this group and one of those.  For instance, users may not be portal users and internal users.",
    )

    @api.constrains("implied_ids", "implied_by_ids")
    def _check_disjoint_groups(self) -> None:
        _debug.lifecycle("groups_cache_cleared", groups=self.ids, by="implied_ids")
        self.env.registry.clear_cache("groups")
        self.all_implied_by_ids._check_user_disjoint_groups()

    @api.constrains("view_access")
    def _check_inherited_view_groups(self) -> None:
        _debug.logic(
            "inherited_view_groups_checked",
            groups=self.ids,
            views=len(self.view_access),
        )
        self.view_access._check_groups()

    @api.constrains("is_privilege", "implied_ids", "user_ids")
    def _check_privilege_is_held_by_code_only(self) -> None:
        for group in self:
            linked = group.implied_ids | group.implied_by_ids
            if group.is_privilege and (group.user_ids or linked):
                raise ValidationError(
                    self.env._(
                        "%(group)s is a privilege: only code holds it, so it has no "
                        "users and neither implies nor is implied by a group.",
                        group=group.full_name,
                    )
                )
            if not group.is_privilege and linked.filtered("is_privilege"):
                raise ValidationError(
                    self.env._(
                        "%(group)s cannot imply or be implied by a privilege.",
                        group=group.full_name,
                    )
                )

    @api.model
    @tools.ormcache("names", cache="stable")
    def _privilege_ids(self, names: tuple[str, ...]) -> frozenset[int]:
        ids = set()
        for name in names:
            group = self.sudo().env.ref(name, raise_if_not_found=False)
            if group is None or group._name != "res.groups" or not group.is_privilege:
                raise ValueError(
                    f"{name!r} names no privilege: declare it as a res.groups record "
                    f"with is_privilege set, and give it its ir.access rows"
                )
            ids.add(group.id)
        return frozenset(ids)

    @api.constrains("user_ids")
    def _check_user_disjoint_groups(self) -> None:
        gids = self._get_user_type_groups().ids
        domain = (
            Domain("active", "=", True)
            & Domain("group_ids", "in", self.ids)
            & Domain.OR(
                Domain("all_group_ids", "in", [gids[index]])
                & Domain("all_group_ids", "in", gids[index + 1 :])
                for index in range(len(gids) - 1)
            )
        )
        user = self.env["res.users"].search(domain, order="id", limit=1)
        _debug.logic(
            "user_disjoint_groups_checked",
            groups=self.ids,
            user_type_groups=len(gids),
            offender=user.id,
        )
        if user:
            user._check_disjoint_groups()

    @api.ondelete(at_uninstall=False)
    def _unlink_except_settings_group(self) -> None:
        classified = self.env["res.config.settings"]._get_fields_classified()
        for _name, _groups, implied_group in classified["group"]:
            if implied_group.id in self.ids:
                _debug.logic("unlink_refused_settings_group", group=implied_group.id)
                raise ValidationError(
                    self.env._(
                        "You cannot delete a group linked with a settings field."
                    )
                )

    @api.depends("privilege_id.name", "name")
    @api.depends_context("short_display_name")
    def _compute_full_name(self) -> None:
        for group, group1 in zip(self, self.sudo(), strict=True):
            if group1.privilege_id and not self.env.context.get("short_display_name"):
                group.full_name = f"{group1.privilege_id.name} / {group1.name}"
            else:
                group.full_name = group1.name

    def _search_full_name(self, operator: str, operand: Any) -> Domain:
        if operator in Domain.NEGATIVE_OPERATORS:
            _debug.logic("full_name_search_unsupported", operator=operator)
            return NotImplemented

        if isinstance(operand, str):

            def value_to_operand(val):
                return val

            operands = [operand]
        else:

            def value_to_operand(val):
                return [val]

            operands = operand

        where_domains = [Domain("name", operator, operand)]
        for group in operands:
            if not group:
                continue
            if "/" in group:
                privilege_name, _, group_name = group.partition("/")
                group_name = group_name.strip()
                privilege_name = privilege_name.strip()
            else:
                privilege_name = group
                group_name = None

            if privilege_name:
                domain = Domain(
                    "privilege_id",
                    "any!",
                    Domain("name", operator, value_to_operand(privilege_name)),
                )
                if group_name:
                    domain &= Domain("name", operator, value_to_operand(group_name))
                where_domains.append(domain)

        _debug.logic(
            "full_name_search",
            operator=operator,
            operands=len(operands),
            domains=len(where_domains),
        )
        return Domain.OR(where_domains)

    @api.model
    def _search(
        self,
        domain: list,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        **kwargs: Any,
    ) -> Any:
        if order and order.startswith("full_name"):
            groups = super().search(domain)
            _debug.perf.count(
                "search_sorted_in_python",
                by="full_name",
                groups=len(groups),
                offset=offset,
                limit=limit,
            )
            groups = groups.sorted(
                "full_name", reverse=order.strip().upper().endswith("DESC")
            )
            groups = groups[offset : offset + limit] if limit else groups[offset:]
            return groups._as_query(order)
        return super()._search(domain, offset, limit, order, **kwargs)

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        for group, vals in zip(self, vals_list, strict=True):
            vals["name"] = default.get("name") or self.env._("%s (copy)", group.name)
        return vals_list

    def copy_translations(self, new, excluded=()):
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record.env._("%s (copy)", term)
        )

    def write(self, vals: dict[str, Any]) -> bool:
        if "name" in vals:
            if vals["name"].startswith("-"):
                _debug.logic("write_refused", groups=self.ids, reason="name_dash")
                raise UserError(
                    self.env._('The name of the group can not start with "-"')
                )

        membership = (
            self._user_membership()
            if "user_ids" in vals and self.ids and not projecting()
            else None
        )
        _debug.lifecycle("write", count=len(self), fields=list(vals))
        res = super().write(vals)
        if membership is not None:
            after = self._user_membership()
            self.env["res.users.grant"]._follow_membership(
                after - membership, membership - after
            )
        if {"user_ids", "implied_ids"} & vals.keys():
            # res.users holds the invariant on its own side only
            _debug.logic(
                "administrator_checked",
                groups=self.ids,
                by="write",
                fields=sorted({"user_ids", "implied_ids"} & vals.keys()),
            )
            self.env["res.users"]._check_at_least_one_administrator()

        if self.ids:
            self.env["ir.access"]._clear_access_caches()
            self.env.registry.clear_cache("groups")
            _debug.lifecycle("groups_cache_cleared", groups=self.ids, by="write")

        return res

    def _add_missing_xml_ids(self) -> dict[int, str]:
        result = self.get_external_id()
        missings = {
            group_id: f"__custom__.group_{group_id}"
            for group_id, ext_id in result.items()
            if not ext_id
        }
        if missings:
            _debug.lifecycle("custom_xmlids_added", groups=list(missings))
            self.env["ir.model.data"].sudo().create(
                [
                    {
                        "name": name.split(".")[1],
                        "model": "res.groups",
                        "res_id": group_id,
                        "module": name.split(".")[0],
                    }
                    for group_id, name in missings.items()
                ]
            )
            result.update(missings)

        return result

    @api.depends("all_implied_by_ids.user_ids")
    def _compute_all_user_ids(self) -> None:
        groups = self.with_context(active_test=False)
        groups.all_implied_by_ids.fetch(["user_ids"])
        _debug.perf.count(
            "all_user_ids_computed",
            groups=len(groups),
            implying=len(groups.all_implied_by_ids),
        )
        for group in groups:
            group.all_user_ids = group.all_implied_by_ids.user_ids

    def _inverse_all_user_ids(self) -> None:
        for group in self:
            implied_by_users = group.all_implied_by_ids.user_ids
            user_to_add = group.all_user_ids - implied_by_users
            user_to_remove = implied_by_users - group.all_user_ids

            if user_to_remove:
                _debug.logic(
                    "implied_users_removal_refused",
                    group=group.id,
                    users=user_to_remove.ids,
                )
                raise UserError(
                    self.env._(
                        "It is not possible to remove implied group %(group)s from users %(users)s",
                        group=repr(group.name),
                        users=", ".join(user_to_remove.mapped("name")),
                    )
                )

            _debug.lifecycle("group_users_added", group=group.id, users=user_to_add.ids)
            group.user_ids += user_to_add

    def _search_all_user_ids(self, operator: str, value: Any) -> list:
        return [("all_implied_by_ids.user_ids", operator, value)]

    @api.depends("implied_ids.all_implied_ids")
    def _compute_all_implied_ids(self) -> None:
        group_definitions = self._get_group_definitions()
        _debug.perf.count("all_implied_ids_computed", groups=len(self))
        for g in self:
            g.all_implied_ids = g.ids + group_definitions.get_superset_ids(g.ids)

    def _search_all_implied_ids(self, operator: str, value: Any) -> list:
        if operator in ("any", "not any") and isinstance(value, Domain):
            value = self.search(value).ids
            _debug.logic(
                "all_implied_ids_search_resolved", operator=operator, groups=len(value)
            )
            operator = "in" if operator == "any" else "not in"
        elif operator not in ("in", "not in"):
            _debug.logic("all_implied_ids_search_unsupported", operator=operator)
            return NotImplemented
        group_definitions = self._get_group_definitions()
        ids = [*value, *group_definitions.get_subset_ids(value)]
        _debug.logic(
            "all_implied_ids_search",
            operator=operator,
            given=len(value),
            expanded=len(ids),
        )
        return [("id", operator, ids)]

    @api.depends("implied_by_ids.all_implied_by_ids")
    def _compute_all_implied_by_ids(self) -> None:
        group_definitions = self._get_group_definitions()
        _debug.perf.count("all_implied_by_ids_computed", groups=len(self))
        for g in self:
            g.all_implied_by_ids = g.ids + group_definitions.get_subset_ids(g.ids)

    def _search_all_implied_by_ids(self, operator: str, value: Any) -> list:
        if operator in ("any", "not any") and isinstance(value, Domain):
            value = self.search(value).ids
            operator = "in" if operator == "any" else "not in"
        elif operator not in ("in", "not in"):
            _debug.logic("all_implied_by_ids_search_unsupported", operator=operator)
            return NotImplemented

        group_definitions = self._get_group_definitions()
        ids = [*value, *group_definitions.get_superset_ids(value)]
        _debug.logic(
            "all_implied_by_ids_search",
            operator=operator,
            given=len(value),
            expanded=len(ids),
        )

        return [("id", operator, ids)]

    def _get_user_type_groups(self) -> Self:
        return self.sudo().browse(self._get_user_type_group_ids())

    @api.model
    @tools.ormcache(cache="groups")
    def _get_user_type_group_ids(self) -> tuple[int, ...]:
        return tuple(
            gid
            for xid in (
                "base.group_user",
                "base.group_portal",
                "base.group_public",
            )
            if (
                gid := self.env["ir.model.data"]._xmlid_to_res_id(
                    xid, raise_if_not_found=False
                )
            )
        )

    def _compute_disjoint_ids(self) -> None:
        user_type_groups = self._get_user_type_groups()
        _debug.perf.count(
            "disjoint_ids_computed",
            groups=len(self),
            user_type_groups=len(user_type_groups),
        )
        for group in self:
            if group in user_type_groups:
                group.disjoint_ids = user_type_groups - group
            else:
                group.disjoint_ids = False

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        groups = super().create(vals_list)
        if not projecting():
            self.env["res.users.grant"]._follow_membership(
                groups._user_membership(), ()
            )
        _debug.lifecycle("create", count=len(groups))
        self.env["ir.access"]._clear_access_caches()
        self.env.registry.clear_cache("groups")
        return groups

    def unlink(self) -> bool:
        _debug.lifecycle("unlink", count=len(self))
        res = super().unlink()
        _debug.logic("administrator_checked", groups=self.ids, by="unlink")
        self.env["res.users"]._check_at_least_one_administrator()
        self.env["ir.access"]._clear_access_caches()
        self.env.registry.clear_cache("groups")
        return res

    def _user_membership(self) -> set[tuple[int, int]]:
        return {
            (user_id, group.id)
            for group in self.sudo()
            for user_id in group.with_context(active_test=False).user_ids.ids
        }

    def _add_implied_group(self, implied_group: Self) -> None:
        groups = self.filtered(lambda g: implied_group not in g.all_implied_ids)
        _debug.lifecycle(
            "implied_group_added", implied=implied_group.id, groups=groups.ids
        )
        groups.write({"implied_ids": [Command.link(implied_group.id)]})

    def _remove_group(self, implied_group: Self) -> None:
        groups = self.all_implied_ids.filtered(lambda g: implied_group in g.implied_ids)
        _debug.lifecycle(
            "implied_group_removed", implied=implied_group.id, groups=groups.ids
        )
        groups.write({"implied_ids": [Command.unlink(implied_group.id)]})

    def _compute_view_group_hierarchy(self) -> None:
        self.view_group_hierarchy = self._get_view_group_hierarchy()

    @api.model
    @tools.ormcache("self.env.lang", cache="groups")
    def _get_view_group_hierarchy(self) -> dict[str, Any]:
        hierarchy = {
            "groups": {
                group.id: {
                    "id": group.id,
                    "name": group.name,
                    "comment": group.comment,
                    "privilege_id": group.privilege_id.id,
                    "disjoint_ids": group.disjoint_ids.ids,
                    "implied_ids": group.implied_ids.ids,
                    "all_implied_ids": group.all_implied_ids.ids,
                    "all_implied_by_ids": group.all_implied_by_ids.ids,
                }
                for group in self.search([("is_privilege", "=", False)])
            },
            "privileges": {
                privilege.id: {
                    "id": privilege.id,
                    "name": privilege.name,
                    "category_id": privilege.category_id.id,
                    "description": privilege.description,
                    "placeholder": privilege.placeholder,
                    "group_ids": self._get_privilege_group_ids_sorted(privilege),
                }
                for privilege in self.env["res.groups.privilege"].search([])
            },
            "categories": [
                {
                    "id": category.id,
                    "name": category.name,
                    "privilege_ids": category.privilege_ids.sorted(lambda p: p.sequence)
                    .filtered(lambda p: p.group_ids)
                    .ids,
                }
                for category in self.env["ir.module.category"].search(
                    [("privilege_ids.group_ids", "!=", False)]
                )
            ],
        }
        _debug.perf.count(
            "view_group_hierarchy_computed",
            lang=self.env.lang,
            groups=len(hierarchy["groups"]),
            privileges=len(hierarchy["privileges"]),
            categories=len(hierarchy["categories"]),
        )
        return hierarchy

    @api.model
    def _get_privilege_group_ids_sorted(self, privilege: Any) -> list[int]:
        privilege_groups = privilege.group_ids
        implied_count = {
            group.id: (
                len(group.all_implied_ids & privilege_groups)
                if group.privilege_id
                else 0
            )
            for group in privilege_groups
        }
        return [
            group.id
            for group in privilege_groups.sorted(
                lambda g: (implied_count[g.id], g.sequence, g.id)
            )
        ]

    @api.model
    @tools.ormcache(cache="groups")
    def _get_group_definitions(self) -> SetDefinitions:
        groups = self.sudo().search([], order="id")
        id_to_ref = groups.get_external_id()
        data = {
            group.id: {
                "ref": id_to_ref[group.id] or str(group.id),
                "supersets": group.implied_ids.ids,
                "disjoints": group.disjoint_ids.ids,
            }
            for group in groups
        }
        _debug.perf.count("group_definitions_computed", groups=len(data))
        return SetDefinitions(data)

    @api.model
    def _is_feature_enabled(self, group_reference: str) -> bool:
        enabled = (
            self.env["res.users"]
            .sudo()
            .browse(api.SUPERUSER_ID)
            ._has_group(group_reference)
        )
        _debug.logic("feature_enabled", group=group_reference, enabled=enabled)
        return enabled

    @api.depends("all_user_ids")
    def _compute_all_users_count(self) -> None:
        self.all_implied_by_ids.fetch(["user_ids"])
        for group in self:
            group.all_users_count = len(group.all_implied_by_ids.user_ids)
        _debug.perf.count("all_users_count_computed", groups=len(self))

    def action_show_all_users(self) -> dict[str, Any]:
        self.check_singleton()
        return {
            "name": self.env._(
                "Users and implied users of %(group)s", group=self.display_name
            ),
            "view_mode": "list,form",
            "res_model": "res.users",
            "type": "ir.actions.act_window",
            "context": {
                "create": False,
                "delete": False,
                "form_view_ref": "base.view_users_form",
            },
            "domain": [("all_group_ids", "in", self.ids)],
            "target": "current",
        }
