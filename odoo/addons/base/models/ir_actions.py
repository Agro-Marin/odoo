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
"""Key under which :meth:`_get_bindings` stashes the model an action opens.

Not a field name: the types spell it ``res_model``/``model``/``model_name``,
and ``get_bindings`` has to pop one key rather than guess among three. It never
reaches the browser -- ``get_views`` ships the rest of the dict as a toolbar.
"""


def _safe_eval_dict(expr: str | None, eval_ctx: dict[str, Any], default: Any) -> Any:
    """safe_eval a stored expression expected to yield a dict, degrading to
    ``default`` when it is missing, un-evaluable, or not a dict.

    Stored expressions come from data files, imports or manual edits; a corrupt
    value must degrade rather than make the action unreadable/un-launchable.

    Deliberately silent, and not a place to add a log line: most failures here
    are healthy.  ``ir.actions.act_window.read`` evaluates ``context`` with
    nothing but the environment's own context bound, so every action whose
    context mentions ``active_id`` or ``active_ids`` — 10 of the 134 shipped by
    ``base``, ``web`` and ``mail`` alone — raises ``NameError`` on every read
    and degrades exactly as intended.  Warning on that buries the rare real
    corruption under a flood of correct behaviour.
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
    """Per-table, and therefore weaker than what ``ir.actions.path`` enforces.

    Kept for the index it builds — ``path`` is looked up on every ``/odoo/<path>``
    request — and because a same-subtype duplicate is rejected here first, one
    statement earlier and with the same message.  It cannot reject anything the
    reservation would allow, so the two can never disagree.
    """

    _RESERVED_PATH_PREFIXES = ("m-", "action-")
    _RESERVED_PATHS = ("new",)

    _BINDING_SQL_FIELDS = ("type", "binding_type", "binding_model_id")
    _BINDING_READ_FIELDS = ("name", "binding_view_types")
    _BINDING_OPTIONAL_FIELDS = ("group_ids", "res_model", "sequence", "domain")

    @api.model
    @tools.ormcache(cache="stable")
    def _inheritance_tree_model_names(self) -> frozenset[str]:
        """Every model stored in the ``ir_actions`` inheritance tree.

        Wider than :meth:`_root_model_names`, which holds only the models whose
        own ``_table`` *is* ``ir_actions``; the subtypes live in child tables.

        The distinction is what makes anything spanning the tree awkward: each
        subtype is an ordinary table, so a constraint declared on the root is
        created once per subtype rather than once for the tree (PostgreSQL does
        not inherit ``UNIQUE`` at all — the ORM builds one index per model's
        own ``_table``), and ``flush_model`` writes out one table at a time.
        ``ir.actions.path`` exists because of the first half of that.
        """
        root_table = self.env.registry["ir.actions.actions"]._table
        return frozenset(
            name
            for name, model in self.env.registry.items()
            if not model._abstract and model._table_inheritance_root == root_table
        )

    @api.constrains("type")
    def _check_type(self) -> None:
        """``type`` must name the model whose table the record lives in.

        It is a denormalised copy of the model name, stored as a free ``Char``
        with a per-subtype default and nothing keeping the two in sync, yet
        every consumer dispatches on it: ``clean_action`` does
        ``env[action["type"]]``, ``ir.actions.todo.action_launch`` browses
        through it, and :meth:`_unlink_as_concrete_types` used to delete
        through it — an act_window claiming ``ir.actions.client`` had its
        ``unlink`` routed to ``ir_act_client``, where the row is not, so
        nothing was deleted and ``unlink`` still returned ``True``.

        Making the two agree at the source is what keeps that unreachable, and
        it is why the dispatch below reads ``tableoid`` instead: the invariant
        holds for every row written from now on, the storage answers for the
        rest.
        """
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
        """The model an action is bound to must still be in the registry.

        On the root because ``binding_model_id`` is a root field: every subtype
        can be bound and every one of them reaches :meth:`_get_bindings`, yet
        only ``ir.actions.act_window`` used to check it.  ``ir.model`` outlives
        the registry entry — a row survives its module's uninstall until the
        registry is rebuilt — so the reference can be valid and the model gone.
        """
        for action in self:
            model = action.binding_model_id.model
            if model and model not in self.env:
                raise ValidationError(
                    _("Invalid model name “%s” in action definition.", model)
                )

    @api.constrains("path")
    def _check_path(self) -> None:
        """Validate the shape of an action path.

        Uniqueness is not checked here any more: it belongs to
        ``ir.actions.path``, whose single unique index spans the tree and holds
        against a concurrent transaction, neither of which a Python re-check
        can do.
        """
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

    def _reserve_paths(self) -> None:
        """Make ``ir.actions.path`` agree with this recordset's ``path``.

        One row per pathed action, none for the rest, so that the reservation
        table's unique index is what decides whether a path is free.
        """
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

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        res = super().create(vals_list)
        if any(vals.get("path") for vals in vals_list):
            res._reserve_paths()
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

    def _menu_access_model_field(self) -> str:
        """Field naming the model whose read access gates this action.

        One question with three spellings — ``res_model``, ``model``,
        ``model_name`` — and three consumers that each need the answer:
        ``ir.ui.menu._visible_menu_ids`` hides a menu whose action opens a
        model the user cannot read, :meth:`get_bindings` hides such a binding,
        and :meth:`_unconditional_clear_fields` clears the cached decision when
        it changes.  All three carried their own literal copy of the mapping (a
        fourth lived in the test asserting two of them agreed), and the copies
        had drifted apart in both directions: menus never checked
        ``ir.actions.client`` while bindings did, and bindings never checked
        ``ir.actions.server``/``ir.actions.report`` while menus did.

        An empty name means no model gates the action, which is the honest
        answer for ``ir.actions.act_url`` and ``ir.actions.act_window_close``.
        """
        return ""

    @api.model
    @tools.ormcache(cache="stable")
    def _unconditional_clear_fields(self) -> frozenset[str]:
        """Fields whose write must clear the cache whatever the action is in.

        Two ways to defeat the membership test in :meth:`write`.
        ``binding_model_id`` and ``path`` *change* which caches hold the
        action, so the test would answer for the wrong side of the write.

        The model gating menu visibility is the subtler one, and the reason
        this is not simply the two of them: the decision is cached for every
        action a menu points at — bound or not, pathed or not — so gating on
        membership leaves a menu on screen after its action is repointed at a
        model the user cannot read.  Its name comes from
        :meth:`_menu_access_model_field` rather than a per-subtype override, so
        that a subtype declaring it cannot forget to invalidate it.
        """
        gating = self._menu_access_model_field()
        return frozenset(("binding_model_id", "path", *filter(None, [gating])))

    def write(self, vals: dict[str, Any]) -> bool:
        """Write, clearing registry caches only when this action is in one.

        Writing a field that no cache stores never invalidates anything, and
        neither does writing a cached field of an action no cache holds.
        :meth:`_unconditional_clear_fields` collects the exceptions.

        A write that reaches no record changes nothing at all, whichever field
        it names; ``ir.ui.menu.write`` guards its own clear the same way.
        """
        clear = bool(self) and (
            not vals.keys().isdisjoint(self._unconditional_clear_fields())
            or (
                not self._cache_invalidating_fields().isdisjoint(vals)
                and any(action._is_cached_registry_wide() for action in self)
            )
        )
        res = super().write(vals)
        if "path" in vals:
            self._reserve_paths()
        if clear:
            self.env.registry.clear_cache()
        return res

    @api.model
    @tools.ormcache(cache="stable")
    def _window_view_types(self) -> frozenset[str]:
        """The view types an action can display, as a comma-separated field.

        Read off ``ir.actions.act_window.view.view_mode`` rather than off
        ``ir.ui.view.type`` minus :data:`NON_WINDOW_VIEW_TYPES`: that selection
        is the list a module extends when it adds a view type an action window
        can render — ``web_gantt``, ``web_cohort``, ``mail`` and the rest each
        do — so it states the vocabulary directly, where the subtraction only
        approximates it and happens to agree because a post-install test says
        it must.  The comma-separated fields and the ``view_ids`` lines then
        cannot offer different modes.
        """
        view_modes = (
            self.env["ir.actions.act_window.view"]
            ._fields["view_mode"]
            .get_values(self.env)
        )
        return frozenset(view_modes)

    def _check_view_type_vocabulary(self, field_name: str) -> None:
        """Reject view types the client has no view to render for.

        ``view_mode`` and its siblings are free ``Char`` fields, so a typo or a
        name from an earlier version reaches the browser intact and the web
        client throws ``View types not defined`` on a payload it cannot render
        — for ``binding_view_types`` that means a sidebar entry that simply
        never appears, with nothing to see server-side.  Validating them here
        turns both into an error at the write, where the offending record is
        still named.
        """
        allowed = self._window_view_types()
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

    @api.constrains("binding_view_types")
    def _check_binding_view_types(self) -> None:
        self._check_view_type_vocabulary("binding_view_types")

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

        Restricted to the fields that own their column, exactly as the m2m
        companion is: only those carry an ``ondelete`` policy, so only those
        can have one applied.  A *related* field's ``ondelete`` is ``None`` —
        an absence, not a policy — because it never reaches
        ``Many2one.setup_nonrelated``; coercing that to ``set null`` and
        writing it would blank a derived column while its source field, which
        is listed here in its own right, still holds the real policy.  A
        non-stored one has no column to sweep at all and would make the
        ``search`` below raise for want of a ``search=`` method.
        """
        root_models = self._root_model_names()
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
    def _unenforced_reference_relations(self) -> tuple[tuple[str, str], ...]:
        """``(relation_table, column)`` pairs of many2many links to an action.

        Same root-table problem as :meth:`_unenforced_reference_fields`, but a
        relation row is not a record: nothing owns it, so :meth:`unlink` deletes
        it in SQL rather than through a policy.

        Both ends are collected, because ``update_db_foreign_keys`` skips a
        root at either of them: ``column2`` of a many2many *pointing at* an
        action, and ``column1`` of one *declared on* an action, which would
        otherwise leave its rows behind on exactly the same reasoning.  Neither
        end has such a field today; the asymmetry only shows up once one
        appears, which is late to discover it.
        """
        root_models = self._root_model_names()
        return tuple(
            sorted(
                {
                    (field.relation, column)
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
    def _unenforced_reference_selections(self) -> tuple[tuple[str, str], ...]:
        """``(model, field)`` pairs of stored ``Reference`` fields naming an action.

        A ``Reference`` keeps ``"model,id"`` in a varchar, so PostgreSQL has no
        foreign key to offer for it against *any* comodel — not just against a
        table-inheritance root.  ``Reference`` checks that its target exists
        when the value is written and never again: ``ir.ui.menu.action`` went
        on naming a deleted act_window, and the menu survived only because
        ``ir.ui.menu._visible_menu_ids`` re-resolves the action on every load
        and drops the ones that have gone.

        Matched on the whole tree, not :meth:`_root_model_names`: the subtypes
        are ordinary tables and do get their foreign keys, but a reference is
        not a foreign key, so a menu pointing at an ``ir.actions.act_window``
        dangles exactly like one pointing at the root.

        There is no policy to read — ``ondelete`` on a ``Reference`` selects
        between selection *values*, not deletion behaviours — so the sweep
        applies the one a nullable foreign key gets when its field declares
        nothing, ``set null``.

        A selection given as a list is read here to skip the references that
        can never hold an action; one given as a method name is kept without
        calling it, both because it may name any model — ``resource_ref`` does
        — and because resolving it would run arbitrary model code while a
        registry-level cache entry is being filled.
        """
        tree_models = self._inheritance_tree_model_names()
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

    @api.model
    @tools.ormcache(cache="stable")
    def _tree_model_names_by_table(self) -> frozendict:
        """Map each table of the ``ir_actions`` tree to the models stored in it.

        One entry per table rather than one model: the root table holds both
        ``ir.actions.actions`` and ``ir.actions.act_window_close``, which is
        precisely the ambiguity :meth:`_concrete_model_names` has to resolve
        some other way.
        """
        by_table = defaultdict(list)
        for model_name in self._inheritance_tree_model_names():
            by_table[self.env[model_name]._table].append(model_name)
        return frozendict({table: tuple(sorted(n)) for table, n in by_table.items()})

    def _concrete_model_names(self) -> dict[int, str]:
        """Map each action id to the model whose table actually holds its row.

        ``tableoid`` names the child table a row lives in, which is exactly
        what decides whether a ``DELETE`` aimed at that table reaches it — so
        it, not the ``type`` column, is what the dispatch has to follow.  The
        constraint on ``type`` keeps the two in agreement, but a row written
        before it existed is only reachable through the storage.

        The root table is the only one holding more than one model, so it is
        the only place ``type`` gets a say — and a harmless one, since both
        models there share a table and differ only in ORM-side cleanup.  Every
        other table names exactly one model, which therefore wins outright: a
        ``type`` that lies must not demote the row to the root, or the dispatch
        deletes it through ``ir_actions`` after all and skips the very cleanup
        it exists to reach.  Ids the query does not return are gone already:
        they map to the root, whose ``unlink`` is a no-op on them, exactly as
        an ordinary model's is.

        Only the tree is flushed, not the transaction: a record created and
        deleted without an intervening flush has no row for ``tableoid`` to
        report on, and that is the whole of what this query needs.  ``unlink``
        flushes everything a few lines later anyway, so a wider flush here only
        moves where an unrelated pending write would fail.
        """
        if not self:
            return {}
        root = self.env.registry["ir.actions.actions"]
        by_table = self._tree_model_names_by_table()
        for model_name in self._inheritance_tree_model_names():
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

    def _as_concrete(self) -> Self:
        """This action browsed through the model that actually stores its row.

        ``ir.actions.actions`` is a view onto the subtypes: reading a record
        through it yields only the root's fields, so every caller wanting the
        real action re-browses.  Three did it by hand off ``type`` — this
        method, ``web``'s URL-path resolver and ``ir.actions.todo`` — which is
        one denormalised column standing between a URL and the right model.
        """
        self.ensure_one()
        [model_name] = self._concrete_model_names().values()
        return self.env[model_name].browse(self.id)

    def _unlink_as_concrete_types(self) -> bool:
        """Unlink through each action's own model rather than the root one.

        Deleting an ``ir_act_window`` row as an ``ir.actions.actions`` works in
        PostgreSQL — the row is visible through the inherited table and the
        DELETE reaches it — but every ORM-side cleanup keyed on the model name
        misses: the ``ir.model.data`` row keeps a dangling xml id, and the
        subtype's ``@api.ondelete`` guards never run.
        """
        by_model = defaultdict(list)
        for action_id, model_name in self._concrete_model_names().items():
            by_model[model_name].append(action_id)
        result = True
        for model_name, ids in by_model.items():
            if model_name != self._name:
                result = self.env[model_name].browse(ids).unlink() and result
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

        Three kinds of reference, three ways of clearing one: a many2one owns
        an ``ondelete`` policy and is a record, so the policy is applied to it;
        a ``Reference`` (:meth:`_unenforced_reference_selections`) is a record
        too but has no policy to own; a many2many row is not a record at all
        and goes in SQL.
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

        values = [
            f"{model_name},{action_id}"
            for model_name in {self._name, "ir.actions.actions"}
            for action_id in self.ids
        ]
        for model_name, field_name in self._unenforced_reference_selections():
            referring = (
                self.env[model_name]
                .sudo()
                .with_context(active_test=False)
                .search([(field_name, "in", values)])
            )
            if referring:
                referring.write({field_name: False})

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

        Two access checks, both on read: the model the action is bound to, and
        the model the action opens.  The second used to be spelled ``res_model``
        and so reached only ``ir.actions.act_window`` and ``ir.actions.client``
        — an ``ir.actions.server`` or ``ir.actions.report`` names it
        ``model_id``/``model``, so a binding whose destination differed from the
        model it was bound to showed its name and domain to anyone who could
        read the latter.  It now asks :meth:`_menu_access_model_field`, the same
        question ``ir.ui.menu`` asks about menus, so the two agree and the
        server and report types are covered.

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
                opens = action_data.pop(_BINDING_ACCESS_MODEL, None)
                if opens and (
                    opens not in self.env
                    or not Access.check(opens, mode="read", raise_exception=False)
                ):
                    continue
                actions.append(action_data)
            if actions:
                result[action_type] = actions
        return result

    @tools.ormcache("model_name", "self.env.lang")
    def _get_bindings(self, model_name: str) -> frozendict:
        """Retrieve bound actions for a model, batch-reading per action type.

        Ordered by ``(sequence, id)``: reading per action type rather than per
        action makes the accumulation order group by model, so id is what
        restores the ``ORDER BY a.id`` the query already asks for.  Only
        ``ir.actions.server`` declares ``sequence``, so every other type sorts
        on the ``0`` default and stays in id order among itself.

        ``group_ids`` stays a tuple of database ids.  Translating it to external
        identifiers here — as the per-user filter used to need — makes this
        cached *read* create an ``ir.model.data`` row for every group that has
        none, and the two live in different cache groups: ``ir.model.data``
        clears only ``groups`` on insert, so a request that rolls back after
        populating this entry leaves the identifier cached here and nowhere
        else, and the binding disappears for every user until ``default`` is
        cleared.

        The model each action opens is resolved here, under sudo, and stored
        under :data:`_BINDING_ACCESS_MODEL` for :meth:`get_bindings` to check
        per user; the field it came from never reaches the payload, which is
        shipped to the browser as a view toolbar.
        """
        cr = self.env.cr
        result = defaultdict(list)

        for name in self._inheritance_tree_model_names():
            self.env[name].flush_model()
        self.env["ir.model"].flush_model()
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
            opens_field = actions._menu_access_model_field()
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


class IrActionsPath(models.Model):
    _name = "ir.actions.path"
    _description = "Action Path"
    _rec_name = "path"
    _allow_sudo_commands = False

    path = fields.Char(required=True)
    action_id = fields.Many2one(
        "ir.actions.actions",
        required=True,
        ondelete="cascade",
        index="btree_not_null",
    )

    _path_unique = models.Constraint(
        "unique(path)",
        "Path to show in the URL must be unique! Please choose another one.",
    )
    _action_unique = models.Constraint(
        "unique(action_id)",
        "An action has at most one path.",
    )

    def init(self) -> None:
        """Reserve a row for every action that already has a path.

        ``ON CONFLICT DO NOTHING`` because a database written before this table
        existed may hold the very duplicates it is meant to prevent; one of
        them wins the reservation and the other keeps its ``path`` column
        unbacked, which is what the warning is for — nothing here can guess
        which of the two should be renamed.
        """
        self.env.cr.execute(
            SQL(
                """
                INSERT INTO %s (path, action_id)
                     SELECT path, id FROM %s WHERE path IS NOT NULL
                ON CONFLICT DO NOTHING
                """,
                SQL.identifier(self._table),
                SQL.identifier(self.env["ir.actions.actions"]._table),
            )
        )
        self.env.cr.execute(
            SQL(
                "SELECT a.id, a.path FROM %s a"
                " LEFT JOIN %s p ON p.action_id = a.id"
                " WHERE a.path IS NOT NULL AND p.id IS NULL",
                SQL.identifier(self.env["ir.actions.actions"]._table),
                SQL.identifier(self._table),
            )
        )
        if unbacked := self.env.cr.fetchall():
            _logger.warning(
                "Duplicate action paths found; these actions keep an "
                "unreachable path and should be renamed: %s",
                ", ".join(
                    f"{path!r} (action {action_id})" for action_id, path in unbacked
                ),
            )


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

    @api.constrains("res_model")
    def _check_model(self) -> None:
        for action in self:
            if action.res_model not in self.env:
                raise ValidationError(
                    _(
                        "Invalid model name “%s” in action definition.",
                        action.res_model,
                    )
                )

    @api.constrains("view_mode", "mobile_view_mode")
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
        self._check_view_type_vocabulary("view_mode")
        self._check_view_type_vocabulary("mobile_view_mode")

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

    def _empty_list_help(self, stored_help: str | bool) -> str | bool:
        """The target model's placeholder for an empty list, from ``help``.

        Evaluated with the action's own ``context`` merged in, because
        ``get_empty_list_help`` implementations read it — ``mail`` builds an
        alias out of ``default_*`` keys, for one.
        """
        self.ensure_one()
        if self.res_model not in self.env:
            return stored_help
        ctx = _safe_eval_dict(self.context, dict(self.env.context), {})
        return (
            self.with_context(**ctx)
            .env[self.res_model]
            .get_empty_list_help(stored_help)
        )

    def _menu_access_model_field(self) -> str:
        return "res_model"

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
        """Expand embedded actions, and fill ``help`` in for an empty list.

        The placeholder belongs to the payload the client launches, not to
        ``read``.  It used to be a ``read`` override, so every reader got it —
        including the action's own form, where ``help`` is an editable field:
        it displayed the model's generated text instead of the stored one, and
        saving the form wrote that text back over whatever its author had
        written.  Nothing else asks ``read`` for an action's help, so nothing
        else loses the placeholder by moving it here.
        """
        result = super()._get_action_dict()
        if embedded_action_ids := result["embedded_action_ids"]:
            embedded = self.env["ir.embedded.actions"].browse(embedded_action_ids)
            result["embedded_action_ids"] = embedded.read(
                sorted(embedded._get_readable_fields())
            )
        result["help"] = self._empty_list_help(result.get("help", ""))
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
            if isinstance(stored, bytes):
                # `params_store` is a non-attachment Binary, so it reads back as
                # bytes even though `_inverse_params` wrote `repr(dict)`, a str.
                # `safe_eval` then raised TypeError and the `except` below turned
                # every well-formed params dict into False -- the round-trip was
                # broken for years behind a guard meant for *corrupt* input.
                # Decoding here keeps that guard for what it is actually for.
                stored = stored.decode()
            try:
                record.params = safe_eval(stored, {"uid": self.env.uid})
            except Exception:
                record.params = False

    def _inverse_params(self) -> None:
        for record in self:
            params = record.params
            record.params_store = repr(params) if isinstance(params, dict) else params

    def _menu_access_model_field(self) -> str:
        """``res_model`` gates a client action too, wherever it is set.

        It is optional here and documented as "mostly used for needactions",
        which is why menus never checked it while ``get_bindings`` did — the
        one difference between the two access gates, and an accidental one.
        Declaring it makes both check it: no shipped client action is bound and
        none of the menus pointing at one sets it, so nothing changes today,
        and the next one to set it is gated rather than half-gated.
        """
        return "res_model"

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

        Which of ``self`` survives is decided by ``_order``, not by recordset
        order, so it is the record ``ir.module.module._next_todo_action`` will
        actually run — its ``search(..., limit=1)`` reads the same order.
        Opening several at once used to keep whichever happened to come first
        out of ``create``, and the queue then ran a different one.
        """
        keep = self.filtered(lambda todo: todo.state == "open").sorted()[:1]
        if not keep:
            return
        self.search([("state", "=", "open"), ("id", "not in", keep.ids)]).write(
            {"state": "done"}
        )

    def action_launch(self) -> dict[str, Any]:
        """Mark the wizard done and return its action for the web client."""
        self.ensure_one()
        self.state = "done"

        action = self.action_id._as_concrete()
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
