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
    """External identifiers (XML ids) mapping records to their defining module."""

    _name = "ir.model.data"
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
        """Return (res_model, res_id) for xmlid, or raise ValueError if not found."""
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
        """Return (res_model, res_id), or (False, False) if not found."""
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
        """Return (model, res_id) for the given module and xml_id, but only if the
        current user has read access to that record. Otherwise raise an AccessError
        if ``raise_on_access_error`` is True, or return (model, False).
        """
        model, res_id = self._xmlid_lookup(f"{module}.{xml_id}")
        # search by id to verify the current user has read access
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
        """Copy xmlids, suffixing ``name`` to avoid UniqueIndex collisions."""
        vals_list = super().copy_data(default=default)
        for model, vals in zip(self, vals_list, strict=True):
            rand = f"{random.getrandbits(16):04x}"
            vals["name"] = f"{model.name}_{rand}"
        return vals_list

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Create xmlids, busting the groups cache for res.groups rows."""
        res = super().create(vals_list)
        if any(vals.get("model") == "res.groups" for vals in vals_list):
            self.env.registry.clear_cache("groups")
        return res

    def write(self, vals: dict[str, Any]) -> bool:
        """Update xmlids, busting the _xmlid_lookup cache and the groups cache for res.groups rows."""
        if not self:
            # do not clear caches for a no-op write on an empty recordset
            return True
        # _xmlid_lookup caches (model, res_id) keyed on module.name; a
        # noupdate-only write can't stale it, so skip the default cache bust on
        # the common toggle_noupdate path (IMD-P1).
        bust_xmlid = not (set(vals) <= {"noupdate"})
        # Clear the `groups` cache if the pre- or post-image points at
        # res.groups: re-pointing or editing such an xmlid must not leave
        # group/ACL resolution stale. Read `self` before super().write so the
        # pre-image model is still accurate.
        touch_groups = vals.get("model") == "res.groups" or any(
            data.model == "res.groups" for data in self
        )
        res = super().write(vals)
        if bust_xmlid:
            # Flush BEFORE clearing: super().write only marks rows dirty.
            # _xmlid_lookup reads via raw SQL (no ORM flush), so evicting while
            # the DB still holds the pre-write row lets the next env.ref()
            # re-cache the stale value. Push the UPDATE first, then evict.
            self.flush_recordset()
            self.env.registry.clear_cache()  # _xmlid_lookup
        if touch_groups:
            self.env.registry.clear_cache("groups")
        return res

    def unlink(self) -> bool:
        """Unlink, clearing the _xmlid_lookup cache and the groups cache for res.groups rows."""
        if not self:
            # do not clear caches for a no-op unlink on an empty recordset
            return True
        self.env.registry.clear_cache()  # _xmlid_lookup
        if any(data.model == "res.groups" for data in self.exists()):
            self.env.registry.clear_cache("groups")
        return super().unlink()

    def _lookup_xmlids(self, xml_ids: list[str], model: Any) -> list[tuple]:
        """Look up the given XML ids of the given model."""
        if not xml_ids:
            return []

        bymodule = defaultdict(set)
        for xml_id in xml_ids:
            prefix, suffix = xml_id.split(".", 1)
            bymodule[prefix].add(suffix)

        # query xml_ids by prefix; the joined table identifier is invariant, so
        # build it once (IMD-S1: SQL wrapper, not f-string, for the table name)
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
        """Create or update the given XML ids.

        :param data_list: list of dicts with keys `xml_id` (XMLID to
            assign), `noupdate` (flag on XMLID), `record` (target record).
        :param update: should be ``True`` when upgrading a module
        """
        if not data_list:
            return

        rows = OrderedSet()
        for data in data_list:
            prefix, suffix = data["xml_id"].split(".", 1)
            record = data["record"]
            noupdate = bool(data.get("noupdate"))
            rows.add((prefix, suffix, record._name, record.id, noupdate))

        for sub_rows in batched(rows, self.env.cr.BATCH_SIZE, strict=False):
            query = self._build_update_xmlids_query(sub_rows, update)
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
                        # optimisation: during install many xmlids are upserted;
                        # set the cache value directly instead of clearing it
                        self._xmlid_lookup.__cache__.add_value(
                            self,
                            f"{module}.{name}",
                            cache_value=(model, res_id),
                        )
                        if create_date != write_date:
                            # something was updated, notify other workers.
                            # equal create/write dates mean it was created in
                            # this transaction; no need to invalidate others.
                            self.env.registry.cache_invalidated.add("default")

            except Exception:
                _logger.error(
                    "Failed to insert ir_model_data\n%s",
                    "\n".join(str(row) for row in sub_rows),
                )
                raise

        xml_ids = {f"{row[0]}.{row[1]}" for row in rows}
        self.pool.loaded_xmlids.update(xml_ids)
        # tee for modules.loading.load_data: while a data file is being
        # converted, it records which xmlids the file asserts, so an upgrade
        # can later skip the unchanged file yet still mark those xmlids loaded
        # (protecting the records from _process_end's orphan cleanup)
        recorder = getattr(self.pool, "_xmlid_recorder", None)
        if recorder is not None:
            recorder.update(xml_ids)

        if any(row[2] == "res.groups" for row in rows):
            self.env.registry.clear_cache("groups")

    # Overridden in web_studio; keep any further override compatible with it.
    def _insert_xmlids_extra_columns(self) -> dict[str, SQL]:
        """Extra constant-valued columns appended to each xmlid row inserted by
        :meth:`_build_update_xmlids_query`, as ``{column_name: SQL value}``.
        """
        return {}

    def _build_update_xmlids_query(self, sub_rows: list[tuple], update: bool) -> SQL:
        """Build the upsert query for one batch of xmlid rows.

        Each row of ``sub_rows`` is ``(module, name, model, res_id, noupdate)``;
        the resulting :class:`~odoo.tools.SQL` carries its own parameters.
        """
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
        """Mark the given XML id as loaded, and return the corresponding record."""
        record = self.env.ref(xml_id, raise_if_not_found=False)
        if record:
            self.pool.loaded_xmlids.add(xml_id)
            # see the recorder tee in _update_xmlids
            recorder = getattr(self.pool, "_xmlid_recorder", None)
            if recorder is not None:
                recorder.add(xml_id)
        return record

    @api.model
    def _module_data_uninstall(self, modules_to_remove: list[str]) -> None:
        """Delete all records (and their DB schema: tables, columns, FKs)
        referenced by the given modules' ir.model.data entries, unless another
        entry still references them. Deletion is ordered to maximise graceful
        removal. Part of a module's full uninstallation.
        """
        if not self.env.is_system():
            raise AccessError(
                _("Administrator access is required to uninstall a module")
            )

        # enable model/field deletion; disable prefetch so we don't read a
        # column that has been deleted
        self = self.with_context(
            **{MODULE_UNINSTALL_FLAG: True, "prefetch_fields": False}
        )

        records_items = []  # [(model, id)]
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

        # avoid prefetching fields about to be deleted: a recompute (via flush)
        # can run after the DB columns are dropped but before the new registry
        # is built, on a stale registry; prefetching a now-missing column would
        # then fail and block the uninstall.
        has_shared_field = False
        for ir_field in self.env["ir.model.fields"].browse(field_ids):
            model = self.pool.get(ir_field.model)
            if model is not None:
                field = model._fields.get(ir_field.name)
                if field is not None and field.prefetch:
                    if field._toplevel:
                        # the field is specific to this registry
                        field.prefetch = False
                    else:
                        # the field is shared across registries; don't modify it
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

        # external ids of records that cannot be deleted
        undeletable_ids = []

        def delete(records):
            # skip records with other external ids (owned by other modules)
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

            # special case for ir.model.fields
            if records._name == "ir.model.fields":
                missing = records - records.exists()
                if missing:
                    # delete orphan external ids now: an ir.model.field removed
                    # via ONDELETE CASCADE leaves an orphan ir.model.data, and
                    # accessing the missing record would raise MissingError
                    orphans = ref_data.filtered(lambda r: r.res_id in missing._ids)
                    _logger.info("Deleting orphan ir_model_data %s", orphans)
                    orphans.unlink()
                    # /!\ this must go before any field accesses on `records`
                    records -= missing
                # do not remove LOG_ACCESS_COLUMNS unless _log_access is False
                # on the model
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
                    # divide the batch in two, and recursively delete them
                    half_size = len(records) // 2
                    delete(records[:half_size])
                    delete(records[half_size:])

        # remove non-model records first, grouped by batches of the same model
        for model, items in groupby(unique(records_items), itemgetter(0)):
            ids = [item[1] for item in items]
            # we cannot guarantee that the ir.model.data points to an existing model
            if model in self.env:
                delete(self.env[model].browse(ids))
            else:
                _logger.info(
                    "Orphan ir.model.data records %s refer to unavailable model '%s'",
                    ids,
                    model,
                )

        # Remove copied views: after removing the modules' records (else
        # ondelete='restrict' may block a view) but before cleaning the DB
        # schema (else dependent fields may no longer exist).
        modules = self.env["ir.module.module"].search(
            [("name", "in", modules_to_remove)]
        )
        modules._remove_copied_views()

        delete(self.env["ir.model.constraint"].browse(unique(constraint_ids)))

        # Delete selection values before their field: dropping the field first
        # removes the column, so ondelete='cascade' values would never trigger
        # deletion of the referencing records.
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

        # some undeletable data may now be deletable after the cascade-deletes
        # and dropped tables above
        for data in self.browse(undeletable_ids).exists():
            if data.model not in self.env.registry:
                continue
            record = self.env[data.model].browse(data.res_id)
            try:
                with self.env.cr.savepoint():
                    if record.exists():
                        # record still exists: data is still undeletable, drop
                        # it from module_data
                        module_data -= data
                        continue
            except psycopg.ProgrammingError:
                # most likely the record's table no longer exists (so neither
                # does the record); exists() runs a raw SELECT. Also applies to
                # ir.model.fields, constraints, etc.
                pass
        module_data.unlink()

    @api.model
    def _process_end_unlink_record(self, record: Any) -> None:
        record.unlink()

    @api.model
    def _process_end(self, modules: list[str]) -> None:
        """Remove records dropped from updated module data.

        Called at the end of module loading to delete records no longer present
        in the data: those with an xml id whose module is in ir_model_data and
        noupdate is false, but which are not in self.pool.loaded_xmlids.
        """
        if not modules or tools.config.get("import_partial"):
            return

        bad_imd_ids = []
        self = self.with_context({MODULE_UNINSTALL_FLAG: True})
        loaded_xmlids = self.pool.loaded_xmlids

        query = """ SELECT id, module || '.' || name, model, res_id FROM ir_model_data
                    WHERE module = ANY(%s) AND res_id IS NOT NULL AND COALESCE(noupdate, false) != %s ORDER BY id DESC
                """
        self.env.cr.execute(query, (list(modules), True))
        for id, xmlid, model, res_id in self.env.cr.fetchall():
            if xmlid in loaded_xmlids:
                continue

            Model = self.env.get(model)
            if Model is None:
                continue

            # implicitly created _inherits parents get an external id (if their
            # descendant has one) so they're removed with the module, but that
            # id isn't provided on update; don't remove the xid or record if a
            # child was just updated
            keep = False
            for inheriting in (self.env[m] for m in Model._inherits_children):
                # ignore mixins
                if inheriting._abstract:
                    continue

                parent_field = inheriting._inherits[model]
                children = inheriting.with_context(active_test=False).search(  # noqa: E8507 — inherent: each row targets a different model/res_id
                    [(parent_field, "=", res_id)]
                )
                children_xids = {
                    xid
                    for xids in (children and children._get_external_ids().values())
                    for xid in xids
                }
                if children_xids & loaded_xmlids:
                    # at least one child was loaded
                    keep = True
                    break
            if keep:
                continue

            # if the record has other associated xids, only remove the xid
            if self.search_count(  # noqa: E8507 — inherent: per-xmlid check during module cleanup
                [
                    ("model", "=", model),
                    ("res_id", "=", res_id),
                    ("id", "!=", id),
                    ("id", "not in", bad_imd_ids),
                ]
            ):
                bad_imd_ids.append(id)
                continue

            _logger.info("Deleting %s@%s (%s)", res_id, model, xmlid)
            record = Model.browse(res_id)
            if record.exists():
                module = xmlid.split(".", 1)[0]
                record = record.with_context(module=module)
                self._process_end_unlink_record(record)
            else:
                bad_imd_ids.append(id)
        if bad_imd_ids:
            self.browse(bad_imd_ids).unlink()

        # Once all views are created create specific ones
        self.env["ir.ui.view"]._create_all_specific_views(modules)

        loaded_xmlids.clear()

    @api.model
    def toggle_noupdate(self, model: str, res_id: int) -> None:
        """Toggle the noupdate flag on the external id of the record"""
        self.env[model].browse(res_id).check_access("write")
        xids = self.search([("model", "=", model), ("res_id", "=", res_id)])
        # group by current value: at most two write() calls (one per flipped
        # value) instead of one per xid (IMD-P2)
        for noupdate, group in xids.grouped("noupdate").items():
            group.write({"noupdate": not noupdate})
