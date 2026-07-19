import logging
import re
from collections import defaultdict
from typing import Any, Self, override

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tools import (
    SQL,
    OrderedSet,
    remove_accents,
    sql,
    unique,
)
from odoo.tools.translate import _

from .ir_model_common import (
    MODULE_UNINSTALL_FLAG,
    compute_modules,
    inherit_xmlid,
    mark_modified,
    model_xmlid,
    reload_schema,
    select_en,
    upsert_en,
)

_logger = logging.getLogger(__name__)


# IMPORTANT: this must be the first model declared in the module


class Base(models.AbstractModel):
    """The base model, which is implicitly inherited by all models."""

    _name = "base"
    _description = "Base"


class Unknown(models.AbstractModel):
    """Substitute for relational fields with an unknown comodel."""

    _name = "_unknown"
    _description = "Unknown"


class IrModel(models.Model):
    _name = "ir.model"
    _description = "Models"
    _order = "model"
    _rec_names_search = ["name", "model"]
    _allow_sudo_commands = False

    def _default_field_id(self) -> list[tuple[int, int, dict[str, Any]]]:
        if self.env.context.get("install_mode"):
            return []  # no default field when importing
        return [
            Command.create(
                {
                    "name": "x_name",
                    "field_description": "Name",
                    "ttype": "char",
                    "copied": True,
                }
            )
        ]

    name = fields.Char(string="Model Description", translate=True, required=True)
    model = fields.Char(default="x_", required=True)
    order = fields.Char(
        string="Order",
        default="id",
        required=True,
        help='SQL expression for ordering records in the model; e.g. "x_sequence asc, id desc"',
    )
    info = fields.Text(string="Information")
    field_id = fields.One2many(
        "ir.model.fields",
        "model_id",
        string="Fields",
        required=True,
        copy=True,
        default=_default_field_id,
    )
    inherited_model_ids = fields.Many2many(
        "ir.model",
        compute="_compute_inherited_model_ids",
        string="Inherited models",
        help="The parent models this model delegates to (via _inherits).",
    )
    state = fields.Selection(
        [("manual", "Custom Object"), ("base", "Base Object")],
        string="Type",
        default="manual",
        readonly=True,
    )
    access_ids = fields.One2many("ir.model.access", "model_id", string="Access")
    rule_ids = fields.One2many("ir.rule", "model_id", string="Record Rules")
    abstract = fields.Boolean(string="Abstract Model")
    transient = fields.Boolean(string="Transient Model")
    modules = fields.Char(
        compute="_compute_modules",
        string="In Apps",
        help="List of modules in which the object is defined or inherited",
    )
    view_ids = fields.One2many(
        "ir.ui.view", compute="_compute_view_ids", string="Views"
    )
    count = fields.Integer(
        compute="_compute_count",
        string="Count (Incl. Archived)",
        help="Total number of records in this model",
    )
    fold_name = fields.Char(
        string="Fold Field",
        help="In a Kanban view where columns are records of this model, the value "
        "of this (boolean) field determines which column should be folded by default.",
    )

    @api.depends()
    def _compute_inherited_model_ids(self) -> None:
        """Batch-resolve inherited models with a single search."""
        self.inherited_model_ids = False
        all_parent_names = set()
        inherits_by_model: dict[str, list[str]] = {}
        for model in self:
            if (records := self.env.get(model.model)) is not None:
                parent_names = list(records._inherits)
                if parent_names:
                    inherits_by_model[model.model] = parent_names
                    all_parent_names.update(parent_names)
        if not all_parent_names:
            return
        parent_records = {
            rec.model: rec
            for rec in self.search([("model", "in", list(all_parent_names))])
        }
        for model in self:
            if parent_names := inherits_by_model.get(model.model):
                model.inherited_model_ids = self.browse(
                    parent_records[name].id
                    for name in parent_names
                    if name in parent_records
                )

    @api.depends()
    def _compute_modules(self) -> None:
        compute_modules(self)

    @api.depends()
    def _compute_view_ids(self) -> None:
        """Batch-fetch views for all models in a single query."""
        model_names = [m.model for m in self]
        View = self.env["ir.ui.view"]
        views_by_model: dict[str, list[int]] = defaultdict(list)
        if model_names:
            for view in View.search([("model", "in", model_names)]):
                views_by_model[view.model].append(view.id)
        for model in self:
            model.view_ids = View.browse(views_by_model.get(model.model, []))

    @api.depends()
    def _compute_count(self) -> None:
        """Batch-count records using a single UNION ALL query."""
        self.count = 0
        table_models: list[tuple[str, str]] = [
            (records._table, model.model)
            for model in self
            if (records := self.env.get(model.model)) is not None
            and not records._abstract
            and records._auto
        ]
        if not table_models:
            return
        # single UNION ALL: one COUNT(*) per table in one round-trip
        parts = [
            SQL(
                "SELECT %s AS model, COUNT(*) FROM %s",
                model_name,
                SQL.identifier(table),
            )
            for table, model_name in table_models
        ]
        query = SQL(" UNION ALL ").join(parts)
        counts = dict(self.env.execute_query(query))
        for model in self:
            if model.model in counts:
                model.count = counts[model.model]

    @api.constrains("model")
    def _check_model_name(self) -> None:
        for model in self:
            if model.state == "manual":
                self._check_manual_name(model.model)
            if not models.check_object_name(model.model):
                raise ValidationError(
                    _(
                        "The model name can only contain lowercase characters, digits, underscores and dots."
                    )
                )

    @api.constrains("order", "field_id")
    def _check_order(self) -> None:
        for model in self:
            try:
                model._check_qorder(
                    model.order
                )  # regex check for the whole clause ('is it valid sql?')
            except UserError as e:
                raise ValidationError(str(e)) from None
            # add MAGIC_COLUMNS in case 'model' is not initialized yet, or
            # 'field_id' is not up-to-date in cache
            stored_fields = set(
                model.field_id.filtered("store").mapped("name") + models.MAGIC_COLUMNS
            )
            if model.model in self.env:
                # add already-loaded fields inherited from code-defined models
                stored_fields.update(
                    fname
                    for fname, fval in self.env[model.model]._fields.items()
                    if fval.inherited and fval.base_field.store
                )

            # Use the ORM's own order parser (already applied by _check_qorder)
            # rather than a parallel regex that would drift from the grammar and
            # mistake grouping funcs ("create_date:month") or related-field
            # properties ("parent_id.name") for missing field names.
            for order_part in model.order.split(","):
                order_match = models.regex_order.match(order_part)
                field = order_match["field"] if order_match else None
                if field and field not in stored_fields:
                    raise ValidationError(
                        _(
                            "Unable to order by %s: fields used for ordering must be present on the model and stored.",
                            field,
                        )
                    )

    @api.constrains("fold_name")
    def _check_fold_name(self) -> None:
        for model in self:
            if model.fold_name and model.fold_name not in model.field_id.mapped("name"):
                raise ValidationError(
                    _("The value of 'Fold Field' should be a field name of the model.")
                )

    _obj_name_uniq = models.Constraint(
        "UNIQUE (model)", "Each model must have a unique name."
    )

    def _get(self, name: str) -> Self:
        """Return the (sudoed) `ir.model` record with the given name.

        Empty recordset if the model is not found.
        """
        model_id = self._get_id(name) if name else False
        return self.sudo().browse(model_id)

    @tools.ormcache("name", cache="stable")
    def _get_id(self, name: str) -> int | None:
        self.env.cr.execute("SELECT id FROM ir_model WHERE model=%s", (name,))
        return result[0] if (result := self.env.cr.fetchone()) else None

    def _drop_table(self) -> bool:
        for model in self:
            if (current_model := self.env.get(model.model)) is not None:
                if current_model._abstract:
                    continue

                table = current_model._table
                kind = sql.table_kind(self.env.cr, table)
                if kind == sql.TableKind.View:
                    self.env.cr.execute(SQL("DROP VIEW %s", SQL.identifier(table)))
                elif kind == sql.TableKind.Regular:
                    self.env.cr.execute(
                        SQL("DROP TABLE %s CASCADE", SQL.identifier(table))
                    )
                elif kind is not None:
                    _logger.warning(
                        "Unable to drop table %r of model %r: unmanaged or unknown table type %r",
                        table,
                        model.model,
                        kind,
                    )
            else:
                _logger.warning(
                    "The model %s could not be dropped because it did not exist in the registry.",
                    model.model,
                )
        return True

    @api.ondelete(at_uninstall=False)
    def _unlink_if_manual(self) -> None:
        # Prevent manual deletion of module tables
        for model in self:
            if model.state != "manual":
                raise UserError(
                    _(
                        "Model “%s” contains module data and cannot be removed.",
                        model.name,
                    )
                )

    @override
    def unlink(self) -> bool:
        # prevent screwing up fields that depend on these models' fields
        manual_models = self.filtered(lambda model: model.state == "manual")
        manual_models.field_id.filtered(lambda f: f.state == "manual")._prepare_update()
        (self - manual_models).field_id._prepare_update()

        # delete fields whose comodel is being removed
        self.env["ir.model.fields"].search(
            [("relation", "in", self.mapped("model"))]
        ).unlink()

        # delete ir_crons created by user
        crons = (
            self.env["ir.cron"]
            .with_context(active_test=False)
            .search([("model_id", "in", self.ids)])
        )
        if crons:
            crons.unlink()

        # delete related ir_model_data
        model_data = self.env["ir.model.data"].search(
            [("model", "in", self.mapped("model"))]
        )
        if model_data:
            model_data.unlink()

        self._drop_table()
        res = super().unlink()

        # Reload registry for normal unlink only. For module uninstall, the
        # reload is done independently in odoo.modules.loading.
        if not self.env.context.get(MODULE_UNINSTALL_FLAG):
            # setup models; this automatically removes model from registry
            self.env.flush_all()
            self.pool._setup_models__(self.env.cr)

        return res

    @override
    def write(self, vals: dict[str, Any]) -> bool:
        for unmodifiable_field in ("model", "state", "abstract", "transient"):
            if unmodifiable_field in vals and any(
                rec[unmodifiable_field] != vals[unmodifiable_field] for rec in self
            ):
                raise UserError(
                    _(
                        "Field %s cannot be modified on models.",
                        self._fields[unmodifiable_field]._description_string(self.env),
                    )
                )
        # Filter out operation 4 from field_id: the web client always writes
        # (4, id, False) even for non-dirty items.
        if "field_id" in vals:
            vals["field_id"] = [op for op in vals["field_id"] if op[0] != 4]
        res = super().write(vals)
        # ordering has been changed, reload registry to reflect update + signaling
        if "order" in vals or "fold_name" in vals:
            self.env.flush_all()  # _setup_models__ needs to fetch the updated values from the db
            # incremental setup will reload custom models
            self.pool._setup_models__(self.env.cr, [])
        return res

    @api.model_create_multi
    @override
    def create(self, vals_list: list[ValuesType]) -> Self:
        res = super().create(vals_list)
        manual_models = [
            vals["model"]
            for vals in vals_list
            if vals.get("state", "manual") == "manual"
        ]
        if manual_models:
            # reload custom models into the registry, then create their schema;
            # freshly created models have no descendants, so _inherits expansion
            # is a no-op here
            reload_schema(self.env, [], manual_models)
        return res

    @api.model
    @override
    def name_create(self, name: str) -> tuple[int, str]:
        """Infer the model name from the description, e.g. 'My New Model' -> 'x_my_new_model'.

        The name is slugified (accents stripped, non-alphanumeric runs collapsed
        to underscores) so punctuation or diacritics can't fail the
        ``_check_model_name`` constraint.
        """
        slug = re.sub(r"[^a-z0-9]+", "_", remove_accents(name).lower()).strip("_")
        ir_model = self.create(
            {
                "name": name,
                "model": f"x_{slug}" if slug else "x_",
            }
        )
        return ir_model.id, ir_model.display_name

    def _reflect_model_params(self, model: models.BaseModel) -> dict[str, Any]:
        """Return the values to write to the database for the given model."""
        return {
            "model": model._name,
            "name": model._description,
            "order": model._order or "id",
            "info": next(
                (
                    cls.__doc__
                    for cls in self.env.registry[model._name].mro()
                    if cls.__doc__
                ),
                None,
            ),
            "state": "manual" if model._custom else "base",
            "abstract": model._abstract,
            "transient": model._transient,
            "fold_name": model._fold_name,
        }

    def _reflect_models(self, model_names: list[str]) -> None:
        """Reflect the given models."""
        if not model_names:
            return
        rows = [
            self._reflect_model_params(self.env[model_name])
            for model_name in model_names
        ]
        cols = list(unique(["model"] + list(rows[0])))
        expected = [tuple(row[col] for col in cols) for row in rows]

        model_ids = {}
        existing = {}
        for row in select_en(self, ["id"] + cols, model_names):
            model_ids[row[1]] = row[0]
            existing[row[1]] = row[1:]

        # create or update rows
        rows = [row for row in expected if existing.get(row[0]) != row]
        if rows:
            ids = upsert_en(self, cols, rows, ["model"])
            for row, id_ in zip(rows, ids, strict=True):
                model_ids[row[0]] = id_
            self.pool.post_init(mark_modified, self.browse(ids), cols[1:])

        # pre-warm the _get_id ormcache so the subsequent
        # _reflect_inherits/_reflect_fields passes don't cold-miss one SELECT
        # per distinct model/parent name
        add_value = self._get_id.__cache__.add_value
        for name, id_ in model_ids.items():
            add_value(self, name, cache_value=id_)

        # update their XML id
        module = self.env.context.get("module")
        if not module:
            return

        data_list = []
        for model_name, model_id in model_ids.items():
            model = self.env[model_name]
            if model._module == module:
                # model._module is the name of the module that last extended model
                xml_id = model_xmlid(module, model_name)
                record = self.browse(model_id)
                data_list.append({"xml_id": xml_id, "record": record})
        self.env["ir.model.data"]._update_xmlids(data_list)

    @api.model
    def _instantiate_attrs(self, model_data: dict[str, Any]) -> dict[str, Any]:
        """Return the class attributes for a custom model defined by ``model_data``."""
        return {
            "_name": model_data["model"],
            "_description": model_data["name"],
            "_module": False,
            "_custom": True,
            "_abstract": bool(model_data["abstract"]),
            "_transient": bool(model_data["transient"]),
            "_order": model_data["order"],
            "_fold_name": model_data["fold_name"],
            "__doc__": model_data["info"],
        }

    @api.model
    def _is_manual_name(self, name: str) -> bool:
        return models.is_manual_name(name)

    @api.model
    def _check_manual_name(self, name: str) -> None:
        if not self._is_manual_name(name):
            raise ValidationError(_("The model name must start with 'x_'."))


class IrModelInherit(models.Model):
    _name = "ir.model.inherit"
    _description = "Model Inheritance Tree"
    _log_access = False

    model_id = fields.Many2one("ir.model", required=True, ondelete="cascade")
    parent_id = fields.Many2one("ir.model", required=True, ondelete="cascade")
    parent_field_id = fields.Many2one(
        "ir.model.fields", ondelete="cascade"
    )  # in case of inherits

    _uniq = models.Constraint(
        "UNIQUE(model_id, parent_id)", "Models inherits from another only once"
    )

    def _reflect_inherits(self, model_names: list[str]) -> None:
        """Reflect the given models' inherits (_inherit and _inherits)."""
        IrModel = self.env["ir.model"]
        get_model_id = IrModel._get_id

        module_mapping = defaultdict(OrderedSet)
        for model_name in model_names:
            get_field_id = self.env["ir.model.fields"]._get_ids(model_name).get
            model_id = get_model_id(model_name)
            model = self.env[model_name]

            for cls in reversed(type(model).mro()):
                if not models.is_model_definition(cls):
                    continue

                inherit_parents = [
                    parent_name
                    for parent_name in cls._inherit
                    if parent_name not in ("base", model_name)
                ]
                # parent_id is required: resolve parents up front so a missing
                # one fails with a named culprit rather than an opaque NOT NULL
                # violation deep inside upsert_en.
                parent_ids = {}
                for parent_name in (*inherit_parents, *cls._inherits):
                    parent_id = get_model_id(parent_name)
                    if parent_id is None:
                        raise ValueError(
                            f"Cannot reflect inheritance of {model_name!r}: parent "
                            f"model {parent_name!r} is not present in ir_model."
                        )
                    parent_ids[parent_name] = parent_id

                items = [
                    (model_id, parent_ids[parent_name], None)
                    for parent_name in inherit_parents
                ] + [
                    (model_id, parent_ids[parent_name], get_field_id(field))
                    for parent_name, field in cls._inherits.items()
                ]

                for item in items:
                    module_mapping[item].add(cls._module)

        if not module_mapping:
            return

        cr = self.env.cr
        cr.execute(
            """
                SELECT i.id, i.model_id, i.parent_id, i.parent_field_id
                  FROM ir_model_inherit i
                  JOIN ir_model m
                    ON m.id = i.model_id
                 WHERE m.model = ANY(%s)
            """,
            [list(model_names)],
        )
        existing = {}
        inh_ids = {}
        for iid, model_id, parent_id, parent_field_id in cr.fetchall():
            inh_ids[(model_id, parent_id, parent_field_id)] = iid
            existing[(model_id, parent_id)] = parent_field_id

        sentinel = object()
        cols = ["model_id", "parent_id", "parent_field_id"]
        rows = [
            item
            for item in module_mapping
            if existing.get(item[:2], sentinel) != item[2]
        ]
        if rows:
            ids = upsert_en(self, cols, rows, ["model_id", "parent_id"])
            inh_ids.update(dict(zip(rows, ids, strict=True)))
            self.pool.post_init(mark_modified, self.browse(ids), cols[1:])

        # update their XML id: resolve every model/parent id to its name once,
        # instead of re-browsing (twice) inside the loop below
        involved = IrModel.browse(id_ for item in module_mapping for id_ in item[:2])
        involved.fetch(["model"])
        xml_name = {rec.id: rec.model for rec in involved}
        data_list = []
        for (
            model_id,
            parent_id,
            parent_field_id,
        ), modules in module_mapping.items():
            record_id = inh_ids[(model_id, parent_id, parent_field_id)]
            data_list += [
                {
                    "xml_id": inherit_xmlid(
                        module, xml_name[model_id], xml_name[parent_id]
                    ),
                    "record": self.browse(record_id),
                }
                for module in modules
            ]

        self.env["ir.model.data"]._update_xmlids(data_list)
