import logging
import random
import typing
from collections import defaultdict
from itertools import batched
from operator import itemgetter
from typing import Any, Self

import psycopg

from odoo import api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import AccessError, MissingError
from odoo.models import add_field
from odoo.tools import SQL, OrderedSet, groupby, reset_cached_properties, unique
from odoo.tools.translate import _

from .ir_model_common import MODULE_UNINSTALL_FLAG

_logger = logging.getLogger(__name__)


class IrModelData(models.Model):
    _name = "ir.model.data"
    _is_registry_metadata = True
    _description = "Model Data"
    _order = "module, model, name"
    _allow_sudo_commands = False

    name = fields.Char(
        string="External Identifier",
        required=True,
        help="External Key/Identifier that can be used for data integration with third-party systems",
    )
    complete_name = fields.Char(compute="_compute_complete_name", string="Complete ID")
    model = fields.Char(string="Model Name", required=True)
    module = fields.Char(default="", required=True)
    res_id = fields.Many2oneReference(
        string="Record ID",
        help="ID of the target record in the database",
        model_field="model",
    )
    noupdate = fields.Boolean(string="Non Updatable", default=False)
    reference = fields.Char(
        string="Reference",
        compute="_compute_reference",
        readonly=True,
        store=False,
    )

    _name_nospaces = models.Constraint(
        "CHECK(name NOT LIKE '% %')", "External IDs cannot contain spaces"
    )
    _module_name_uniq_index = models.UniqueIndex("(module, name)")
    _model_res_id_index = models.Index("(model, res_id)")

    @api.depends("module", "name")
    def _compute_complete_name(self) -> None:
        for res in self:
            res.complete_name = ".".join(n for n in [res.module, res.name] if n)

    @api.depends("model", "res_id")
    def _compute_reference(self) -> None:
        for res in self:
            res.reference = f"{res.model},{res.res_id}"

    @api.depends("res_id", "model", "complete_name")
    def _compute_display_name(self) -> None:
        invalid_records = self.filtered(
            lambda r: not r.res_id or r.model not in self.env
        )
        for invalid_record in invalid_records:
            invalid_record.display_name = invalid_record.complete_name
        for model, model_data_records in (
            (self - invalid_records).grouped("model").items()
        ):
            records = self.env[model].browse(model_data_records.mapped("res_id"))
            for xid, target_record in zip(model_data_records, records, strict=True):
                try:
                    xid.display_name = target_record.display_name or xid.complete_name
                except AccessError, MissingError:
                    xid.display_name = xid.complete_name

    @api.model
    @tools.ormcache("xmlid")
    def _xmlid_lookup(self, xmlid: str) -> tuple[str, int]:
        if "." not in xmlid:
            raise ValueError(f"External ID not found in the system: {xmlid}")
        module, name = xmlid.split(".", 1)
        query = "SELECT model, res_id FROM ir_model_data WHERE module=%s AND name=%s"
        self.env.cr.execute(query, [module, name])
        result = self.env.cr.fetchone()
        if not (result and result[1]):
            raise ValueError(f"External ID not found in the system: {xmlid}")
        return result

    @api.model
    def _xmlid_to_res_model_res_id(
        self, xmlid: str, raise_if_not_found: bool = False
    ) -> tuple[str, int] | tuple[typing.Literal[False], typing.Literal[False]]:
        try:
            return self._xmlid_lookup(xmlid)
        except ValueError:
            if raise_if_not_found:
                raise
            return (False, False)

    @api.model
    def _xmlid_to_res_id(
        self, xmlid: str, raise_if_not_found: bool = False
    ) -> int | bool:
        return self._xmlid_to_res_model_res_id(xmlid, raise_if_not_found)[1]

    @api.model
    def check_object_reference(
        self, module: str, xml_id: str, raise_on_access_error: bool = False
    ) -> tuple[str, int | bool]:
        model, res_id = self._xmlid_lookup(f"{module}.{xml_id}")
        if self.env[model].search([("id", "=", res_id)]):
            return model, res_id
        if raise_on_access_error:
            raise AccessError(
                _(
                    'Not enough access rights on the external ID "%(module)s.%(xml_id)s"',
                    module=module,
                    xml_id=xml_id,
                )
            )
        return model, False

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        vals_list = super().copy_data(default=default)
        for model, vals in zip(self, vals_list, strict=True):
            rand = f"{random.getrandbits(16):04x}"
            vals["name"] = f"{model.name}_{rand}"
        return vals_list

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        res = super().create(vals_list)
        if any(vals.get("model") == "res.groups" for vals in vals_list):
            self.env.registry.clear_cache("groups")
        return res

    def write(self, vals: dict[str, Any]) -> bool:
        if not self:
            return True
        bust_xmlid = not (set(vals) <= {"noupdate"})
        touch_groups = vals.get("model") == "res.groups" or any(
            data.model == "res.groups" for data in self
        )
        res = super().write(vals)
        if bust_xmlid:
            self.flush_recordset()
            self.env.registry.clear_cache()
        if touch_groups:
            self.env.registry.clear_cache("groups")
        return res

    def unlink(self) -> bool:
        if not self:
            return True
        touch_groups = any(data.model == "res.groups" for data in self.exists())
        res = super().unlink()
        self.env.registry.clear_cache()
        if touch_groups:
            self.env.registry.clear_cache("groups")
        return res

    def _get_xmlids(self, xml_ids: list[str], model: Any) -> list[tuple]:
        if not xml_ids:
            return []

        bymodule = defaultdict(set)
        for xml_id in xml_ids:
            prefix, suffix = xml_id.split(".", 1)
            bymodule[prefix].add(suffix)

        result = []
        cr = self.env.cr
        table_sql = SQL.identifier(model._table)
        for prefix, suffixes in bymodule.items():
            for subsuffixes in batched(suffixes, cr.BATCH_SIZE, strict=False):
                cr.execute(
                    SQL(
                        """
                        SELECT d.id, d.module, d.name, d.model, d.res_id, d.noupdate, r.id
                        FROM ir_model_data d LEFT JOIN %s r ON d.res_id = r.id
                        WHERE d.module = %s AND d.name = ANY(%s)
                        """,
                        table_sql,
                        prefix,
                        list(subsuffixes),
                    )
                )
                result.extend(cr.fetchall())

        return result

    @api.model
    def _update_xmlids(
        self, data_list: list[dict[str, Any]], update: bool = False
    ) -> None:
        if not data_list:
            return

        rows = OrderedSet()
        for data in data_list:
            prefix, suffix = data["xml_id"].split(".", 1)
            record = data["record"]
            noupdate = bool(data.get("noupdate"))
            rows.add((prefix, suffix, record._name, record.id, noupdate))

        for sub_rows in batched(rows, self.env.cr.BATCH_SIZE, strict=False):
            query = self._prepare_update_xmlids_query(sub_rows, update)
            try:
                self.env.cr.execute(query)
                result = self.env.cr.fetchall()
                if result:
                    for (
                        module,
                        name,
                        model,
                        res_id,
                        create_date,
                        write_date,
                    ) in result:
                        self._xmlid_lookup.__cache__.add_value(
                            self,
                            f"{module}.{name}",
                            cache_value=(model, res_id),
                        )
                        if create_date != write_date:
                            self.env.registry.cache_invalidated.add("default")

            except Exception:
                _logger.error(
                    "Failed to insert ir_model_data\n%s",
                    "\n".join(str(row) for row in sub_rows),
                )
                raise

        xml_ids = {f"{row[0]}.{row[1]}" for row in rows}
        self.pool.loaded_xmlids.update(xml_ids)
        recorder = getattr(self.pool, "_xmlid_recorder", None)
        if recorder is not None:
            recorder.update(xml_ids)

        if any(row[2] == "res.groups" for row in rows):
            self.env.registry.clear_cache("groups")

    def _insert_xmlids_extra_columns(self) -> dict[str, SQL]:
        return {}

    def _prepare_update_xmlids_query(self, sub_rows: list[tuple], update: bool) -> SQL:
        extra = self._insert_xmlids_extra_columns()
        columns = ["module", "name", "model", "res_id", "noupdate", *extra]
        values = SQL(", ").join(
            SQL(
                "(%s)",
                SQL(", ").join([*(SQL("%s", value) for value in row), *extra.values()]),
            )
            for row in sub_rows
        )
        return SQL(
            """
            INSERT INTO ir_model_data (%(columns)s)
            VALUES %(values)s
            ON CONFLICT (module, name)
            DO UPDATE SET (model, res_id, write_date) =
                (EXCLUDED.model, EXCLUDED.res_id, now() at time zone 'UTC')
                WHERE (ir_model_data.res_id != EXCLUDED.res_id OR ir_model_data.model != EXCLUDED.model) %(and_where)s
            RETURNING module, name, model, res_id, create_date, write_date
            """,
            columns=SQL(", ").join(SQL.identifier(column) for column in columns),
            values=values,
            and_where=SQL("AND NOT ir_model_data.noupdate") if update else SQL(),
        )

    @api.model
    def _load_xmlid(self, xml_id: str) -> Any:
        record = self.env.ref(xml_id, raise_if_not_found=False)
        if record:
            self.pool.loaded_xmlids.add(xml_id)
            recorder = getattr(self.pool, "_xmlid_recorder", None)
            if recorder is not None:
                recorder.add(xml_id)
        return record

    @api.model
    def _module_data_uninstall(self, modules_to_remove: list[str]) -> None:
        if not self.env.is_system():
            raise AccessError(
                _("Administrator access is required to uninstall a module")
            )

        self = self.with_context(
            **{MODULE_UNINSTALL_FLAG: True, "prefetch_fields": False}
        )

        records_items = []
        model_ids = []
        field_ids = []
        selection_ids = []
        constraint_ids = []

        module_data = self.search(
            [("module", "in", modules_to_remove)], order="id DESC"
        )
        for data in module_data:
            match data.model:
                case "ir.model":
                    model_ids.append(data.res_id)
                case "ir.model.fields":
                    field_ids.append(data.res_id)
                case "ir.model.fields.selection":
                    selection_ids.append(data.res_id)
                case "ir.model.constraint":
                    constraint_ids.append(data.res_id)
                case _:
                    records_items.append((data.model, data.res_id))

        has_shared_field = False
        for ir_field in self.env["ir.model.fields"].browse(field_ids):
            model = self.pool.get(ir_field.model)
            if model is not None:
                field = model._fields.get(ir_field.name)
                if field is not None and field.prefetch:
                    if field._toplevel:
                        field.prefetch = False
                    else:
                        Field = type(field)
                        field_ = Field(_base_fields__=(field, Field(prefetch=False)))
                        add_field(
                            self.env.registry[ir_field.model],
                            ir_field.name,
                            field_,
                        )
                        field_.setup(model)
                        has_shared_field = True
        if has_shared_field:
            reset_cached_properties(self.env.registry)

        undeletable_ids = []

        def delete(records):
            ref_data = self.search(
                [
                    ("model", "=", records._name),
                    ("res_id", "in", records.ids),
                ]
            )
            cloc_exclude_data = ref_data.filtered(
                lambda imd: imd.module == "__cloc_exclude__"
            )
            ref_data -= cloc_exclude_data
            records -= records.browse((ref_data - module_data).mapped("res_id"))
            if not records:
                return

            if records._name == "ir.model.fields":
                missing = records - records.exists()
                if missing:
                    orphans = ref_data.filtered(lambda r: r.res_id in missing._ids)
                    _logger.info("Deleting orphan ir_model_data %s", orphans)
                    orphans.unlink()
                    records -= missing
                records -= records.filtered(
                    lambda f: (
                        f.name == "id"
                        or (
                            f.name in models.LOG_ACCESS_COLUMNS
                            and f.model in self.env
                            and self.env[f.model]._log_access
                        )
                    )
                )

            _logger.info("Deleting %s", records)
            try:
                with self.env.cr.savepoint():
                    cloc_exclude_data.unlink()
                    records.unlink()
            except Exception:
                if len(records) <= 1:
                    undeletable_ids.extend(ref_data._ids)
                else:
                    half_size = len(records) // 2
                    delete(records[:half_size])
                    delete(records[half_size:])

        for model, items in groupby(unique(records_items), itemgetter(0)):
            ids = [item[1] for item in items]
            if model in self.env:
                delete(self.env[model].browse(ids))
            else:
                _logger.info(
                    "Orphan ir.model.data records %s refer to unavailable model '%s'",
                    ids,
                    model,
                )

        modules = self.env["ir.module.module"].search(
            [("name", "in", modules_to_remove)]
        )
        modules._remove_copied_views()

        delete(self.env["ir.model.constraint"].browse(unique(constraint_ids)))

        delete(
            self.env["ir.model.fields.selection"].browse(unique(selection_ids)).exists()
        )
        delete(self.env["ir.model.fields"].browse(unique(field_ids)))
        relations = self.env["ir.model.relation"].search(
            [("module", "in", modules.ids)]
        )
        relations._module_data_uninstall()

        delete(self.env["ir.model"].browse(unique(model_ids)))

        _logger.info("ir.model.data could not be deleted (%s)", undeletable_ids)

        for data in self.browse(undeletable_ids).exists():
            if data.model not in self.env.registry:
                continue
            record = self.env[data.model].browse(data.res_id)
            try:
                with self.env.cr.savepoint():
                    if record.exists():
                        module_data -= data
                        continue
            except psycopg.ProgrammingError:
                pass
        module_data.unlink()

    def _count_xmlids_per_record(
        self, keys: list[tuple[str, int]]
    ) -> dict[tuple[str, int], int]:
        if not keys:
            return {}
        models_, res_ids = zip(*set(keys), strict=True)
        return {
            (model, res_id): count
            for model, res_id, count in self.env.execute_query(
                SQL(
                    """SELECT model, res_id, count(*)
                       FROM ir_model_data
                       WHERE (model, res_id) IN (
                           SELECT * FROM unnest(%s::varchar[], %s::integer[])
                       )
                       GROUP BY model, res_id""",
                    list(models_),
                    list(res_ids),
                )
            )
        }

    @api.model
    def _process_end_unlink_record(self, record: Any) -> None:
        record.unlink()

    @api.model
    def _process_end(self, modules: list[str]) -> None:
        if not modules or tools.config.get("import_partial"):
            return

        bad_imd_ids = []
        self = self.with_context({MODULE_UNINSTALL_FLAG: True})
        loaded_xmlids = self.pool.loaded_xmlids

        query = """ SELECT id, module || '.' || name, model, res_id FROM ir_model_data
                    WHERE module = ANY(%s) AND res_id IS NOT NULL AND COALESCE(noupdate, false) != %s ORDER BY id DESC
                """
        self.env.cr.execute(query, (list(modules), True))
        candidates = self.env.cr.fetchall()
        xmlids_per_record = self._count_xmlids_per_record(
            [(model, res_id) for _id, _xmlid, model, res_id in candidates]
        )

        for id, xmlid, model, res_id in candidates:
            if xmlid in loaded_xmlids:
                continue

            Model = self.env.get(model)
            if Model is None:
                continue

            keep = False
            for inheriting in (self.env[m] for m in Model._inherits_children):
                if inheriting._abstract:
                    continue

                parent_field = inheriting._inherits[model]
                children = inheriting.with_context(active_test=False).search(
                    [(parent_field, "=", res_id)]
                )
                children_xids = {
                    xid
                    for xids in (children and children._get_external_ids().values())
                    for xid in xids
                }
                if children_xids & loaded_xmlids:
                    keep = True
                    break
            if keep:
                continue

            if xmlids_per_record.get((model, res_id), 1) > 1:
                xmlids_per_record[(model, res_id)] -= 1
                bad_imd_ids.append(id)
                continue

            _logger.info("Deleting %s@%s (%s)", res_id, model, xmlid)
            record = Model.browse(res_id)
            if record.exists():
                module = xmlid.split(".", 1)[0]
                record = record.with_context(module=module)
                self._process_end_unlink_record(record)
            else:
                xmlids_per_record[(model, res_id)] = (
                    xmlids_per_record.get((model, res_id), 1) - 1
                )
                bad_imd_ids.append(id)
        if bad_imd_ids:
            self.browse(bad_imd_ids).unlink()

        self.env["ir.ui.view"]._create_all_specific_views(modules)

        loaded_xmlids.clear()

    @api.model
    def toggle_noupdate(self, model: str, res_id: int) -> None:
        self.env[model].browse(res_id).check_access("write")
        xids = self.search([("model", "=", model), ("res_id", "=", res_id)])
        for noupdate, group in xids.grouped("noupdate").items():
            group.write({"noupdate": not noupdate})
