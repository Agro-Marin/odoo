"""Data-import operations for BaseModel (LoadMixin): the ``load()`` pipeline.

``load()`` ingests an external data matrix (e.g. CSV import): it extracts and
converts records, then creates/updates them in batches with per-record error
recovery. Disjoint from the export pipeline (see :mod:`.export`).
"""

import functools
import itertools
import logging
import typing
from collections import defaultdict
from typing import Self

import psycopg

from odoo.exceptions import UserError, ValidationError
from odoo.libs.lru import LRU
from odoo.tools.translate import _

from ... import decorators as api
from ..._typing import ValuesType
from ...helpers import get_columns_from_sql_diagnostics, itemgetter_tuple
from ...parsing import fix_import_export_id_paths
from ._model_stubs import _ModelStubs

_logger = logging.getLogger("odoo.models")


if typing.TYPE_CHECKING:
    from collections.abc import Callable, Generator


class LoadMixin(_ModelStubs):
    """Data-import (``load()``) operations, inherited by BaseModel."""

    __slots__ = ()

    @api.model
    def load(self, fields: list[str], data: list[list[str]]) -> dict:
        """Attempt to load the data matrix, and return a list of ids (or
        ``False`` if there was an error and no id could be generated) and a
        list of messages.

        The ids are those of the records created and saved (in database), in
        the same order they were extracted from the file. They can be passed
        directly to :meth:`~read`.

        :param fields: fields to import, at the same index as their data column
        :param data: row-major matrix of data to import
        :returns: ``{ids: list[int] | False, messages: list[dict], nextrow: int}``
        """
        from ...fields.relational import One2many

        mode = self.env.context.get("mode", "init")
        current_module = self.env.context.get("module", "__import__")
        noupdate = self.env.context.get("noupdate", False)
        # current module is needed in context for xml-id conversion
        self = self.with_context(_import_current_module=current_module)

        cr = self.env.cr
        # Savepoint strategy (three roles, see ``CheckSavepoint`` tests):
        #   1. this load-wide savepoint: the whole load is atomic, so any
        #      recorded error rolls everything back (``ids`` becomes False);
        #   2. one savepoint around each batch's fast-path bulk create (below);
        #   3. on bulk-create failure, one savepoint per record in the row-by-row
        #      recovery -- lets each record see the true prior state (so conflicts
        #      are attributed to the right row) and rolls a failed record back in
        #      isolation, keeping the ids of already-succeeded records. The
        #      conflict-free path never reaches it, and base_import bounds each
        #      load() to a batch, so recovery cost stays bounded per transaction.
        savepoint = cr.savepoint()

        fields = [fix_import_export_id_paths(f) for f in fields]

        ids = []
        messages = []

        # list of (xid, vals, info) for records to be created in batch
        batch = []
        batch_xml_ids = set()
        # models that may need flushing before a name_search (we create/modify
        # data in them): the root model and any o2m comodel
        creatable_models = {self._name}
        for field_path in fields:
            if field_path[0] in (None, "id", ".id"):
                continue
            model_fields = self._fields
            for field_name in field_path:
                if field_name in (None, "id", ".id"):
                    break

                if isinstance(model_fields.get(field_name), One2many):
                    comodel = model_fields[field_name].comodel_name
                    creatable_models.add(comodel)
                    model_fields = self.env[comodel]._fields

        def flush(*, xml_id=None, model=None):
            if not batch:
                return

            # raise (not assert): xml_id/model mutual exclusivity is a caller
            # contract that must hold under python -O.
            if xml_id and model:
                raise ValueError(
                    "flush can specify *either* an external id or a model, not both"
                )

            if xml_id and xml_id not in batch_xml_ids:
                # The referenced xid is not pending in the current batch, so
                # flushing the batch cannot resolve it — skip. (The former
                # ``xml_id not in self.env`` tested the xid against model *names*
                # via ``Environment.__contains__``, which only skipped when the
                # xid did not happen to collide with a model name.)
                return
            if model and model not in creatable_models:
                return

            data_list = [
                {"xml_id": xid, "values": vals, "info": info, "noupdate": noupdate}
                for xid, vals, info in batch
            ]
            batch.clear()
            batch_xml_ids.clear()

            # try to create in batch
            global_error_message = None
            try:
                with cr.savepoint():
                    recs = self._load_records(data_list, mode == "update")
                    ids.extend(recs.ids)
                return
            except psycopg.InternalError as e:
                # broken transaction: bail and hope the source error was logged
                if not any(message["type"] == "error" for message in messages):
                    info = data_list[0]["info"]
                    messages.append(
                        dict(
                            info,
                            type="error",
                            message=_("Unknown database error: '%s'", e),
                        )
                    )
                return
            except UserError as e:
                global_error_message = dict(
                    data_list[0]["info"], type="error", message=str(e)
                )
            except Exception:
                _logger.debug(
                    "Batch load failed, retrying record by record", exc_info=True
                )

            errors = 0
            # Retry record by record. Each record runs in its OWN savepoint, so a
            # failure rolls back only that record's partial work and leaves
            # already-succeeded records (and their ids) intact, while the failed
            # record's error is attributed to the right row. (Under psycopg3,
            # server notices/warnings never raise — they go to notice handlers —
            # so only real errors reach the except clauses below.)
            for i, rec_data in enumerate(data_list, 1):
                try:
                    with cr.savepoint():
                        rec = self._load_records([rec_data], mode == "update")
                        cr.flush()  # surface flush exceptions inside the savepoint
                    ids.append(rec.id)
                except psycopg.Error as e:
                    info = rec_data["info"]
                    pg_error_info = {"message": self._sql_error_to_message(e)}
                    if e.diag.table_name == self._table:
                        e_fields = get_columns_from_sql_diagnostics(
                            self.env.cr, e.diag, check_registry=True
                        )
                        if len(e_fields) == 1:
                            pg_error_info["field"] = e_fields[0]
                    messages.append(dict(info, type="error", **pg_error_info))
                    errors += 1
                except UserError as e:
                    info = rec_data["info"]
                    messages.append(dict(info, type="error", message=str(e)))
                    errors += 1
                except Exception as e:
                    _logger.debug("Error while loading record", exc_info=True)
                    info = rec_data["info"]
                    message = _(
                        "Unknown error during import: %(error_type)s: %(error_message)s",
                        error_type=e.__class__,
                        error_message=e,
                    )
                    moreinfo = _("Resolve other errors first")
                    messages.append(
                        dict(
                            info,
                            type="error",
                            message=message,
                            moreinfo=moreinfo,
                        )
                    )
                    errors += 1
                if errors >= 10 and (errors >= i / 10):
                    messages.append(
                        {
                            "type": "warning",
                            "message": _(
                                "Found more than 10 errors and more than one error per 10 records, interrupted to avoid showing too many errors."
                            ),
                        }
                    )
                    break
            if (
                errors > 0
                and global_error_message
                and global_error_message not in messages
            ):
                # 1-by-1 also failed: surface the original batch-create error
                messages.insert(0, global_error_message)

        # make 'flush' available to the methods below (e.g. when XMLID
        # resolution fails)
        flush_recordset = self.with_context(import_flush=flush, import_cache=LRU(1024))

        # Import limit comes via context: load()'s public (fields, data) API has
        # no parameter for it and changing it would break all callers.
        limit = self.env.context.get("_import_limit")
        if limit is None:
            limit = float("inf")
        extracted = flush_recordset._extract_records(
            fields, data, log=messages.append, limit=limit
        )

        converted = flush_recordset._convert_records(
            extracted, log=messages.append, savepoint=savepoint
        )

        info = {"rows": {"to": -1}}
        for id, xid, record, info in converted:
            if self.env.context.get("import_file") and self.env.context.get(
                "import_skip_records"
            ):
                if any(
                    record.get(field) is None
                    for field in self.env.context["import_skip_records"]
                ):
                    continue
            if xid:
                xid = xid if "." in xid else f"{current_module}.{xid}"
                batch_xml_ids.add(xid)
            elif id:
                record["id"] = id
            batch.append((xid, record, info))

        flush()
        if any(message["type"] == "error" for message in messages):
            savepoint.rollback()
            ids = False
            # undo registry/ormcache changes
            self.pool.reset_changes()
        savepoint.close(rollback=False)

        nextrow = info["rows"]["to"] + 1
        if nextrow < limit:
            nextrow = 0
        return {
            "ids": ids,
            "messages": messages,
            "nextrow": nextrow,
        }

    def _extract_records(
        self,
        field_paths: list[list[str | None]],
        data: list[list[str]],
        log: Callable = lambda a: None,
        limit: float = float("inf"),
    ) -> Generator[tuple[dict, dict]]:
        """Generate record dicts from the data sequence.

        Yields dicts mapping field names to raw (unconverted, unvalidated)
        values. For relational fields with sub-fields, the value is a list of
        sub-records.

        Special sub-field keys:

        * None: the display_name (for name_create/name_search)
        * "id": the External ID
        * ".id": the Database ID
        """
        fields = self._fields

        get_o2m_values = itemgetter_tuple(
            [
                index
                for index, fnames in enumerate(field_paths)
                if fnames[0] in fields and fields[fnames[0]].type == "one2many"
            ]
        )
        get_nono2m_values = itemgetter_tuple(
            [
                index
                for index, fnames in enumerate(field_paths)
                if fnames[0] not in fields or fields[fnames[0]].type != "one2many"
            ]
        )

        # Checks if the provided row has any non-empty one2many fields
        def only_o2m_values(row):
            return any(get_o2m_values(row)) and not any(get_nono2m_values(row))

        property_definitions = {}
        property_columns = defaultdict(list)
        for fname, *__ in field_paths:
            if not fname:
                continue
            if "." not in fname:
                if fname not in fields:
                    raise ValueError(f"Invalid field name {fname!r}")
                continue

            f_prop_name, property_name = fname.split(".")
            if f_prop_name not in fields or fields[f_prop_name].type != "properties":
                # Can be .id
                continue

            definition = self.get_property_definition(fname)
            if not definition:
                # Can happen if someone remove the property, UserError ?
                raise ValueError(
                    f"Property {property_name!r} doesn't have any definition on {fname!r} field"
                )

            property_definitions[fname] = definition
            property_columns[f_prop_name].append(fname)

        # m2o fields can't be on multiple lines so don't take it in account
        # for only_o2m_values rows filter, but special-case it later on to
        # be handled with relational fields (as it can have subfields).
        # Pre-compute set of relational field names for O(1) lookup per row
        relational_fnames = {fname for fname in fields if fields[fname].relational} | {
            fname
            for fname, defn in property_definitions.items()
            if defn.get("type") in ("many2one", "many2many")
        }

        def is_relational(fname):
            return fname in relational_fnames

        index = 0
        while index < len(data) and index < limit:
            row = data[index]

            # copy non-relational fields to record dict
            record = {
                fnames[0]: value
                for fnames, value in zip(field_paths, row, strict=False)
                if not is_relational(fnames[0])
            }

            # Get all following rows which have relational values attached to
            # the current record (no non-relational values)
            record_span = itertools.takewhile(
                only_o2m_values,
                (data[j] for j in range(index + 1, len(data))),
            )
            # stitch record row back on for relational fields
            record_span = list(itertools.chain([row], record_span))

            for relfield, *__ in field_paths:
                if not is_relational(relfield):
                    continue

                if relfield not in property_definitions:
                    comodel = self.env[fields[relfield].comodel_name]
                else:
                    comodel = self.env[property_definitions[relfield]["comodel"]]

                # get only cells for this sub-field, should be strictly
                # non-empty, field path [None] is for display_name field
                indices, subfields = zip(
                    *(
                        (index, fnames[1:] or [None])
                        for index, fnames in enumerate(field_paths)
                        if fnames[0] == relfield
                    ),
                    strict=False,
                )

                # return all rows which have at least one value for the
                # subfields of relfield
                relfield_data = [
                    it for it in map(itemgetter_tuple(indices), record_span) if any(it)
                ]
                record[relfield] = [
                    subrecord
                    for subrecord, _subinfo in comodel._extract_records(
                        subfields, relfield_data, log=log
                    )
                ]

            for (
                properties_fname,
                property_indexes_names,
            ) in property_columns.items():
                properties = []
                for property_name in property_indexes_names:
                    value = record.pop(property_name)
                    properties.append(
                        dict(**property_definitions[property_name], value=value)
                    )
                record[properties_fname] = properties

            yield (
                record,
                {
                    "rows": {
                        "from": index,
                        "to": index + len(record_span) - 1,
                    }
                },
            )
            index += len(record_span)

    @api.model
    def _convert_records(
        self,
        records: Generator[tuple[dict, dict]],
        *,
        log: Callable = lambda a: None,
        savepoint: typing.Any,
    ) -> Generator[tuple[int | bool, str | bool, dict, dict]]:
        """Convert source records (recursive dicts of strings) into forms
        writable to the database (via ``self.create`` or
        ``(ir.model.data)._update``).

        :returns: generator of ``(id, xid, converted_record, info)`` tuples
        """
        field_names = {name: field.string for name, field in self._fields.items()}
        if self.env.lang:
            field_names.update(self.env["ir.model.fields"].get_field_string(self._name))

        convert = (
            self.env["ir.fields.converter"]
            .with_context(import_savepoint=savepoint)
            .for_model(self)
        )

        def _log(base, record, field, exception):
            type = "warning" if isinstance(exception, Warning) else "error"
            # log the logical field name (for automated processing) but put the
            # human-readable name in the message
            field_name = field_names[field]
            exc_vals = dict(base, record=record, field=field_name)
            record = dict(
                base,
                type=type,
                record=record,
                field=field,
                message=str(exception.args[0]) % exc_vals,
            )
            if len(exception.args) > 1:
                info = {}
                if exception.args[1] and isinstance(exception.args[1], dict):
                    info = exception.args[1]
                # field_name lets import concatenate multiple errors per block
                info["field_name"] = field_name
                record.update(info)
            log(record)

        for stream_index, (record, extras) in enumerate(records):
            xid = record.get("id", False)
            dbid = False
            if record.get(".id"):
                try:
                    dbid = int(record[".id"])
                except ValueError:
                    # overridden (non-int) id column
                    dbid = record[".id"]
                if not self.search([("id", "=", dbid)]):
                    log(
                        dict(
                            extras,
                            type="error",
                            record=stream_index,
                            field=".id",
                            message=_("Unknown database identifier '%s'", dbid),
                        )
                    )
                    dbid = False

            converted = convert(record, functools.partial(_log, extras, stream_index))

            yield dbid, xid, converted, dict(extras, record=stream_index)

    def _load_records_write(self, values: ValuesType) -> None:
        self.ensure_one()
        to_write = {}  # defer properties write so a changed definition isn't reused
        for fname in list(values):
            if fname not in self._fields or self._fields[fname].type != "properties":
                continue
            field_converter = self._fields[fname].convert_to_cache
            to_write[fname] = dict(
                self[fname]._values or {},
                **field_converter(values.pop(fname), self, validate=False),
            )

        self.write(values)
        if to_write:
            self.write(to_write)
            # Clean properties now that they are written (optional — the client
            # would otherwise clean them on the next Form-view edit).
            self._clean_properties()

    def _load_records_create(self, vals_list: list[ValuesType]) -> Self:
        records = self.create(vals_list)
        if any(field.type == "properties" for field in self._fields.values()):
            records._clean_properties()
        return records

    def _load_records(self, data_list: list[dict], update: bool = False) -> Self:
        """Create or update records of this model, and assign XMLIDs.

        :param data_list: list of dicts with keys ``xml_id`` (XMLID to
            assign), ``noupdate`` (flag on XMLID), ``values`` (field values)
        :param update: should be ``True`` when upgrading a module
        :return: the records corresponding to ``data_list``
        """
        original_self = self.browse()

        imd = self.env["ir.model.data"].sudo()

        # partition 'data_list' into records to create / update / leave; set
        # data['record'] on each, then return them all.

        # determine existing xml_ids
        xml_ids = [data["xml_id"] for data in data_list if data.get("xml_id")]
        existing = {
            f"{row[1]}.{row[2]}": row for row in imd._lookup_xmlids(xml_ids, self)
        }

        # determine which records to create and update
        to_create = []  # list of data
        to_update = []  # list of data
        imd_data_list = []  # list of data for _update_xmlids()

        for data in data_list:
            xml_id = data.get("xml_id")
            if not xml_id:
                vals = data["values"]
                if vals.get("id"):
                    data["record"] = self.browse(vals["id"])
                    to_update.append(data)
                elif not update:
                    to_create.append(data)
                else:
                    raise ValidationError(
                        _("Cannot update a record without specifying its id or xml_id")
                    )
                continue
            row = existing.get(xml_id)
            if not row:
                to_create.append(data)
                continue
            d_id, _d_module, _d_name, d_model, d_res_id, d_noupdate, r_id = row
            if self._name != d_model:
                raise ValidationError(  # pylint: disable=missing-gettext
                    f"For external id {xml_id} "
                    f"when trying to create/update a record of model {self._name} "
                    f"found record of different model {d_model} ({d_id})"
                )
            record = self.browse(d_res_id)
            if r_id:
                data["record"] = record
                imd_data_list.append(data)
                if not (update and d_noupdate):
                    to_update.append(data)
            else:
                imd.browse(d_id).unlink()
                to_create.append(data)

        # update existing records
        for data in to_update:
            data["record"]._load_records_write(data["values"])

        self._load_records_warn_foreign_module(to_create)
        self._load_records_check_import_prefix(to_create)

        # create records
        if to_create:
            records = self._load_records_create([data["values"] for data in to_create])
            # strict=True: create() must return one record per vals dict; a
            # mismatch would otherwise drop data["record"] and fail later.
            for data, record in zip(to_create, records, strict=True):
                data["record"] = record
                if data.get("xml_id"):
                    # add XML ids for parent records that have just been created
                    for parent_model, parent_field in self._inherits.items():
                        if not data["values"].get(parent_field):
                            imd_data_list.append(
                                {
                                    "xml_id": f"{data['xml_id']}_{parent_model.replace('.', '_')}",
                                    "record": record[parent_field],
                                    "noupdate": data.get("noupdate", False),
                                }
                            )
                    imd_data_list.append(data)

        # create or update XMLIDs
        imd._update_xmlids(imd_data_list, update)

        return original_self.concat(*(data["record"] for data in data_list))

    def _load_records_warn_foreign_module(self, to_create: list[dict]) -> None:
        """Warn when creating a record whose XMLID belongs to another module."""
        module = self.env.context.get("install_module")
        if not module:
            return
        prefix = module + "."
        for data in to_create:
            if (
                data.get("xml_id")
                and not data["xml_id"].startswith(prefix)
                and not self.env.context.get("foreign_record_to_create")
            ):
                _logger.warning(
                    "Creating record %s in module %s.", data["xml_id"], module
                )

    def _load_records_check_import_prefix(self, to_create: list[dict]) -> None:
        """During a user import, reject XMLIDs prefixed with an existing module.

        Such a prefix would make the record be deleted on that module's next
        upgrade, so it is almost always a mistake.
        """
        if not self.env.context.get("import_file"):
            return
        existing_modules = self.env["ir.module.module"].sudo().search([]).mapped("name")
        for data in to_create:
            xml_id = data.get("xml_id")
            if xml_id and not data.get("noupdate"):
                module_name, sep, record_id = xml_id.partition(".")
                if sep and module_name in existing_modules:
                    raise UserError(
                        _(
                            "The record %(xml_id)s has the module prefix %(module_name)s. This is the part before the '.' in the external id. Because the prefix refers to an existing module, the record would be deleted when the module is upgraded. Use either no prefix and no dot or a prefix that isn't an existing module. For example, __import__, resulting in the external id __import__.%(record_id)s.",
                            xml_id=xml_id,
                            module_name=module_name,
                            record_id=record_id,
                        )
                    )
