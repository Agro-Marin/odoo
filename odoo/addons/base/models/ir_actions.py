import base64
import collections.abc
import re
from collections import defaultdict
from typing import Any, Self

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.libs.datetime.tz import timezone
from odoo.libs.numbers.float_utils import float_compare
from odoo.tools import SQL, _, frozendict
from odoo.tools.safe_eval import safe_eval

_RX_ACTION_PATH = re.compile(r"[a-z][a-z0-9_-]*")


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
    _table_inheritance_root = "ir_actions"
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

    _RESERVED_PATH_PREFIXES = ("m-", "action-")
    _RESERVED_PATHS = ("new",)

    _BINDING_SQL_FIELDS = ("type", "binding_type", "binding_model_id")
    _BINDING_READ_FIELDS = ("name", "binding_view_types")
    _BINDING_OPTIONAL_FIELDS = ("group_ids", "res_model", "sequence", "domain")

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

        paths = [action.path for action in self if action.path]
        duplicates = paths and self.env["ir.actions.actions"].sudo()._read_group(
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
        if any(action._is_cached_registry_wide() for action in res):
            self.env.registry.clear_cache()
        return res

    def _is_cached_registry_wide(self) -> bool:
        """Whether this action's data can be inside a registry-level cache.

        Only bound actions reach :meth:`_get_bindings`, and only pathed ones
        reach ``ir.ui.menu.load_menus``; an action that is neither cannot
        invalidate anything, so renaming it must not flush every worker's
        caches.  The companion of :meth:`_cache_invalidating_fields`, which
        answers the same question for a ``vals`` dict.
        """
        self.ensure_one()
        return bool(self.binding_model_id or self.path)

    @api.model
    @tools.ormcache(cache="stable")
    def _cache_invalidating_fields(self) -> frozenset[str]:
        """Fields whose value ends up inside a registry-level (ormcache) entry.

        Writing one of them must clear that cache; writing anything else must
        not, or renaming a single action flushes the ACL, xml-id and menu
        caches of every worker.

        ``base`` memoises the inputs of :meth:`_get_bindings`, plus ``path``,
        which ``ir.ui.menu.load_menus`` embeds as each menu's ``action_path``.
        A module that memoises further action data extends this set rather
        than editing a core list of everything it is *not* allowed to cache.
        """
        return frozenset(
            (
                *self._BINDING_SQL_FIELDS,
                *self._BINDING_READ_FIELDS,
                *self._BINDING_OPTIONAL_FIELDS,
                "path",
            )
        )

    _CACHE_MEMBERSHIP_FIELDS = ("binding_model_id", "path")

    def write(self, vals: dict[str, Any]) -> bool:
        """Write, clearing registry caches only when this action is in one.

        Writing a field that no cache stores never invalidates anything, and
        neither does writing a cached field of an action no cache holds — but
        writing ``binding_model_id`` or ``path`` *changes* which caches hold it,
        so the membership test is unusable and the clear unconditional.
        """
        membership_changed = not vals.keys().isdisjoint(self._CACHE_MEMBERSHIP_FIELDS)
        clear = membership_changed or (
            not self._cache_invalidating_fields().isdisjoint(vals)
            and any(action._is_cached_registry_wide() for action in self)
        )
        res = super().write(vals)
        if clear:
            self.env.registry.clear_cache()
        return res

    @api.model
    @tools.ormcache(cache="stable")
    def _root_model_names(self) -> frozenset[str]:
        """Models sharing the ``ir_actions`` table, i.e. valid comodels of a
        reference to "any action"."""
        root = self.env.registry["ir.actions.actions"]
        return frozenset(
            name
            for name, model in self.env.registry.items()
            if model._table == root._table
        )

    @api.model
    @tools.ormcache(cache="stable")
    def _unenforced_reference_fields(self) -> tuple[tuple[str, str, str], ...]:
        """``(model, field, ondelete)`` triples PostgreSQL cannot cascade for us.

        ``ir_actions`` is a table-inheritance root: an FK pointing at it would
        not see the rows that actually live in ``ir_act_window`` & co, so the
        ORM creates none (see ``BaseModel._is_table_inheritance_root``) and
        every ``ondelete`` declared on a field targeting ``ir.actions.actions``
        is inert. :meth:`unlink` applies them in Python.

        Derived from the registry so that references declared by any module
        (embedded actions, filters, studio approvals, a user's home action)
        are honoured without listing them here.

        Anchored on the root table rather than ``self._table``: every subtype
        shares the ``ir_actions`` id space, so deleting an act_window has to
        sweep the references that point at ``ir.actions.actions``.

        ``ondelete`` is normalised the way ``Many2one.update_db_foreign_key``
        would have: a *related* field never goes through ``setup_nonrelated``,
        so its policy is still ``None`` here and would otherwise reach the
        dispatch below as an unhandled fourth value.
        """
        root_models = self._root_model_names()
        return tuple(
            sorted(
                (model_name, field.name, field.ondelete or "set null")
                for model_name, model in self.env.registry.items()
                if not model._abstract
                for field in model._fields.values()
                if field.type == "many2one" and field.comodel_name in root_models
            )
        )

    @api.model
    @tools.ormcache(cache="stable")
    def _unenforced_reference_relations(self) -> tuple[tuple[str, str], ...]:
        """``(relation_table, column)`` pairs of many2many links to an action.

        Same root-table problem as :meth:`_unenforced_reference_fields`, but a
        relation row is not a record: nothing owns it, so :meth:`unlink` deletes
        it in SQL rather than through a policy.
        """
        root_models = self._root_model_names()
        return tuple(
            sorted(
                {
                    (field.relation, field.column2)
                    for model in self.env.registry.values()
                    if not model._abstract
                    for field in model._fields.values()
                    if field.type == "many2many"
                    and field.store
                    and field.comodel_name in root_models
                }
            )
        )

    def unlink(self) -> bool:
        """Apply the unenforceable ``ondelete`` rules, then unlink.

        The sweep runs inside a savepoint so that a reference the ORM refuses to
        delete — an ``@api.ondelete`` guard on a cascade target, an access
        error, a constraint — undoes the deletions already made instead of
        leaving the caller with an action that still exists and referencing
        records that no longer do.  A real foreign key is atomic; this has to be
        too, because ``ValidationError``/``UserError`` leave the transaction
        usable and callers do catch them.
        """
        if self._name == "ir.actions.actions":
            return self._unlink_as_concrete_types()
        with self.env.cr.savepoint():
            self._apply_unenforced_ondelete()
            res = super().unlink()
        self.env.registry.clear_cache()
        return res

    def _unlink_as_concrete_types(self) -> bool:
        """Unlink through each action's own model rather than the root one.

        Deleting an ``ir_act_window`` row as an ``ir.actions.actions`` works in
        PostgreSQL — the row is visible through the inherited table and the
        DELETE reaches it — but every ORM-side cleanup keyed on the model name
        misses: the ``ir.model.data`` row keeps a dangling xml id, and the
        subtype's ``@api.ondelete`` guards never run.
        """
        by_type = defaultdict(list)
        for values in self.sudo().read(["type"]):
            by_type[values["type"]].append(values["id"])
        result = True
        for action_type, ids in by_type.items():
            if action_type != self._name and action_type in self.env:
                result = self.env[action_type].browse(ids).unlink() and result
                continue
            records = self.browse(ids)
            with self.env.cr.savepoint():
                records._apply_unenforced_ondelete()
                result = super(IrActionsActions, records).unlink() and result
            self.env.registry.clear_cache()
        return result

    def _apply_unenforced_ondelete(self) -> None:
        """Enforce, in policy order, the ``ondelete`` rules of every reference.

        ``restrict`` is resolved for all models before anything is destroyed:
        the alternative is to discover it midway and abort having already
        cascaded, and the alphabetical order the registry sweep happens to
        produce is not a deletion order.
        """
        if not self:
            return
        found = defaultdict(list)
        for model_name, field_name, ondelete in self._unenforced_reference_fields():
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
        for relation, column in self._unenforced_reference_relations():
            self.env.cr.execute(
                SQL(
                    "DELETE FROM %s WHERE %s IN %s",
                    SQL.identifier(relation),
                    SQL.identifier(column),
                    tuple(self.ids),
                )
            )

    def _compute_xml_id(self) -> None:
        res = self.get_external_id()
        for record in self:
            record.xml_id = res.get(record.id)

    @api.model
    def _get_eval_context(self, action: Any) -> dict[str, Any]:
        """Evaluation context to pass to safe_eval.

        ``action`` is unused here but required in the signature for the
        ``ir.actions.server`` override, which derives a record-aware context
        from it; callers pass it uniformly.

        It is required rather than defaulting to ``None`` so that the base and
        that override stay call-compatible. An optional parameter here would
        let a caller holding an ``ir.actions.actions`` reference invoke this
        argument-less and fail on a server action, which is the narrowing the
        override-signature lint rejects.
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

        The bound model is access-checked first.  Filtering only on each
        action's destination model covers ``ir.actions.act_window`` and
        ``ir.actions.client``, which carry ``res_model``, but leaves the name
        and domain of every ``ir.actions.server`` and ``ir.actions.report``
        binding readable by anyone who calls this over RPC for a model they
        cannot open — those name their model ``model_id``/``model``, so the
        destination check never fires for them.

        :return: dict mapping each binding type to a list of action dicts (as
                 returned by ``read`` on the action record).
        """
        Access = self.env["ir.model.access"]
        if model_name not in self.env or not Access.check(
            model_name, mode="read", raise_exception=False
        ):
            return {}

        result = {}
        for action_type, all_actions in self._get_bindings(model_name).items():
            actions = []
            for action in all_actions:
                action_data = dict(action)
                groups = action_data.pop("group_ids", None)
                if groups and not self.env.user.has_any_group_id(groups):
                    continue
                res_model = action_data.pop("res_model", None)
                if res_model and not Access.check(
                    res_model, mode="read", raise_exception=False
                ):
                    continue
                actions.append(action_data)
            if actions:
                result[action_type] = actions
        return result

    @tools.ormcache("model_name", "self.env.lang")
    def _get_bindings(self, model_name: str) -> frozendict:
        """Retrieve bound actions for a model, batch-reading per action type.

        ``group_ids`` stays a tuple of database ids.  Translating it to external
        identifiers here — as the per-user filter used to need — makes this
        cached *read* create an ``ir.model.data`` row for every group that has
        none, and the two live in different cache groups: ``ir.model.data``
        clears only ``groups`` on insert, so a request that rolls back after
        populating this entry leaves the identifier cached here and nowhere
        else, and the binding disappears for every user until ``default`` is
        cleared.
        """
        cr = self.env.cr
        result = defaultdict(list)

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
            read_fields = [
                *self._BINDING_READ_FIELDS,
                *(f for f in self._BINDING_OPTIONAL_FIELDS if f in actions._fields),
            ]
            for action_data in actions.read(read_fields):
                if "domain" in action_data and not action_data.get("domain"):
                    action_data.pop("domain")
                if "group_ids" in action_data:
                    action_data["group_ids"] = tuple(action_data["group_ids"])
                result[binding_map[action_data["id"]]].append(frozendict(action_data))

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
        if not isinstance(self.env[record._name], self.env.registry[self._name]):
            raise ValidationError(
                _("Record %s is not a valid action type", full_xml_id)
            )
        return record._get_action_dict()

    def _get_action_dict(self) -> dict[str, Any]:
        """Return the action content for this action record.

        Sudo because ir.actions.* is restricted to group_system yet any user
        must load action definitions to render the UI.
        """
        self.ensure_one()
        return self.sudo().read(sorted(self._get_readable_fields()))[0]

    def _get_readable_fields(self) -> frozenset[str]:
        """ORM field names safe to send to the web client.

        Only web-client fields belong here; server-side content must be
        accessed manually with superuser. Every name must be a real field:
        this set is passed to ``read()``.
        """
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

    def _get_client_only_keys(self) -> frozenset[str]:
        """Keys the web client understands that are not ORM fields.

        Action dicts built in Python may carry them — ``effect`` for the
        rainbow man, ``infos``, ``close`` — so ``clean_action`` has to keep
        them and must not report them as stray custom properties. They are
        deliberately absent from :meth:`_get_readable_fields`, which feeds
        ``read()``.
        """
        return frozenset()


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
    all_embedded_action_ids = fields.One2many(
        "ir.embedded.actions",
        "parent_action_id",
        string="All Embedded Actions",
    )
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
            if not all(modes):
                raise ValidationError(
                    _("Empty view mode in view_mode: “%s”", rec.view_mode)
                )
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
        vals_list = [
            (
                vals
                if vals.get("name") or vals.get("res_model") not in self.env
                else {**vals, "name": self.env[vals["res_model"]]._description}
            )
            for vals in vals_list
        ]
        return super().create(vals_list)

    @api.depends("all_embedded_action_ids.is_visible")
    @api.depends_context("active_id", "active_model", "uid")
    def _compute_embedded_actions(self) -> None:
        """Embedded actions of this action that are visible in the current context.

        Visibility is entirely context-derived (``is_visible`` depends on the
        active record and the user), so without the ``depends_context`` above
        the first record's result would be served for every other record of
        the same transaction.

        Depends on the plain one2many rather than searching: a ``search`` gives
        the ORM no dependency to invalidate, so an embedded action created in
        this transaction stayed invisible until something else flushed the
        field cache.
        """
        for action in self:
            action.embedded_action_ids = action.all_embedded_action_ids.filtered(
                "is_visible"
            )

    @api.depends(
        "view_ids.view_mode",
        "view_ids.view_id",
        "view_ids.sequence",
        "view_mode",
        "view_id.type",
    )
    def _compute_views(self) -> None:
        """Compute the ordered ``(view_id, view_mode)`` pairs for this action.

        Resolves the precedence between the ``view_mode`` string, the
        ``view_ids`` o2m, and the ``view_id`` m2o.

        Re-sorts ``view_ids`` instead of trusting its order: writing a line's
        ``sequence`` invalidates this compute but not the cached one2many, so
        the recomputation would otherwise read the pre-write ordering.
        """
        for act in self:
            lines = act.view_ids.sorted(lambda view: (view.sequence, view.id))
            views = [(view.view_id.id, view.view_mode) for view in lines]
            got_modes = {view.view_mode for view in lines}
            missing_modes = [
                mode for mode in act.view_mode.split(",") if mode not in got_modes
            ]
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
        eval_ctx = dict(self.env.context)
        records = {record.id: record for record in self}
        for values in result:
            record = records[values["id"]]
            if record.res_model not in self.env:
                continue
            ctx = _safe_eval_dict(record.context, eval_ctx, {})
            values["help"] = (
                self.with_context(**ctx)
                .env[record.res_model]
                .get_empty_list_help(values.get("help", ""))
            )
        return result

    def _get_readable_fields(self) -> frozenset[str]:
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
                sorted(embedded._get_readable_fields())
            )
        return result


NON_WINDOW_VIEW_TYPES = ("search", "qweb")
"""``ir.ui.view`` types an action window can never display.

``view_mode`` below must stay ``ir.ui.view.type`` minus these — a module adding
a view type has to extend both, and the pair drifting apart means an act_window
line that cannot be created for a view type that exists.  Deriving one from the
other is not an option: ``selection_add`` requires a list-valued base selection,
and only that form carries the ``ondelete`` policies that clean up act_window
lines when the module owning a view type is uninstalled.  A post-install test
enforces the invariant instead.
"""

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

    def _get_client_only_keys(self) -> frozenset[str]:
        return super()._get_client_only_keys() | {
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

    def _get_readable_fields(self) -> frozenset[str]:
        return super()._get_readable_fields() | {
            "target",
            "url",
        }

    def _get_client_only_keys(self) -> frozenset[str]:
        return super()._get_client_only_keys() | {"close"}


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
    @api.depends_context("uid")
    def _compute_params(self) -> None:
        """Evaluate the stored params expression, degrading to ``False``.

        Same contract as :func:`_safe_eval_dict`: the expression comes from data
        files, imports or manual edits, and a corrupt one must not make the
        action un-launchable.  ``params`` is not required to be a dict, so it
        cannot use that helper.
        """
        self_bin = self.with_context(bin_size=False, bin_size_params_store=False)
        for record, record_bin in zip(self, self_bin, strict=True):
            stored = record_bin.params_store
            if not stored:
                record.params = stored
                continue
            try:
                record.params = safe_eval(stored, {"uid": self.env.uid})
            except Exception:
                record.params = False

    def _inverse_params(self) -> None:
        for record in self:
            params = record.params
            record.params_store = repr(params) if isinstance(params, dict) else params

    def _get_readable_fields(self) -> frozenset[str]:
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
        ondelete="cascade",
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
        todos._close_other_open_todos()
        return todos

    def write(self, vals: dict[str, Any]) -> bool:
        res = super().write(vals)
        if vals.get("state") == "open":
            self._close_other_open_todos()
        return res

    def unlink(self) -> bool:
        """Unlink, but restore ``base.open_menu`` to its original action instead.

        ``suppress`` covers only the two lookups: a database where either xml id
        is missing has nothing to preserve, whereas a failure of the write below
        is a real error and must not be swallowed into a silent full delete.
        """
        todos = self
        try:
            todo_open_menu = self.env.ref("base.open_menu")
            default_action = self.env.ref("base.action_client_base_menu")
        except ValueError:
            pass
        else:
            if todo_open_menu in todos:
                todo_open_menu.action_id = default_action.id
                todos -= todo_open_menu
        return super(IrActionsTodo, todos).unlink()

    def _close_other_open_todos(self) -> None:
        """Keep a single open todo: the one just opened wins.

        Closing every open todo but the lowest-``sequence`` one instead would
        include the record whose write triggered this, so opening a wizard
        would report success and leave it done.
        """
        keep = self.filtered(lambda todo: todo.state == "open")[:1]
        if not keep:
            return
        self.search([("state", "=", "open"), ("id", "not in", keep.ids)]).write(
            {"state": "done"}
        )

    def action_launch(self) -> dict[str, Any]:
        """Mark the wizard done and return its action for the web client."""
        self.ensure_one()
        self.state = "done"

        action = self.env[self.action_id.type].browse(self.action_id.id)
        result = action._get_action_dict()
        if action._name != "ir.actions.act_window":
            return result

        eval_context = {**action._get_eval_context(action), **self.env.context}
        ctx = _safe_eval_dict(result.get("context"), eval_context, {})
        if ctx.get("res_id"):
            result["res_id"] = ctx.pop("res_id")
        ctx["disable_log"] = True
        result["context"] = ctx
        return result

    def action_open(self) -> bool:
        """Reopen the configuration wizard (state ``open``)."""
        return self.write({"state": "open"})
