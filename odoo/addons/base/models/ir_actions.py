import base64
import collections.abc
import re
from collections import defaultdict
from contextlib import suppress
from typing import Any, Self

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.libs.datetime.tz import timezone
from odoo.libs.numbers.float_utils import float_compare
from odoo.tools import _, frozendict
from odoo.tools.safe_eval import safe_eval

_RX_ACTION_PATH = re.compile(r"[a-z][a-z0-9_-]*")


def _readable_stored_field_names(records: models.Model) -> list[str]:
    """Readable-field names that are real ORM fields on ``records``' model.

    IRA-L2: ``_get_readable_fields()`` also lists virtual client-side keys (e.g.
    ``close`` on act_url, ``effect``/``infos`` on act_window_close); passing
    those to ``read()`` logs a spurious "Invalid field" warning, so filter them.
    """
    return [name for name in records._get_readable_fields() if name in records._fields]


def _safe_eval_dict(expr: str | None, eval_ctx: dict[str, Any], default: Any) -> Any:
    """safe_eval a stored expression expected to yield a dict, degrading to
    ``default`` when it is missing, un-evaluable, or not a dict.

    Stored expressions come from data files, imports or manual edits; a corrupt
    value must degrade rather than make the action unreadable/un-launchable.
    """
    try:
        result = safe_eval(expr or "{}", eval_ctx)
    except Exception:
        return default
    return result if isinstance(result, dict) else default


class IrActionsActions(models.Model):
    _name = "ir.actions.actions"
    _description = "Actions"
    _table = "ir_actions"
    _order = "name, id"
    _allow_sudo_commands = False

    name = fields.Char(string="Action Name", required=True, translate=True)
    type = fields.Char(string="Action Type", required=True)
    xml_id = fields.Char(compute="_compute_xml_id", string="External ID")
    path = fields.Char(string="Path to show in the URL")
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

    _path_unique = models.Constraint(
        "unique(path)",
        "Path to show in the URL must be unique! Please choose another one.",
    )

    # Path prefixes/values reserved by the web router; an action may not claim
    # them (enforced by _check_path).
    _RESERVED_PATH_PREFIXES = ("m-", "action-")
    _RESERVED_PATHS = ("new",)

    @api.constrains("path")
    def _check_path(self) -> None:
        """Validate action path format and cross-table uniqueness."""
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

        # Cross-table uniqueness: PostgreSQL table inheritance makes the _path_unique
        # index apply per child table only (an act_window and an act_url could both
        # claim one path), so one grouped query over the parent table catches
        # duplicates across every child.
        # See https://www.postgresql.org/docs/current/ddl-inherit.html#DDL-INHERIT-CAVEATS
        paths = [action.path for action in self if action.path]
        duplicates = paths and self.env["ir.actions.actions"]._read_group(
            [("path", "in", paths)],
            groupby=["path"],
            aggregates=["__count"],
            having=[("__count", ">", 1)],
        )
        if duplicates:
            raise ValidationError(
                _(
                    "Path to show in the URL must be unique! Already in use: %s",
                    ", ".join(path for path, __count in duplicates),
                )
            )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        res = super().create(vals_list)
        # _get_bindings selects only rows with binding_model_id set, so a new
        # action can stale its cache only when created bound. Check the created
        # records (not vals_list) to also catch bindings set via defaults.
        if any(action.binding_model_id for action in res):
            self.env.registry.clear_cache()
        return res

    # IRA-L3: fields that never feed _get_bindings(), so writing ONLY these
    # cannot stale the bindings ormcache. Fail-safe allowlist: any field not
    # listed (including unknown/module-added ones) triggers a full cache clear.
    # Do NOT add binding inputs: name, type, binding_model_id, binding_type,
    # binding_view_types, res_model, group_ids, sequence, domain.
    _CACHE_SAFE_FIELDS = frozenset(
        {
            "help",
            "path",
            "context",
            "limit",
            "target",
            "view_mode",
            "mobile_view_mode",
            "res_id",
            "view_id",
            "view_ids",
            "search_view_id",
            "cache",
            "filter",
            "usage",
            "url",
            "tag",
            "params",
            "params_store",
            # ir.actions.server runtime-value/config fields: they drive what the
            # action *does* when executed, never how/where it is bound, and no
            # ormcache reads them. So editing a server action's Python code (a
            # routine dev op) no longer wipes the whole registry cache.
            "code",
            "value",
            "evaluation_type",
            "selection_value",
            "update_boolean_value",
            "update_field_id",
            "update_path",
            "link_field_id",
            "resource_ref",
            "webhook_url",
            "webhook_field_ids",
        }
    )

    def write(self, vals: dict[str, Any]) -> bool:
        res = super().write(vals)
        # get_bindings() caches action data; refresh it unless this write
        # touched only binding-irrelevant fields.
        if not vals.keys() <= self._CACHE_SAFE_FIELDS:
            self.env.registry.clear_cache()
        return res

    def unlink(self) -> bool:
        """Manually cascade-delete dependent records before unlinking.

        PostgreSQL ``ON DELETE CASCADE`` does not propagate across table
        inheritance boundaries (ir_actions → ir_act_window, etc.), so the
        ``ondelete="cascade"`` on fields referencing ``ir.actions.actions`` is
        never a working FK; delete ir.actions.todo, ir.filters and
        ir.embedded.actions dependents explicitly.
        """
        todos = self.env["ir.actions.todo"].search([("action_id", "in", self.ids)])
        todos.unlink()
        filters = (
            self.env["ir.filters"]
            .with_context(active_test=False)
            .search([("action_id", "in", self.ids)])
        )
        filters.unlink()
        # Without this, dangling ir.embedded.actions rows violate the action_id
        # XOR python_method CHECK and crash the web client. Sudo so the cascade
        # doesn't depend on the deleting user's ACLs. The
        # _unlink_if_action_deletable ondelete hook still applies: a
        # data-file-seeded embedded action blocks manual deletion with a
        # UserError, while module uninstall (MODULE_UNINSTALL_FLAG) skips it.
        embedded_actions = (
            self.env["ir.embedded.actions"]
            .sudo()
            .search([("action_id", "in", self.ids)])
        )
        embedded_actions.unlink()
        res = super().unlink()
        # self.get_bindings() depends on action records
        self.env.registry.clear_cache()
        return res

    @api.ondelete(at_uninstall=True)
    def _unlink_check_home_action(self) -> None:
        # Sudo required on write: the global res.users record rule hides portal
        # users whose companies don't overlap with the current admin's companies.
        # Without sudo, orphaned action_id references would remain on hidden users.
        self.env["res.users"].with_context(active_test=False).search(
            [("action_id", "in", self.ids)]
        ).sudo().write({"action_id": None})

    def _compute_xml_id(self) -> None:
        res = self.get_external_id()
        for record in self:
            record.xml_id = res.get(record.id)

    @api.model
    def _get_eval_context(self, action: Any = None) -> dict[str, Any]:
        """Evaluation context to pass to safe_eval.

        ``action`` is unused here but kept in the signature for the
        ``ir.actions.server`` override, which derives a record-aware context
        from it; callers pass it uniformly.
        """
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
        """Retrieve the actions bound to the given model.

        :return: dict mapping each binding type to a list of action dicts (as
                 returned by ``read`` on the action record).
        """
        result = {}
        for action_type, all_actions in self._get_bindings(model_name).items():
            actions = []
            for action in all_actions:
                action_data = dict(action)
                groups = action_data.pop("group_ids", None)
                if groups and not any(
                    self.env.user.has_group(ext_id) for ext_id in groups
                ):
                    # the user may not perform this action
                    continue
                res_model = action_data.pop("res_model", None)
                if res_model and not self.env["ir.model.access"].check(
                    res_model, mode="read", raise_exception=False
                ):
                    # the user won't be able to read records
                    continue
                actions.append(action_data)
            if actions:
                result[action_type] = actions
        return result

    @tools.ormcache("model_name", "self.env.lang")
    def _get_bindings(self, model_name: str) -> frozendict:
        """Retrieve bound actions for a model, batch-reading per action type."""
        cr = self.env.cr
        result = defaultdict(list)

        # flush_all (not flush_model): the raw SQL queries the ir_actions parent
        # table, but pending writes may sit on any child model (ir_act_window, …).
        self.env.flush_all()
        cr.execute(
            """
            SELECT a.id, a.type, a.binding_type
              FROM ir_actions a
              JOIN ir_model m ON a.binding_model_id = m.id
             WHERE m.model = %s
          ORDER BY a.id
        """,
            [model_name],
        )
        rows = cr.fetchall()
        if not rows:
            return frozendict(result)

        # Group by action model type for batch browse+read (O(k) queries
        # where k = distinct action types, instead of O(n) per action)
        by_model = defaultdict(list)
        for action_id, action_model, binding_type in rows:
            by_model[action_model].append((action_id, binding_type))

        # Pre-compute read fields per action model (field set is static per
        # model class, so introspection only needs to happen once per type).
        optional_fields = ("group_ids", "res_model", "sequence", "domain")
        fields_cache: dict[str, list[str]] = {}

        # First pass: read each action type and collect the union of group ids.
        pending: list[tuple[str, dict]] = []  # (binding_type, action_data)
        all_group_ids: set[int] = set()
        for action_model, entries in by_model.items():
            if action_model not in self.env.registry:
                continue
            action_ids = [e[0] for e in entries]
            binding_map = dict(entries)  # action_id -> binding_type

            # IRA-L1: standard ORM exists() (correct post-flush). The
            # act_window exists() override caching an id-set was removed as
            # unsafe for NewId / unflushed records.
            actions = self.env[action_model].sudo().browse(action_ids).exists()
            if not actions:
                continue
            if action_model not in fields_cache:
                model_fields = actions._fields
                fields_cache[action_model] = [
                    "name",
                    "binding_view_types",
                    *(f for f in optional_fields if f in model_fields),
                ]
            for action_data in actions.read(fields_cache[action_model]):
                if "domain" in action_data and not action_data.get("domain"):
                    action_data.pop("domain")
                if action_data.get("group_ids"):
                    all_group_ids.update(action_data["group_ids"])
                pending.append((binding_map[action_data["id"]], action_data))

        # Resolve every group's external id in a single batch rather than once
        # per action (the same groups are shared across many actions).
        group_xmlids = (
            self.env["res.groups"].browse(all_group_ids)._ensure_xml_id()
            if all_group_ids
            else {}
        )
        for binding_type, action_data in pending:
            if action_data.get("group_ids"):
                action_data["group_ids"] = [
                    group_xmlids[gid] for gid in action_data["group_ids"]
                ]
            result[binding_type].append(frozendict(action_data))

        # Sort every bucket by sequence (server actions carry one; act_window/
        # report default to 0). sorted() is stable, so the SQL "ORDER BY a.id"
        # tie-break holds. Freezing to tuples keeps the ormcached result
        # immutable against caller mutation.
        return frozendict(
            {
                key: tuple(sorted(val, key=lambda vals: vals.get("sequence", 0)))
                for key, val in result.items()
            }
        )

    @api.model
    def _for_xml_id(self, full_xml_id: str) -> dict[str, Any]:
        """Return the action content for the provided xml_id

        :param full_xml_id: the fully qualified external id of the action,
            i.e. ``module.name``
        :return: A read() view of the ir.actions.action safe for web use
        """
        record = self.env.ref(full_xml_id)
        # Guard: the xml_id must resolve to an ir.actions.* record, not an
        # arbitrary model that happens to own this external id.
        if not isinstance(self.env[record._name], self.env.registry[self._name]):
            raise ValidationError(
                _("Record %s is not a valid action type", full_xml_id)
            )
        return record._get_action_dict()

    def _get_action_dict(self) -> dict[str, Any]:
        """Return the action content for this action record.

        Sudo because ir.actions.* is restricted to group_system yet any user
        must load action definitions to render the UI. Only readable *stored*
        fields are fetched (IRA-L2), keeping sensitive/virtual keys out.
        """
        self.ensure_one()
        return self.sudo().read(_readable_stored_field_names(self))[0]

    def _get_readable_fields(self) -> set[str]:
        """Return the fields safe to read (via /web/action/load or _for_xml_id).

        Only web-client fields belong here; server-side content must be
        accessed manually with superuser.
        """
        return {
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


class IrActionsAct_Window(models.Model):
    _name = "ir.actions.act_window"
    _description = "Action Window"
    _table = "ir_act_window"
    _inherit = ["ir.actions.actions"]
    _order = "name, id"
    _allow_sudo_commands = False

    type = fields.Char(default="ir.actions.act_window")
    view_id = fields.Many2one("ir.ui.view", string="View Ref.", ondelete="set null")
    domain = fields.Char(
        string="Domain Value",
        help="Optional domain filtering of the destination data, as a Python expression",
    )
    context = fields.Char(
        string="Context Value",
        default="{}",
        required=True,
        help="Context dictionary as Python expression, empty by default (Default: {})",
    )
    res_id = fields.Integer(
        string="Record ID",
        help="Database ID of record to open in form view, when ``view_mode`` is set to 'form' only",
    )
    res_model = fields.Char(
        string="Destination Model",
        required=True,
        help="Model name of the object to open in the view window",
    )
    target = fields.Selection(
        [
            ("current", "Current Window"),
            ("new", "New Window"),
            ("fullscreen", "Full Screen"),
            ("main", "Main action of Current Window"),
        ],
        default="current",
        string="Target Window",
    )
    view_mode = fields.Char(
        required=True,
        default="list,form",
        help="Comma-separated list of allowed view modes, such as 'form', 'list', 'calendar', etc. (Default: list,form)",
    )
    mobile_view_mode = fields.Char(
        default="kanban",
        help="First view mode in mobile and small screen environments (default='kanban'). If it can't be found among available view modes, the same mode as for wider screens is used)",
    )
    usage = fields.Char(
        string="Action Usage",
        help="Used to filter menu and home actions from the user form.",
    )
    view_ids = fields.One2many(
        "ir.actions.act_window.view",
        "act_window_id",
        string="No of Views",
    )
    views = fields.Binary(
        compute="_compute_views",
        help="This function field computes the ordered list of views that should be enabled "
        "when displaying the result of an action, federating view mode, views and "
        "reference view. The result is returned as an ordered list of pairs (view_id,view_mode).",
    )
    limit = fields.Integer(default=80, help="Default limit for the list view")
    group_ids = fields.Many2many(
        "res.groups",
        "ir_act_window_group_rel",
        "act_id",
        "gid",
        string="Groups",
    )
    search_view_id = fields.Many2one("ir.ui.view", string="Search View Ref.")
    embedded_action_ids = fields.One2many(
        "ir.embedded.actions", compute="_compute_embedded_actions"
    )
    filter = fields.Boolean()
    cache = fields.Boolean(
        string="Data Caching",
        default=True,
        help="If enabled, this action will cache the related data used in list, Kanban and form views with the aim to increase the loading speed",
    )

    @api.constrains("res_model", "binding_model_id")
    def _check_model(self) -> None:
        for action in self:
            if action.res_model not in self.env:
                raise ValidationError(
                    _(
                        "Invalid model name “%s” in action definition.",
                        action.res_model,
                    )
                )
            if (
                action.binding_model_id
                and action.binding_model_id.model not in self.env
            ):
                raise ValidationError(
                    _(
                        "Invalid model name “%s” in action definition.",
                        action.binding_model_id.model,
                    )
                )

    @api.constrains("view_mode")
    def _check_view_mode(self) -> None:
        for rec in self:
            modes = rec.view_mode.split(",")
            if len(modes) != len(set(modes)):
                raise ValidationError(
                    _(
                        "The modes in view_mode must not be duplicated: %s",
                        modes,
                    )
                )
            if any(" " in mode for mode in modes):
                raise ValidationError(_("No spaces allowed in view_mode: “%s”", modes))

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        for vals in vals_list:
            # Default the action name to the target model's description. IRA-L4:
            # guard membership so an invalid res_model raises the friendly
            # _check_model ValidationError instead of a raw KeyError here.
            if not vals.get("name") and vals.get("res_model") in self.env:
                vals["name"] = self.env[vals["res_model"]]._description
        # super() clears the registry cache when a created action is bound.
        return super().create(vals_list)

    def _compute_embedded_actions(self) -> None:
        embedded_actions = (
            self.env["ir.embedded.actions"]
            .search([("parent_action_id", "in", self.ids)])
            .filtered(lambda x: x.is_visible)
        )
        grouped = embedded_actions.grouped("parent_action_id")
        for action in self:
            action.embedded_action_ids = grouped.get(
                action, self.env["ir.embedded.actions"]
            )

    @api.depends("view_ids.view_mode", "view_mode", "view_id.type")
    def _compute_views(self) -> None:
        """Compute the ordered ``(view_id, view_mode)`` pairs for this action.

        Resolves the precedence between the ``view_mode`` string, the
        ``view_ids`` o2m, and the ``view_id`` m2o.
        """
        for act in self:
            views = [(view.view_id.id, view.view_mode) for view in act.view_ids]
            got_modes = {view.view_mode for view in act.view_ids}
            missing_modes = [
                mode for mode in act.view_mode.split(",") if mode not in got_modes
            ]
            # If the reference view_id covers one of the missing modes, place it
            # first so it takes precedence over a generic (False, mode) entry.
            if act.view_id and act.view_id.type in missing_modes:
                missing_modes.remove(act.view_id.type)
                views.append((act.view_id.id, act.view_id.type))
            views.extend((False, mode) for mode in missing_modes)
            act.views = views

    def read(
        self,
        fields: collections.abc.Sequence[str] | None = None,
        load: str = "_classic_read",
    ) -> list[ValuesType]:
        """Enrich the ``help`` field with the target model's empty-list help."""
        result = super().read(fields, load=load)
        if fields and "help" not in fields:
            return result
        # Source res_model/context from the record, not `values`, so read(['help'])
        # behaves like a full read. eval_ctx is shared and safe_eval copies it
        # internally, so build it once.
        eval_ctx = dict(self.env.context)
        records = {rec.id: rec for rec in self}
        for values in result:
            record = records.get(values["id"])
            model = record.res_model if record else values.get("res_model")
            if model not in self.env:
                continue
            raw_context = record.context if record else values.get("context", "{}")
            # Eval against the request context so the stored expression sees the
            # same variables (lang, uid, ...) as the requesting client.
            ctx = _safe_eval_dict(raw_context, eval_ctx, {})
            values["help"] = (
                self.with_context(**ctx)
                .env[model]
                .get_empty_list_help(values.get("help", ""))
            )
        return result

    def _get_readable_fields(self) -> set[str]:
        return super()._get_readable_fields() | {
            "context",
            "cache",
            "mobile_view_mode",
            "domain",
            "filter",
            "group_ids",
            "limit",
            "res_id",
            "res_model",
            "search_view_id",
            "target",
            "view_id",
            "view_mode",
            "views",
            "embedded_action_ids",
        }

    def _get_action_dict(self) -> dict[str, Any]:
        """Override to expand embedded actions into full read() dicts."""
        result = super()._get_action_dict()
        if embedded_action_ids := result["embedded_action_ids"]:
            embedded = self.env["ir.embedded.actions"].browse(embedded_action_ids)
            result["embedded_action_ids"] = embedded.read(
                _readable_stored_field_names(embedded)
            )
        return result


VIEW_TYPES = [
    ("list", "List"),
    ("form", "Form"),
    ("graph", "Graph"),
    ("pivot", "Pivot"),
    ("calendar", "Calendar"),
    ("kanban", "Kanban"),
]


class IrActionsAct_WindowView(models.Model):
    _name = "ir.actions.act_window.view"
    _description = "Action Window View"
    _table = "ir_act_window_view"
    _rec_name = "view_id"
    _order = "sequence,id"
    _allow_sudo_commands = False

    sequence = fields.Integer()
    view_id = fields.Many2one("ir.ui.view", string="View")
    view_mode = fields.Selection(VIEW_TYPES, string="View Type", required=True)
    act_window_id = fields.Many2one(
        "ir.actions.act_window",
        string="Action",
        ondelete="cascade",
        index="btree_not_null",
    )
    multi = fields.Boolean(
        string="On Multiple Doc.",
        help="If set to true, the action will not be displayed on the right toolbar of a form view.",
    )

    _unique_mode_per_action = models.UniqueIndex("(act_window_id, view_mode)")


class IrActionsAct_Window_Close(models.Model):
    _name = "ir.actions.act_window_close"
    _description = "Action Window Close"
    _inherit = ["ir.actions.actions"]
    _table = "ir_actions"
    _allow_sudo_commands = False

    type = fields.Char(default="ir.actions.act_window_close")

    def _get_readable_fields(self) -> set[str]:
        return super()._get_readable_fields() | {
            # Virtual keys, not stored fields: 'effect' drives the rainbowman,
            # 'infos' is awaited by the action_service.
            "effect",
            "infos",
        }


class IrActionsAct_Url(models.Model):
    _name = "ir.actions.act_url"
    _description = "Action URL"
    _table = "ir_act_url"
    _inherit = ["ir.actions.actions"]
    _order = "name, id"
    _allow_sudo_commands = False

    type = fields.Char(default="ir.actions.act_url")
    url = fields.Text(string="Action URL", required=True)
    target = fields.Selection(
        [
            ("new", "New Window"),
            ("self", "This Window"),
            ("download", "Download"),
        ],
        string="Action Target",
        default="new",
        required=True,
    )

    def _get_readable_fields(self) -> set[str]:
        return super()._get_readable_fields() | {
            "target",
            "url",
            # 'close' is not a stored field; the act_url JS executor reads it to
            # dispatch a follow-up window-close (ir.actions.act_window_close).
            "close",
        }


class IrActionsClient(models.Model):
    _name = "ir.actions.client"
    _description = "Client Action"
    _inherit = ["ir.actions.actions"]
    _table = "ir_act_client"
    _order = "name, id"
    _allow_sudo_commands = False

    type = fields.Char(default="ir.actions.client")
    tag = fields.Char(
        string="Client action tag",
        required=True,
        help="An arbitrary string, interpreted by the client"
        " according to its own needs and wishes. There "
        "is no central tag repository across clients.",
    )
    target = fields.Selection(
        [
            ("current", "Current Window"),
            ("new", "New Window"),
            ("fullscreen", "Full Screen"),
            ("main", "Main action of Current Window"),
        ],
        default="current",
        string="Target Window",
    )
    res_model = fields.Char(
        string="Destination Model",
        help="Optional model, mostly used for needactions.",
    )
    context = fields.Char(
        string="Context Value",
        default="{}",
        required=True,
        help="Context dictionary as Python expression, empty by default (Default: {})",
    )
    params = fields.Binary(
        compute="_compute_params",
        inverse="_inverse_params",
        string="Supplementary arguments",
        help="Arguments sent to the client along with the view tag",
    )
    params_store = fields.Binary(
        string="Params storage", readonly=True, attachment=False
    )

    @api.depends("params_store")
    def _compute_params(self) -> None:
        self_bin = self.with_context(bin_size=False, bin_size_params_store=False)
        for record, record_bin in zip(self, self_bin, strict=True):
            stored = record_bin.params_store
            if not stored:
                record.params = stored
                continue
            # IRA-L5: a corrupt params_store must not make the client action
            # un-loadable — degrade to False rather than crash. Not
            # _safe_eval_dict: a non-dict payload is legitimate here (see
            # _inverse_params) and the default is an explicit False. Eval
            # context is only `uid` — params are plain client arguments.
            try:
                record.params = safe_eval(stored, {"uid": self.env.uid})
            except Exception:
                record.params = False

    def _inverse_params(self) -> None:
        for record in self:
            params = record.params
            record.params_store = repr(params) if isinstance(params, dict) else params

    def _get_readable_fields(self) -> set[str]:
        return super()._get_readable_fields() | {
            "context",
            "params",
            "res_model",
            "tag",
            "target",
        }


class IrActionsTodo(models.Model):
    _name = "ir.actions.todo"
    _description = "Configuration Wizards"
    _rec_name = "action_id"
    _order = "sequence, id"
    _allow_sudo_commands = False

    name = fields.Char()
    sequence = fields.Integer(default=10)
    action_id = fields.Many2one(
        "ir.actions.actions",
        string="Action",
        required=True,
        index=True,
    )
    state = fields.Selection(
        [("open", "To Do"), ("done", "Done")],
        string="Status",
        default="open",
        required=True,
    )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        todos = super().create(vals_list)
        if any(todo.state == "open" for todo in todos):
            self.ensure_one_open_todo()
        return todos

    def write(self, vals: dict[str, Any]) -> bool:
        res = super().write(vals)
        if vals.get("state", "") == "open":
            self.ensure_one_open_todo()
        return res

    def unlink(self) -> bool:
        if self:
            # ValueError: env.ref() raises when xmlid doesn't exist (e.g. during uninstall)
            with suppress(ValueError):
                todo_open_menu = self.env.ref("base.open_menu")
                # don't remove base.open_menu todo but set its original action
                if todo_open_menu in self:
                    todo_open_menu.action_id = self.env.ref(
                        "base.action_client_base_menu"
                    ).id
                    self -= todo_open_menu
        return super().unlink()

    @api.model
    def ensure_one_open_todo(self) -> None:
        open_todo = self.search(
            [("state", "=", "open")], order="sequence asc, id desc", offset=1
        )
        if open_todo:
            open_todo.write({"state": "done"})

    def action_launch(self) -> dict[str, Any]:
        """Launch Action of Wizard"""
        self.ensure_one()

        self.write({"state": "done"})

        # Load action
        action_type = self.action_id.type
        action = self.env[action_type].browse(self.action_id.id)

        result = action.read()[0]
        if action_type != "ir.actions.act_window":
            return result
        result.setdefault("context", "{}")

        # Open a specific record when res_id is provided in the context
        # Eval context: only `user` — todo wizard contexts reference the
        # launching user, never the request context.
        ctx = _safe_eval_dict(result["context"], {"user": self.env.user}, {})
        if ctx.get("res_id"):
            result["res_id"] = ctx.pop("res_id")

        # disable log for automatic wizards
        ctx["disable_log"] = True

        result["context"] = ctx

        return result

    def action_open(self) -> bool:
        """Set the configuration wizard to TODO state"""
        return self.write({"state": "open"})
