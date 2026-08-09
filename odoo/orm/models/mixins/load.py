import functools
import itertools
import logging
import re
import typing
from collections import defaultdict
from typing import Self

import psycopg

from odoo.db import schema as sql
from odoo.exceptions import UserError, ValidationError
from odoo.libs.lru import LRU
from odoo.tools.translate import _

from ... import decorators as api
from ..._typing import ValuesType
from ...helpers import itemgetter_tuple
from ...parsing import fix_import_export_id_paths
from ._model_stubs import _ModelStubs

_logger = logging.getLogger("odoo.models")


if typing.TYPE_CHECKING:
    from collections.abc import Callable, Generator


class LoadMixin(_ModelStubs):
    __slots__ = ()

    @api.model
    def load(self, fields: list[str], data: list[list[str]]) -> dict:
        from ...fields.relational import One2many

        mode = self.env.context.get("mode", "init")
        current_module = self.env.context.get("module", "__import__")
        noupdate = self.env.context.get("noupdate", False)
        self = self.with_context(_import_current_module=current_module)

        cr = self.env.cr

        fields = [fix_import_export_id_paths(f) for f in fields]

        ids = []
        messages = []

        batch = []
        batch_xml_ids = set()
        creatable_models = {self._name}
        if invalid := self._invalid_load_paths(fields):
            return {"ids": False, "messages": invalid, "nextrow": 0}

        for field_path in fields:
            if field_path[0] in (None, "id", ".id"):
                continue
            model_fields = self._fields
            for field_name in field_path:
                if field_name in (None, "id", ".id"):
                    break

                if isinstance(o2m_field := model_fields.get(field_name), One2many):
                    comodel = o2m_field.comodel_name
                    creatable_models.add(comodel)
                    model_fields = self.env[comodel]._fields

        def flush(*, xml_id=None, model=None):
            if not batch:
                return

            if xml_id and model:
                raise ValueError(
                    "flush can specify *either* an external id or a model, not both"
                )

            if xml_id and xml_id not in batch_xml_ids:
                return
            if model and model not in creatable_models:
                return

            data_list = [
                {"xml_id": xid, "values": vals, "info": info, "noupdate": noupdate}
                for xid, vals, info in batch
            ]
            batch.clear()
            batch_xml_ids.clear()

            global_error_message = None
            try:
                with cr.savepoint():
                    recs = self._load_records(data_list, mode == "update")
                    ids.extend(recs.ids)
                return
            except psycopg.InternalError as e:
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
            for i, rec_data in enumerate(data_list, 1):
                try:
                    with cr.savepoint():
                        rec = self._load_records([rec_data], mode == "update")
                        cr.flush()
                    ids.append(rec.id)
                except psycopg.Warning as e:
                    messages.append(
                        dict(rec_data["info"], type="warning", message=str(e))
                    )
                except psycopg.Error as e:
                    info = rec_data["info"]
                    pg_error_info = {"message": self._sql_error_to_message(e)}
                    if e.diag.table_name == self._table:
                        e_fields = sql.constraint_columns(
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
                messages.insert(0, global_error_message)

        flush_recordset = self.with_context(import_flush=flush, import_cache=LRU(1024))

        limit = self.env.context.get("_import_limit")
        if limit is None:
            limit = float("inf")

        skip_fields = self._import_skip_fields()
        info = {"rows": {"to": -1}}
        savepoint = cr.savepoint()
        try:
            extracted = flush_recordset._extract_records(
                fields, data, log=messages.append, limit=limit
            )
            converted = flush_recordset._convert_records(extracted, log=messages.append)
            for id, xid, record, info in converted:
                if any(record.get(field, False) is None for field in skip_fields):
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
                self.pool.reset_changes()
        except Exception:
            savepoint.close(rollback=True)
            raise
        savepoint.close(rollback=False)

        nextrow = info["rows"]["to"] + 1
        if nextrow < limit:
            nextrow = 0
        return {
            "ids": ids,
            "messages": messages,
            "nextrow": nextrow,
        }

    @api.model
    def _import_skip_fields(self) -> frozenset[str]:
        context = self.env.context
        if not context.get("import_file"):
            return frozenset()
        return frozenset(
            re.split(r"[/.]", path, maxsplit=1)[0]
            for path in context.get("import_skip_records") or []
        )

    @api.model
    def _invalid_load_paths(self, field_paths: list[tuple[str | None, ...]]) -> list[dict]:
        """ Report column mappings that descend through something with no
        sub-fields, e.g. ``name/foo`` where ``name`` is a Char.

        ``load`` validated this asymmetrically: a bad subpath under a relation
        (``parent_id/nope``) was refused, while one under a scalar was silently
        truncated to its first segment and imported there -- ``name/foo`` set
        ``name``. So a mapping the user cannot have meant produced a record
        anyway, and the only signal was the absence of one.

        Reported rather than raised, and reported before any row is touched, so
        the caller gets the same ``{ids, messages}`` shape it gets for every
        other import error.

        :param field_paths: paths already split by :func:`fix_import_export_id_paths`
        :returns: one message dict per unusable path, empty when all are usable
        :rtype: list[dict]
        """
        messages = []
        for field_path in field_paths:
            if not field_path or field_path[0] in (None, "id", ".id"):
                continue
            model = self
            for index, field_name in enumerate(field_path[:-1]):
                if field_name in (None, "id", ".id"):
                    break
                field = model._fields.get(field_name)
                if field is None:
                    # Unknown field: already reported per row, with the model
                    # name, by the converter. Don't pre-empt it with a worse
                    # message.
                    break
                if not field.relational:
                    messages.append({
                        "type": "error",
                        "rows": {"from": 0, "to": 0},
                        "record": 0,
                        "field": field_path[0],
                        "field_path": list(field_path),
                        "message": _(
                            "Column %(path)s cannot be imported: %(field)s is not a "
                            "relation on model %(model)s, so it has no sub-fields.",
                            path="/".join(field_path),
                            field="/".join(field_path[: index + 1]),
                            model=model._name,
                        ),
                    })
                    break
                model = self.env[field.comodel_name]
        return messages

    def _extract_records(
        self,
        field_paths: list[list[str | None]],
        data: list[list[str]],
        log: Callable = lambda a: None,
        limit: float = float("inf"),
    ) -> Generator[tuple[dict, dict]]:
        fields = self._fields

        get_o2m_values = itemgetter_tuple(
            [
                index
                for index, fnames in enumerate(field_paths)
                if (fname0 := fnames[0]) is not None
                and fname0 in fields
                and fields[fname0].type == "one2many"
            ]
        )
        get_nono2m_values = itemgetter_tuple(
            [
                index
                for index, fnames in enumerate(field_paths)
                if (fname0 := fnames[0]) is None
                or fname0 not in fields
                or fields[fname0].type != "one2many"
            ]
        )

        def only_o2m_values(row):
            return any(get_o2m_values(row)) and not any(get_nono2m_values(row))

        property_definitions = {}
        property_columns = defaultdict(list)
        for fname, *__ in field_paths:
            if not fname:
                continue
            f_prop_name, sep, property_name = fname.partition(".")
            if not sep:
                continue
            if f_prop_name not in fields or fields[f_prop_name].type != "properties":
                continue

            definition = self.get_property_definition(fname)
            if not definition:
                raise ValueError(
                    f"Property {property_name!r} doesn't have any definition on {fname!r} field"
                )

            property_definitions[fname] = definition
            property_columns[f_prop_name].append(fname)

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

            record = {
                fnames[0]: value
                for fnames, value in zip(field_paths, row, strict=False)
                if not is_relational(fnames[0])
            }

            record_span = itertools.takewhile(
                only_o2m_values,
                (data[j] for j in range(index + 1, len(data))),
            )
            record_span = list(itertools.chain([row], record_span))

            for relfield, *__ in field_paths:
                if relfield is None or not is_relational(relfield):
                    continue

                if relfield not in property_definitions:
                    comodel = self.env[fields[relfield].comodel_name]
                else:
                    comodel = self.env[property_definitions[relfield]["comodel"]]

                indices, subfields = zip(
                    *(
                        (index, fnames[1:] or [None])
                        for index, fnames in enumerate(field_paths)
                        if fnames[0] == relfield
                    ),
                    strict=False,
                )

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
    ) -> Generator[tuple[int | bool, str | bool, dict, dict]]:
        field_names = {name: field.string for name, field in self._fields.items()}
        if self.env.lang:
            field_names.update(self.env["ir.model.fields"].get_field_string(self._name))

        convert = self.env["ir.fields.converter"].for_model(self)

        def _log(base, record, field, exception):
            type = "warning" if isinstance(exception, Warning) else "error"
            field_name = field_names.get(field, field)
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
        to_write = {}
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
            self._clean_properties()

    def _load_records_create(self, vals_list: list[ValuesType]) -> Self:
        records = self.create(vals_list)
        if any(field.type == "properties" for field in self._fields.values()):
            records._clean_properties()
        return records

    def _load_records(self, data_list: list[dict], update: bool = False) -> Self:
        original_self = self.browse()

        imd = self.env["ir.model.data"].sudo()

        xml_ids = [data["xml_id"] for data in data_list if data.get("xml_id")]
        existing = {
            f"{row[1]}.{row[2]}": row for row in imd._lookup_xmlids(xml_ids, self)
        }

        to_create = []
        to_update = []
        imd_data_list = []

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
                raise ValidationError(
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

        for data in to_update:
            data["record"]._load_records_write(data["values"])

        self._load_records_warn_foreign_module(to_create)
        self._load_records_check_import_prefix(to_create)

        if to_create:
            records = self._load_records_create([data["values"] for data in to_create])
            for data, record in zip(to_create, records, strict=True):
                data["record"] = record
                if data.get("xml_id"):
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

        imd._update_xmlids(imd_data_list, update)

        return original_self.concat(*(data["record"] for data in data_list))

    def _load_records_warn_foreign_module(self, to_create: list[dict]) -> None:
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
