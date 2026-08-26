import base64
import logging
import re
from collections import defaultdict
from typing import Any, Self

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.libs.datetime import timezone
from odoo.libs.numbers import float_compare
from odoo.tools import SQL, _, frozendict
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

_RX_ACTION_PATH = re.compile(r"[a-z][a-z0-9_-]*")

_BINDING_ACCESS_MODEL = "__opens_model"


def _eval_dict_or_default(
    expr: str | None, eval_ctx: dict[str, Any], default: Any
) -> Any:
    try:
        result = safe_eval(expr or "{}", eval_ctx)
    except Exception as exc:
        if not isinstance(exc.__cause__, NameError):
            _logger.warning("Malformed action expression %r: %s", expr, exc)
        return default
    if isinstance(result, dict):
        return result
    _logger.warning(
        "Action expression %r evaluates to %s, not a dict", expr, type(result).__name__
    )
    return default


def _eval_list_or_default(
    expr: str | None, eval_ctx: dict[str, Any], default: Any
) -> Any:
    try:
        result = safe_eval(expr or "[]", eval_ctx)
    except Exception:
        return default
    return result if isinstance(result, list) else default


class IrActionsActions(models.Model):
    _name = "ir.actions.actions"
    _description = "Actions"
    _table = "ir_actions"
    _table_inheritance_root = "ir_actions"
    _order = "name, id"
    _allow_sudo_commands = False

    name = fields.Char(string="Action Name", required=True, translate=True)
    type = fields.Char(string="Action Type", required=True)
    xml_id = fields.Char(compute="_compute_xml_id", string="External ID")
    path = fields.Char(string="Path to show in the URL", copy=False)
    help = fields.Html(
        string="Action Description",
        translate=True,
        help="Optional help text for the users with a description of the target view, such as its usage and purpose.",
    )
    binding_model_id = fields.Many2one(
        "ir.model",
        ondelete="cascade",
        help="Setting a value makes this action available in the sidebar for the given model.",
    )
    binding_type = fields.Selection(
        [("action", "Action"), ("report", "Report")],
        required=True,
        default="action",
    )
    binding_view_types = fields.Char(default="list,form")

    _RESERVED_PATH_PREFIXES = ("m-", "action-")
    _RESERVED_PATHS = ("new",)

    _BINDING_SQL_SELECTED = ("type", "binding_type")
    _BINDING_SQL_JOINED = "binding_model_id"
    _BINDING_READ_FIELDS = ("name", "binding_view_types")
    _BINDING_OPTIONAL_FIELDS = ("group_ids", "res_model", "sequence", "domain")

    @api.constrains("type")
    def _check_type(self) -> None:
        for action in self:
            if action.type != action._name:
                raise ValidationError(
                    _(
                        "Action type “%(type)s” does not match the model this action "
                        "is stored in (“%(model)s”).",
                        type=action.type,
                        model=action._name,
                    )
                )

    @api.constrains("binding_model_id")
    def _check_binding_model(self) -> None:
        for action in self:
            model = action.binding_model_id.model
            if model and model not in self.env:
                raise ValidationError(
                    _("Invalid model name “%s” in action definition.", model)
                )

    @api.constrains("path")
    def _check_path(self) -> None:
        for action in self:
            if not action.path:
                continue
            if not _RX_ACTION_PATH.fullmatch(action.path):
                raise ValidationError(
                    _(
                        "The path should contain only lowercase alphanumeric characters, underscore, and dash, and it should start with a letter."
                    )
                )
            for prefix in self._RESERVED_PATH_PREFIXES:
                if action.path.startswith(prefix):
                    raise ValidationError(_("'%s' is a reserved prefix.", prefix))
            if action.path in self._RESERVED_PATHS:
                raise ValidationError(
                    _("'%s' is reserved, and can not be used as path.", action.path)
                )

    @api.constrains("binding_view_types")
    def _check_binding_view_types(self) -> None:
        self._check_view_type_vocabulary("binding_view_types")

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        res = super().create(vals_list)
        if any(action.path for action in res):
            res._sync_path_reservations()
        if any(action._is_cached_registry_wide() for action in res):
            self.env.registry.clear_cache()
        return res

    def write(self, vals: dict[str, Any]) -> bool:
        invalidate = bool(self) and (
            not vals.keys().isdisjoint(self._get_fields_invalidating_always())
            or (
                not self._get_fields_invalidating_when_cached().isdisjoint(vals)
                and any(action._is_cached_registry_wide() for action in self)
            )
        )
        res = super().write(vals)
        if "path" in vals:
            self._sync_path_reservations()
        if invalidate:
            self.env.registry.clear_cache()
        return res

    def unlink(self) -> bool:
        if self._name == "ir.actions.actions":
            return self._unlink_as_concrete_types()
        with self.env.cr.savepoint():
            self._apply_ondelete_unenforced()
            res = super().unlink()
        self.env.registry.clear_cache()
        return res

    def _unlink_as_concrete_types(self) -> bool:
        by_model = defaultdict(list)
        for action_id, model_name in self._get_model_names_concrete().items():
            by_model[model_name].append(action_id)
        result = True
        with self.env.cr.savepoint():
            for model_name, ids in by_model.items():
                if model_name != self._name:
                    result = self.env[model_name].browse(ids).unlink() and result
                    continue
                records = self.browse(ids)
                records._apply_ondelete_unenforced()
                result = super(IrActionsActions, records).unlink() and result
        self.env.registry.clear_cache()
        return result

    def _apply_ondelete_unenforced(self) -> None:
        if not self:
            return
        found = defaultdict(list)
        for model_name, field_name, ondelete in self._get_fields_ondelete_unenforced():
            references = (
                self.env[model_name]
                .sudo()
                .with_context(active_test=False)
                .search([(field_name, "in", self.ids)])
            )
            if references:
                found[ondelete].append((model_name, field_name, references))

        if restricted := found.get("restrict"):
            raise ValidationError(
                _(
                    "Cannot delete this action: %s",
                    ", ".join(
                        _(
                            "%(count)s %(model)s record(s) still reference it",
                            count=len(references),
                            model=self.env[model_name]._description,
                        )
                        for model_name, __, references in restricted
                    ),
                )
            )
        for __, __, references in found["cascade"]:
            references.unlink()
        for __, field_name, references in found["set null"]:
            references.write({field_name: False})

        values = [
            f"{model_name},{action_id}"
            for model_name in {self._name, "ir.actions.actions"}
            for action_id in self.ids
        ]
        for model_name, field_name in self._get_selections_ondelete_unenforced():
            referring = (
                self.env[model_name]
                .sudo()
                .with_context(active_test=False)
                .search([(field_name, "in", values)])
            )
            if referring:
                referring.write({field_name: False})

        for (
            model_name,
            field_name,
            relation,
            column,
        ) in self._get_relations_ondelete_unenforced():
            self.env.cr.execute(
                SQL(
                    "DELETE FROM %s WHERE %s IN %s",
                    SQL.identifier(relation),
                    SQL.identifier(column),
                    tuple(self.ids),
                )
            )
            self.env[model_name].invalidate_model([field_name])

    def _compute_xml_id(self) -> None:
        res = self.get_external_id()
        for record in self:
            record.xml_id = res.get(record.id)

    @api.model
    @tools.ormcache(cache="stable")
    def _get_model_names_in_tree(self) -> frozenset[str]:
        root_table = self.env.registry["ir.actions.actions"]._table
        return frozenset(
            name
            for name, model in self.env.registry.items()
            if not model._abstract and model._table_inheritance_root == root_table
        )

    @api.model
    @tools.ormcache(cache="stable")
    def _get_fields_invalidating_when_cached(self) -> frozenset[str]:
        return frozenset(
            (
                *self._BINDING_SQL_SELECTED,
                self._BINDING_SQL_JOINED,
                *self._BINDING_READ_FIELDS,
                *self._BINDING_OPTIONAL_FIELDS,
                "path",
            )
        )

    @api.model
    @tools.ormcache(cache="stable")
    def _get_fields_invalidating_always(self) -> frozenset[str]:
        target = self._get_field_target_model()
        return frozenset(("binding_model_id", "path", *filter(None, [target])))

    @api.model
    @tools.ormcache(cache="stable")
    def _get_view_types_for_window(self) -> frozenset[str]:
        view_modes = (
            self.env["ir.actions.act_window.view"]
            ._fields["view_mode"]
            .get_values(self.env)
        )
        return frozenset(view_modes)

    @api.model
    @tools.ormcache(cache="stable")
    def _get_model_names_in_root_table(self) -> frozenset[str]:
        root = self.env.registry["ir.actions.actions"]
        return frozenset(
            name
            for name, model in self.env.registry.items()
            if model._table == root._table
        )

    @api.model
    @tools.ormcache(cache="stable")
    def _get_fields_ondelete_unenforced(self) -> tuple[tuple[str, str, str], ...]:
        root_models = self._get_model_names_in_root_table()
        return tuple(
            sorted(
                (model_name, field.name, field.ondelete)
                for model_name, model in self.env.registry.items()
                if not model._abstract
                for field in model._fields.values()
                if field.type == "many2one"
                and field.store
                and not field.related
                and field.comodel_name in root_models
            )
        )

    @api.model
    @tools.ormcache(cache="stable")
    def _get_relations_ondelete_unenforced(
        self,
    ) -> tuple[tuple[str, str, str, str], ...]:
        root_models = self._get_model_names_in_root_table()
        return tuple(
            sorted(
                {
                    (model_name, field.name, field.relation, column)
                    for model_name, model in self.env.registry.items()
                    if not model._abstract
                    for field in model._fields.values()
                    if field.type == "many2many" and field.store
                    for column, end in (
                        (field.column2, field.comodel_name),
                        (field.column1, model_name),
                    )
                    if end in root_models
                }
            )
        )

    @api.model
    @tools.ormcache(cache="stable")
    def _get_selections_ondelete_unenforced(self) -> tuple[tuple[str, str], ...]:
        tree_models = self._get_model_names_in_tree()
        return tuple(
            sorted(
                (model_name, field.name)
                for model_name, model in self.env.registry.items()
                if not model._abstract
                for field in model._fields.values()
                if field.type == "reference"
                and field.store
                and (
                    not isinstance(field.selection, list)
                    or any(value in tree_models for value, __ in field.selection)
                )
            )
        )

    @api.model
    @tools.ormcache(cache="stable")
    def _get_model_names_by_table(self) -> frozendict:
        by_table = defaultdict(list)
        for model_name in self._get_model_names_in_tree():
            by_table[self.env[model_name]._table].append(model_name)
        return frozendict({table: tuple(sorted(n)) for table, n in by_table.items()})

    def _get_field_target_model(self) -> str:
        return ""

    def _get_model_names_concrete(self) -> dict[int, str]:
        if not self:
            return {}
        root = self.env.registry["ir.actions.actions"]
        by_table = self._get_model_names_by_table()
        for model_name in self._get_model_names_in_tree():
            self.env[model_name].flush_model()
        self.env.cr.execute(
            SQL(
                "SELECT a.id, c.relname, a.type FROM %s a"
                " JOIN pg_class c ON c.oid = a.tableoid WHERE a.id IN %s",
                SQL.identifier(root._table),
                tuple(self.ids),
            )
        )
        found = {}
        for action_id, table, action_type in self.env.cr.fetchall():
            candidates = by_table.get(table) or (root._name,)
            if action_type in candidates:
                found[action_id] = action_type
            else:
                found[action_id] = candidates[0] if len(candidates) == 1 else root._name
        return {action_id: found.get(action_id, root._name) for action_id in self.ids}

    def _get_action_concrete(self) -> Self:
        self.ensure_one()
        [model_name] = self._get_model_names_concrete().values()
        return self.env[model_name].browse(self.id)

    @api.model
    def _get_action_by_path(self, path: str) -> Self:
        action = (
            self.env["ir.actions.path"]
            .sudo()
            .search([("path", "=", path)], limit=1)
            .action_id
        )
        return action._get_action_concrete() if action else action

    @api.model
    def _eval_action_domain(self, domain: str | None, **names: Any) -> list:
        """An action's stored ``domain``, read the way ``_eval_action_context`` reads a context.

        The same argument, one field over: a stored domain is an expression, not a
        literal. ``hr.mail_activity_plan_action``'s names ``allowed_company_ids``, so
        ``ast.literal_eval`` raises on it -- which is why its caller had resorted to
        ``str.replace("allowed_company_ids", str(ids))`` before literal-eval'ing, a
        substitution that only ever works for the one name the caller thought of.

        ``names`` supplies what the caller knows and its own context does not, and
        wins over ``env.context`` -- so a caller can hand in the fallback it used to
        substitute rather than lose the whole domain when the name is absent.

        The scale is the same as the context case: **111 of the 330** stored
        ``act_window`` domains in ``addons/`` name something rather than being a
        literal (``project`` 19, ``mrp`` 8, ``stock`` 6), so a third of them raise
        under ``ast.literal_eval``. Re-derive by literal-eval'ing every
        ``<field name="domain">`` under an ``ir.actions.act_window`` record in
        ``addons/**/*.xml`` and counting the failures.

        Four call sites still literal-eval a stored domain bare
        (``account_journal_dashboard``, ``hr_holidays``, ``im_livechat``, ``mrp``,
        plus ``account_followup`` and ``web_studio`` in enterprise). Each happens to
        read an action whose domain IS a literal today -- checked, not assumed -- so
        they are one action-configuration change from failing rather than currently
        broken. Converting them is a separate sweep.
        """
        eval_context = {
            **self._get_eval_context(self),
            **self.env.context,
            **names,
        }
        return _eval_list_or_default(domain, eval_context, [])

    @api.model
    def _eval_action_context(self, context: str | None, **names: Any) -> dict:
        eval_context = {
            **self._get_eval_context(self),
            **self.env.context,
            **names,
        }
        return _eval_dict_or_default(context, eval_context, {})

    @api.model
    def _get_eval_context(self, action: Any) -> dict[str, Any]:
        return {
            "uid": self.env.uid,
            "user": self.env.user,
            "time": tools.safe_eval.time,
            "datetime": tools.safe_eval.datetime,
            "dateutil": tools.safe_eval.dateutil,
            "timezone": timezone,
            "float_compare": float_compare,
            "b64encode": base64.b64encode,
            "b64decode": base64.b64decode,
            "Command": Command,
        }

    @api.model
    def get_bindings(self, model_name: str) -> dict[str, list[dict[str, Any]]]:
        Access = self.env["ir.model.access"]
        if model_name not in self.env or not Access.check(
            model_name, mode="read", raise_exception=False
        ):
            return {}

        result = {}
        for binding_type, all_actions in self._get_bindings(model_name).items():
            actions = []
            for action in all_actions:
                action_data = dict(action)
                groups = action_data.pop("group_ids", None)
                if groups and not self.env.user.has_any_group_id(groups):
                    continue
                opens = action_data.pop(_BINDING_ACCESS_MODEL, None)
                if opens and (
                    opens not in self.env
                    or not Access.check(opens, mode="read", raise_exception=False)
                ):
                    continue
                actions.append(action_data)
            if actions:
                result[binding_type] = actions
        return result

    @tools.ormcache("model_name", "self.env.lang")
    def _get_bindings(self, model_name: str) -> frozendict:
        cr = self.env.cr
        result = defaultdict(list)

        for name in self._get_model_names_in_tree():
            self.env[name].flush_model()
        self.env["ir.model"].flush_model()
        cr.execute(
            SQL(
                "SELECT a.id, %s FROM %s a JOIN %s m ON a.%s = m.id"
                " WHERE m.model = %s ORDER BY a.id",
                SQL(", ").join(
                    SQL("a.%s", SQL.identifier(name))
                    for name in self._BINDING_SQL_SELECTED
                ),
                SQL.identifier(self.env.registry["ir.actions.actions"]._table),
                SQL.identifier(self.env["ir.model"]._table),
                SQL.identifier(self._BINDING_SQL_JOINED),
                model_name,
            )
        )
        rows = cr.fetchall()
        if not rows:
            return frozendict(result)

        by_model = defaultdict(list)
        for action_id, action_model, binding_type in rows:
            by_model[action_model].append((action_id, binding_type))

        for action_model, entries in by_model.items():
            if action_model not in self.env.registry:
                continue
            binding_map = dict(entries)

            actions = self.env[action_model].sudo().browse(binding_map.keys()).exists()
            if not actions:
                continue
            opens_field = actions._get_field_target_model()
            read_fields = [
                *self._BINDING_READ_FIELDS,
                *(f for f in self._BINDING_OPTIONAL_FIELDS if f in actions._fields),
            ]
            if opens_field and opens_field not in read_fields:
                read_fields.append(opens_field)
            for action_data in actions.read(read_fields):
                if "domain" in action_data and not action_data.get("domain"):
                    action_data.pop("domain")
                if "group_ids" in action_data:
                    action_data["group_ids"] = tuple(action_data["group_ids"])
                if opens_field:
                    action_data[_BINDING_ACCESS_MODEL] = action_data.pop(opens_field)
                result[binding_map[action_data["id"]]].append(frozendict(action_data))

        return frozendict(
            {
                key: tuple(
                    sorted(val, key=lambda vals: (vals.get("sequence", 0), vals["id"]))
                )
                for key, val in result.items()
            }
        )

    @api.model
    def _get_action_dict_by_xml_id(self, full_xml_id: str) -> dict[str, Any]:
        record = self.env.ref(full_xml_id)
        if not isinstance(self.env[record._name], self.env.registry[self._name]):
            msg = f"{full_xml_id} is a {record._name}, not a {self._name}"
            raise ValueError(msg)
        return record._get_action_dict()

    def _get_action_dict(self) -> dict[str, Any]:
        self.ensure_one()
        return self.sudo().read(sorted(self._get_fields_readable()))[0]

    def _get_fields_readable(self) -> frozenset[str]:
        return frozenset(
            {
                "binding_model_id",
                "binding_type",
                "binding_view_types",
                "display_name",
                "help",
                "id",
                "name",
                "type",
                "xml_id",
                "path",
            }
        )

    def _get_keys_client_only(self) -> frozenset[str]:
        return frozenset()

    def _sync_path_reservations(self) -> None:
        Reservation = self.env["ir.actions.path"].sudo()
        reserved = {
            reservation.action_id.id: reservation
            for reservation in Reservation.search([("action_id", "in", self.ids)])
        }
        to_create = []
        for action in self:
            reservation = reserved.get(action.id)
            if not action.path:
                if reservation:
                    reservation.unlink()
            elif not reservation:
                to_create.append({"path": action.path, "action_id": action.id})
            elif reservation.path != action.path:
                reservation.path = action.path
        if to_create:
            Reservation.create(to_create)

    def _check_view_type_vocabulary(self, field_name: str) -> None:
        allowed = self._get_view_types_for_window()
        for action in self:
            unknown = [
                mode
                for mode in (action[field_name] or "").split(",")
                if mode and mode not in allowed
            ]
            if unknown:
                raise ValidationError(
                    _(
                        "Unknown view type(s) %(unknown)s in %(field)s. Allowed: %(allowed)s",
                        unknown=", ".join(unknown),
                        field=field_name,
                        allowed=", ".join(sorted(allowed)),
                    )
                )

    def _is_cached_registry_wide(self) -> bool:
        self.ensure_one()
        return bool(self.binding_model_id or self.path)
