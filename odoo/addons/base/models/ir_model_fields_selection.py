import logging
from typing import Any, Self

import psycopg
from psycopg.types.json import Json

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.orm._typing import ValuesType
from odoo.tools import SQL, OrderedSet

from .ir_model import (
    MODULE_UNINSTALL_FLAG,
    mark_modified,
    query_insert,
    query_update,
    selection_xmlid,
    upsert_en,
)

_logger = logging.getLogger(__name__)


class IrModelFieldsSelection(models.Model):
    _name = "ir.model.fields.selection"
    _order = "sequence, id"
    _description = "Fields Selection"
    _allow_sudo_commands = False

    field_id = fields.Many2one(
        "ir.model.fields",
        required=True,
        ondelete="cascade",
        index=True,
        domain=[("ttype", "in", ["selection", "reference"])],
    )
    value = fields.Char(required=True)
    name = fields.Char(translate=True, required=True)
    sequence = fields.Integer(default=1000)

    _selection_field_uniq = models.Constraint(
        "UNIQUE (field_id, value)",
        "Selections values must be unique per field",
    )

    def _get_selection(self, field_id: int) -> list[tuple[str, str]]:
        """Return the given field's selection as a list of pairs (value, string)."""
        self.flush_model(["value", "name", "field_id", "sequence"])
        return self._get_selection_data(field_id)

    def _get_selection_data(self, field_id: int) -> list[tuple[str, str]]:
        """Return the field's selection from the database without translations."""
        self.env.cr.execute(
            """
            SELECT value, name->>'en_US'
            FROM ir_model_fields_selection
            WHERE field_id=%s
            ORDER BY sequence, id
        """,
            (field_id,),
        )
        return self.env.cr.fetchall()

    def _reflect_selections(self, model_names: list[str]) -> None:
        """Reflect the selections of the fields of the given models."""
        selection_fields = [
            field
            for model_name in model_names
            for field in self.env[model_name]._fields.values()
            if field.type in ("selection", "reference")
            if isinstance(field.selection, list)
        ]
        if not selection_fields:
            return
        if invalid_fields := OrderedSet(
            field
            for field in selection_fields
            for selection in field.selection
            for value_label in selection
            if not isinstance(value_label, str)
        ):
            raise ValidationError(
                _(
                    "Fields %s contain a non-str value/label in selection",
                    ", ".join(
                        f"{field.model_name}.{field.name}" for field in invalid_fields
                    ),
                )
            )

        # determine expected and existing rows
        IMF = self.env["ir.model.fields"]
        expected = {
            (field_id, value): (label, index)
            for field in selection_fields
            for field_id in [IMF._get_ids(field.model_name)[field.name]]
            for index, (value, label) in enumerate(field.selection)
        }

        cr = self.env.cr
        query = """
            SELECT s.field_id, s.value, s.name->>'en_US', s.sequence
            FROM ir_model_fields_selection s, ir_model_fields f
            WHERE s.field_id = f.id AND f.model = ANY(%s)
        """
        cr.execute(query, [list(model_names)])
        existing = {row[:2]: row[2:] for row in cr.fetchall()}

        # create or update rows
        cols = ["field_id", "value", "name", "sequence"]
        rows = [key + val for key, val in expected.items() if existing.get(key) != val]
        if rows:
            ids = upsert_en(self, cols, rows, ["field_id", "value"])
            self.pool.post_init(mark_modified, self.browse(ids), cols[2:])

        # update their XML ids
        module = self.env.context.get("module")
        if not module:
            return

        query = """
            SELECT f.model, f.name, s.value, s.id
            FROM ir_model_fields_selection s, ir_model_fields f
            WHERE s.field_id = f.id AND f.model = ANY(%s)
        """
        cr.execute(query, [list(model_names)])
        selection_ids = {row[:3]: row[3] for row in cr.fetchall()}

        data_list = []
        for field in selection_fields:
            model = self.env[field.model_name]
            for value, modules in field._selection_modules(model).items():
                for m in modules:
                    xml_id = selection_xmlid(m, field.model_name, field.name, value)
                    record = self.browse(
                        selection_ids[field.model_name, field.name, value]
                    )
                    data_list.append({"xml_id": xml_id, "record": record})
        self.env["ir.model.data"]._update_xmlids(data_list)

    def _update_selection(
        self, model_name: str, field_name: str, selection: list[tuple[str, str]]
    ) -> dict[str, dict[str, Any]]:
        """Set the selection of a field to the given list, and return the row
        values of the given selection records.
        """
        field_id = self.env["ir.model.fields"]._get_ids(model_name)[field_name]

        # selection rows {value: row}
        cur_rows = self._existing_selection_data(model_name, field_name)
        new_rows = {
            value: {"value": value, "name": label, "sequence": index}
            for index, (value, label) in enumerate(selection)
        }

        rows_to_insert = []
        rows_to_update = []
        rows_to_remove = []
        for value in new_rows.keys() | cur_rows.keys():
            new_row, cur_row = new_rows.get(value), cur_rows.get(value)
            if new_row is None:
                if self.pool.ready:
                    # removing a selection in the new list, at your own risks
                    _logger.warning(
                        "Removing selection value %s on %s.%s",
                        cur_row["value"],
                        model_name,
                        field_name,
                    )
                    rows_to_remove.append(cur_row["id"])
            elif cur_row is None:
                new_row["name"] = Json({"en_US": new_row["name"]})
                rows_to_insert.append(dict(new_row, field_id=field_id))
            elif any(new_row[key] != cur_row[key] for key in new_row):
                new_row["name"] = Json({"en_US": new_row["name"]})
                rows_to_update.append(dict(new_row, id=cur_row["id"]))

        if rows_to_insert:
            row_ids = query_insert(self.env.cr, self._table, rows_to_insert)
            # update cur_rows for output
            for row, row_id in zip(rows_to_insert, row_ids, strict=True):
                cur_rows[row["value"]] = dict(row, id=row_id)

        for row in rows_to_update:
            query_update(self.env.cr, self._table, row, ["id"])

        if rows_to_remove:
            self.browse(rows_to_remove).unlink()

        return cur_rows

    def _existing_selection_data(
        self, model_name: str, field_name: str
    ) -> dict[str, dict[str, Any]]:
        """Return the field's selection rows from the database, keyed by value.

        :return: ``{value: row_values}`` for the given model/field.
        :rtype: dict
        """
        query = """
            SELECT s.*, s.name->>'en_US' AS name
            FROM ir_model_fields_selection s
            JOIN ir_model_fields f ON s.field_id=f.id
            WHERE f.model=%s and f.name=%s
        """
        self.env.cr.execute(query, [model_name, field_name])
        return {row["value"]: row for row in self.env.cr.dictfetchall()}

    def _raise_base_field_error(self) -> None:
        """Raise the standard error forbidding edits to non-manual selections."""
        raise UserError(
            _(
                "Properties of base fields cannot be altered in this manner! "
                "Please modify them through Python code, "
                "preferably through a custom addon!"
            )
        )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Create selection rows and re-initialise the affected models in the registry."""
        field_ids = {vals["field_id"] for vals in vals_list}
        field_names = set()
        for field in self.env["ir.model.fields"].browse(field_ids):
            field_names.add((field.model, field.name))
            if field.state != "manual":
                self._raise_base_field_error()
        recs = super().create(vals_list)

        model_names = OrderedSet()
        for model, name in field_names:
            if model in self.pool and name in self.pool[model]._fields:
                model_names.add(model)
            else:
                # The field is not (yet) in the registry -- e.g. a selection row
                # created during module load before its field is set up. The
                # registry refresh is skipped; log it so the silent path stays
                # observable (SEL-C7).
                _logger.debug(
                    "Skipped registry setup for selection on %s.%s: "
                    "field not in registry",
                    model,
                    name,
                )
        if model_names:
            # setup models; this re-initializes model in registry
            self.env.flush_all()
            self.pool._setup_models__(self.env.cr, model_names)

        return recs

    def _is_jsonb_stored(self, field) -> bool:
        """Whether the column backing a selection/reference field is jsonb.

        ``company_dependent`` fields are stored as ``{company_id: value}`` jsonb
        instead of a plain scalar column. :meth:`write` (value rename) and
        :meth:`_get_records` (value match) must both branch on this predicate so
        their stored-column SQL can never diverge (SEL-C1).

        :param field: the selection/reference field -- an ``ir.model.fields``
            record or an ORM field; only ``company_dependent`` is read.
        :rtype: bool
        """
        return bool(field.company_dependent)

    def write(self, vals: dict[str, Any]) -> bool:
        """Write selection rows; rewrite stored column data on value change and
        refresh the registry or selection caches accordingly.
        """
        if not self:
            return True

        if not self.env.user._is_admin() and any(
            record.field_id.state != "manual" for record in self
        ):
            self._raise_base_field_error()

        if "value" in vals:
            # Two selection rows of the same field cannot share a value
            # (UNIQUE(field_id, value)); a batch renaming several rows of one
            # field to the same value would only fail at flush -- after the
            # destructive column rewrites below already ran. Reject it up front.
            # len(self) > len(self.field_id) holds iff some field owns more than
            # one row in self (SEL-C2).
            if len(self) > len(self.field_id):
                raise UserError(
                    _(
                        "Cannot set the same value on several selection options "
                        "of one field; selection values must be unique per field."
                    )
                )
            for selection in self:
                if selection.value == vals["value"]:
                    continue
                if selection.field_id.store:
                    # in order to keep the cache consistent, flush the
                    # corresponding field, and invalidate it from cache
                    model = self.env[selection.field_id.model]
                    fname = selection.field_id.name
                    model.invalidate_model([fname])
                    # Replace the old value by the new one in the field's stored
                    # column. company_dependent fields are jsonb keyed by company
                    # ({company_id: value}); a value rename is global, so every
                    # company key holding the old value must migrate. Mirror the
                    # storage-shape branch in _get_records so the two cannot
                    # diverge (SEL-C1).
                    if self._is_jsonb_stored(selection.field_id):
                        query = SQL(
                            "UPDATE %s AS t SET %s = ("
                            " SELECT jsonb_object_agg(e.key,"
                            " CASE WHEN e.value = to_jsonb(%s::text)"
                            " THEN to_jsonb(%s::text) ELSE e.value END)"
                            " FROM jsonb_each(t.%s) AS e"
                            ") WHERE EXISTS ("
                            " SELECT 1 FROM jsonb_each(t.%s) AS e2"
                            " WHERE e2.value = to_jsonb(%s::text)"
                            ")",
                            SQL.identifier(model._table),
                            SQL.identifier(fname),
                            selection.value,
                            vals["value"],
                            SQL.identifier(fname),
                            SQL.identifier(fname),
                            selection.value,
                        )
                    else:
                        query = SQL(
                            "UPDATE %s SET %s = %s WHERE %s = %s",
                            SQL.identifier(model._table),
                            SQL.identifier(fname),
                            vals["value"],
                            SQL.identifier(fname),
                            selection.value,
                        )
                    self.env.cr.execute(query)

        result = super().write(vals)

        # Re-initialise the affected models in the registry only when the change
        # can alter the selection SET or ORDER. A label-only (name) edit leaves
        # the valid values and their order intact, so the sole stale artefact is
        # the lang-keyed get_field_selection ormcache ("stable"); clearing that
        # is far cheaper than a full _setup_models__ rebuild (SEL-C6).
        self.env.flush_all()
        if {"value", "sequence", "field_id"} & vals.keys():
            model_names = self.field_id.model_id.mapped("model")
            self.pool._setup_models__(self.env.cr, model_names)
        elif "name" in vals:
            self.env.registry.clear_cache("stable")

        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_if_manual(self) -> None:
        # Prevent manual deletion of module columns
        if self.pool.ready and any(
            selection.field_id.state != "manual" for selection in self
        ):
            self._raise_base_field_error()

    def unlink(self) -> bool:
        """Unlink selection rows after applying each value's ondelete policy."""
        model_names = self.field_id.model_id.mapped("model")
        self._process_ondelete()
        result = super().unlink()

        # Reload registry for normal unlink only. For module uninstall, the
        # reload is done independently in odoo.modules.loading.
        if not self.env.context.get(MODULE_UNINSTALL_FLAG):
            # setup models; this re-initializes model in registry
            self.env.flush_all()
            self.pool._setup_models__(self.env.cr, model_names)

        return result

    def _process_ondelete(self) -> None:
        """Apply each deleted selection value's ondelete policy to its records.

        Records are resolved once per ``(field, company)`` -- one flush and one
        query for all of a field's deleted values -- rather than once per value
        (SEL-P3). Resolution precedes any policy write, so each record is handled
        according to the value it held at deletion time; a value whose policy
        targets another value being deleted does not cascade into that bucket.
        """

        def safe_write(records: Any, fname: str, value: Any) -> None:
            if not records:
                return
            try:
                with self.env.cr.savepoint():
                    records.write({fname: value})
            except (UserError, psycopg.Error) as error:
                # The ORM write was refused by an override or a constraint; fall
                # back to a raw column update so module-uninstall cleanup of a
                # removed selection value can still complete. The catch is
                # narrowed to recoverable failures -- a programming error (e.g.
                # TypeError in an override) now propagates instead of being
                # masked by a silent data write (SEL-C4).
                _logger.warning(
                    "Could not fulfill ondelete action for field %s.%s (%s); "
                    "attempting ORM bypass",
                    records._name,
                    fname,
                    error,
                )
                # if this fails there is nothing we can do except fix on a case-by-case basis
                self.env.execute_query(
                    SQL(
                        "UPDATE %s SET %s=%s WHERE id = ANY(%s)",
                        SQL.identifier(records._table),
                        SQL.identifier(fname),
                        field.convert_to_column_insert(value, records),
                        list(records._ids),
                    )
                )
                records.invalidate_recordset([fname])

        # Group the deleted rows by field so each field's model is resolved and
        # flushed once, not once per value.
        for field_record, selections in self.grouped("field_id").items():
            # The field may exist in database but not in registry. In this case
            # we allow the field to be skipped, but for production this should
            # be handled through a migration script. The ORM will take care of
            # the orphaned 'ir.model.fields' down the stack, and will log a
            # warning prompting the developer to write a migration script.
            Model = self.env.get(field_record.model)
            if Model is None:
                continue
            field = Model._fields.get(field_record.name)
            if not field or not field.store or not Model._auto:
                continue

            # Field changed its type, skip it.
            if field.type not in ("selection", "reference"):
                continue

            # resolve the ondelete policy of each deleted value, dropping values
            # that carry none
            policies = {}
            for selection in selections:
                ondelete = (field.ondelete or {}).get(selection.value)
                # special case for custom fields
                if ondelete is None and field.manual and not field.required:
                    ondelete = "set null"
                if ondelete is not None:
                    policies[selection.value] = ondelete
            if not policies:
                # nothing to do, none of the values come from a field extension
                continue

            companies = (
                self.env.companies
                if field_record.company_dependent
                else [self.env.company]
            )
            for company in companies:
                # make a company-specific env for the Model
                company_model = Model.with_company(company.id)
                # one flush + one query resolves every value's records
                records_by_value = self._get_records_by_value(
                    company_model, field, list(policies)
                )
                for value, ondelete in policies.items():
                    records = records_by_value.get(value, company_model.browse())
                    if callable(ondelete):
                        ondelete(records)
                    elif ondelete == "set null":
                        safe_write(records, field.name, False)
                    elif ondelete == "set default":
                        default = field.convert_to_write(
                            field.default(company_model), company_model
                        )
                        safe_write(records, field.name, default)
                    elif ondelete.startswith("set "):
                        safe_write(records, field.name, ondelete.removeprefix("set "))
                    elif ondelete == "cascade":
                        records.unlink()
                    else:
                        # this shouldn't happen... simply a sanity check
                        raise ValueError(
                            _(
                                'The ondelete policy "%(policy)s" is not valid for field "%(field)s"',
                                policy=ondelete,
                                field=f"{field_record.model}.{field.name}",
                            )
                        )

    def _get_records_by_value(
        self, company_model: Any, field: Any, values: list
    ) -> dict:
        """Return ``{value: recordset}`` for ``company_model`` records whose
        stored ``field`` currently holds one of ``values``.

        One flush and one query resolve the whole batch, scoped to the model's
        company for a company-dependent (jsonb) field; the records are bound to
        ``company_model`` so company-dependent writes land in the right context
        (SEL-P3).

        :param field: the ORM field backing the selection/reference column.
        :rtype: dict
        """
        fname = field.name
        company_model.flush_model([fname])
        if self._is_jsonb_stored(field):
            # company-dependent fields are stored as jsonb (e.g. {company_id: value})
            company_key = str(company_model.env.company.id)
            query = SQL(
                "SELECT %s ->> %s AS value, array_agg(id) AS ids FROM %s "
                "WHERE %s ->> %s = ANY(%s) GROUP BY 1",
                SQL.identifier(fname),
                company_key,
                SQL.identifier(company_model._table),
                SQL.identifier(fname),
                company_key,
                values,
            )
        else:
            # normal selection fields are stored as a plain column
            query = SQL(
                "SELECT %s AS value, array_agg(id) AS ids FROM %s "
                "WHERE %s = ANY(%s) GROUP BY 1",
                SQL.identifier(fname),
                SQL.identifier(company_model._table),
                SQL.identifier(fname),
                values,
            )
        self.env.cr.execute(query)
        return {
            value: company_model.browse(ids) for value, ids in self.env.cr.fetchall()
        }

    def _get_records(self) -> Any:
        """Return the records that currently hold this selection value.

        For a company-dependent (jsonb) field the match is scoped to
        ``self.env.company``; :meth:`_process_ondelete` therefore iterates on a
        ``with_company`` recordset so each company is handled in its own context.
        The coupling on the ambient company is intentional and documented here
        rather than threaded through a parameter (SEL-C3).
        """
        self.ensure_one()
        Model = self.env[self.field_id.model]
        Model.flush_model([self.field_id.name])
        if self._is_jsonb_stored(self.field_id):
            # company-dependent fields are stored as jsonb (e.g; {company_id: value})
            query = SQL(
                "SELECT id FROM %s WHERE %s ->> %s = %s",
                SQL.identifier(Model._table),
                SQL.identifier(self.field_id.name),
                str(self.env.company.id),
                self.value,
            )
        else:
            # normal selection fields are stored as general datatype
            query = SQL(
                "SELECT id FROM %s WHERE %s = %s",
                SQL.identifier(Model._table),
                SQL.identifier(self.field_id.name),
                self.value,
            )
        self.env.cr.execute(query)
        return Model.browse(r[0] for r in self.env.cr.fetchall())
