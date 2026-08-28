import collections
import logging
import typing
import uuid
from collections import defaultdict
from typing import Self

from odoo.exceptions import UserError
from odoo.tools import SQL, groupby, unique
from odoo.tools.translate import _

from ..._recordset import is_recordset
from ...parsing import fix_import_export_id_paths
from ._model_stubs import _ModelStubs

_logger = logging.getLogger("odoo.models")


if typing.TYPE_CHECKING:
    from collections.abc import Iterator


class ExportMixin(_ModelStubs):
    __slots__ = ()

    def _ensure_xml_ids(self, skip: bool = False) -> Iterator[tuple[Self, str | None]]:
        if skip:
            return ((record, None) for record in self)

        if not self:
            return iter([])

        if not self._is_an_ordinary_table():
            raise UserError(
                self.env._(
                    "You can not export the column ID of model %(model)s, because the"
                    " table %(table)s is not an ordinary table.",
                    model=self._name,
                    table=self._table,
                )
            )

        modname = "__export__"

        cr = self.env.cr
        cr.execute(
            SQL(
                """
            SELECT res_id, module, name
            FROM ir_model_data
            WHERE model = %s AND res_id = ANY(%s)
            ORDER BY id
        """,
                self._name,
                list(self.ids),
            )
        )
        xids: dict[int, tuple[str, str]] = {}
        for res_id, module, name in cr.fetchall():
            xids.setdefault(res_id, (module, name))

        def to_xid(record_id):
            module, name = xids[record_id]
            return f"{module}.{name}" if module else name

        missing = self.filtered(lambda r: r.id not in xids)
        if not missing:
            return ((record, to_xid(record.id)) for record in self)

        xids.update(
            (
                r.id,
                (
                    modname,
                    f"{r._table}_{r.id}_{uuid.uuid4().hex[:8]}",
                ),
            )
            for r in missing
        )
        fields = ["module", "model", "name", "res_id"]

        cr.copy_from(
            "ir_model_data",
            fields,
            [
                (modname, record._name, xids[record.id][1], record.id)
                for record in missing
            ],
        )
        self.env["ir.model.data"].invalidate_model(fields)

        return ((record, to_xid(record.id)) for record in self)

    def _export_get_cell_value(self, record, name, cache_properties):
        """Resolve the export path segment `name` against `record`.

        A dotted segment names a property inside a properties field, whose
        type and value come from the pre-filled cache rather than from the
        field itself.

        :return: (field, field_type, value)
        """
        if "." in name:
            fname, prop_name = name.split(".")
            field = record._fields[fname]
            field_type, cache_value = cache_properties[field].get(
                prop_name, ("char", None)
            )
            value = cache_value.get(record.id, "") if cache_value else ""
        else:
            field = record._fields[name]
            field_type = field.type
            value = record[name]
        return field, field_type, value

    def _export_get_many2many_cell(self, value, fields2, index_fallback):
        """Render an import-compatible many2many as one comma-joined cell.

        The column it lands in is the first of `.id`, `id`, `name` and
        `display_name` the caller asked for, and how the records are spelled
        follows from which one that was; with none of them asked for, the
        cell stays where the caller had it.

        :return: (index, text)
        """
        index = None
        subfield = None
        for candidate in (".id", "id", "name", "display_name"):
            target = (candidate,)
            index = next(
                (pos for pos, f2 in enumerate(fields2) if tuple(f2) == target),
                None,
            )
            if index is not None:
                subfield = candidate
                break
        if index is None:
            index = index_fallback

        if subfield == "id":
            text = ",".join(xid for _, xid in value._ensure_xml_ids())
        elif subfield == ".id":
            text = ",".join(str(rec_id) for rec_id in value.ids)
        else:
            text = ",".join(value.mapped("display_name")) if value else ""
        return index, text

    def _export_rows(
        self, fields: list[list[str]], *, _is_toplevel_call: bool = True
    ) -> list[list]:
        import_compatible = self.env.context.get("import_compat", True)
        lines = []

        if not _is_toplevel_call:
            cache_properties = self.env.cr.cache["export_properties_cache"]
        else:
            cache_properties = self.env.cr.cache["export_properties_cache"] = (
                defaultdict(dict)
            )
            self._export_fetch_fields(self, fields, cache_properties)

        for record in self:
            current = [""] * len(fields)
            lines.append(current)

            primary_done = set()

            for i, path in enumerate(fields):
                if not path:
                    continue

                name = path[0]
                if name in primary_done:
                    continue

                if name == ".id":
                    current[i] = str(record.id)
                elif name == "id":
                    current[i] = (record._name, record.id)
                else:
                    field, field_type, value = self._export_get_cell_value(
                        record, name, cache_properties
                    )

                    if not is_recordset(value):
                        current[i] = field.convert_to_export(value, record)

                    elif import_compatible and field_type == "reference":
                        current[i] = f"{value._name},{value.id}"

                    else:
                        primary_done.add(name)
                        fields2 = [
                            (p[1:] or ["display_name"] if p and p[0] == name else [])
                            for p in fields
                        ]

                        if import_compatible and field_type == "many2many":
                            index, text = self._export_get_many2many_cell(
                                value, fields2, i
                            )
                            current[index] = text
                            continue

                        lines2 = value._export_rows(fields2, _is_toplevel_call=False)
                        if lines2:
                            for j, val in enumerate(lines2[0]):
                                if val or isinstance(val, (int, float)):
                                    current[j] = val
                            lines += lines2[1:]
                        else:
                            current[i] = ""

        if _is_toplevel_call and any(f[-1] == "id" for f in fields):
            self._inject_export_xids(lines, fields)

        if _is_toplevel_call:
            self.env.cr.cache.pop("export_properties_cache", None)

        return lines

    def _export_fill_properties_cache(
        self, records, fnames_by_path, fname, cache_properties
    ):
        cache_properties_field = cache_properties[records._fields[fname]]

        for row in records.read([fname]):
            properties = row[fname]
            if not properties:
                continue
            rec_id = row["id"]

            for prop in properties:
                current_prop_name = prop["name"]
                if f"{fname}.{current_prop_name}" not in fnames_by_path:
                    continue
                property_type = prop["type"]
                if current_prop_name not in cache_properties_field:
                    cache_properties_field[current_prop_name] = [property_type, {}]

                __, cache_by_id = cache_properties_field[current_prop_name]
                if rec_id in cache_by_id:
                    continue

                value = prop.get("value")
                if property_type in ("many2one", "many2many"):
                    if not isinstance(value, list):
                        value = [value] if value else []
                    value = self.env[prop["comodel"]].browse([val[0] for val in value])
                elif property_type == "tags" and value:
                    value = ",".join(
                        next(
                            iter(tag[1] for tag in prop["tags"] if tag[0] == v),
                            "",
                        )
                        for v in value
                    )
                elif property_type == "selection":
                    value = dict(prop["selection"]).get(value, "")
                cache_by_id[rec_id] = value

    def _export_fetch_fields(self, records, field_paths, cache_properties):
        if not records:
            return

        fnames_by_path = dict(
            groupby(
                [path for path in field_paths if path and path[0] not in ("id", ".id")],
                lambda path: path[0],
            )
        )

        fnames = list(unique(fname.split(".")[0] for fname in fnames_by_path))
        records.fetch(fnames)
        for fname in fnames:
            field = records._fields[fname]
            if field.is_properties:
                self._export_fill_properties_cache(
                    records, fnames_by_path, fname, cache_properties
                )

        for fname, paths in fnames_by_path.items():
            if "." in fname:
                fname, prop_name = fname.split(".")
                field = records._fields[fname]
                if not (field.is_properties and prop_name):
                    raise ValueError(
                        f"export expected a properties subfield, got {field!r}.{prop_name!r}"
                    )

                property_type, property_cache = cache_properties[field].get(
                    prop_name, ("char", None)
                )
                if property_type not in ("many2one", "many2many") or not property_cache:
                    continue
                model = next(iter(property_cache.values())).browse()
                subrecords = model.union(
                    *[
                        property_cache[rec_id]
                        for rec_id in records.ids
                        if rec_id in property_cache
                    ]
                )
            else:
                field = records._fields[fname]
                if not field.relational:
                    continue
                subrecords = records[fname]

            paths = [path[1:] or ["display_name"] for path in paths]
            self._export_fetch_fields(subrecords, paths, cache_properties)

    def _inject_export_xids(self, lines, fields):
        bymodels = collections.defaultdict(set)
        xidmap = collections.defaultdict(list)
        for i, line in enumerate(lines):
            for j, cell in enumerate(line):
                if isinstance(cell, tuple):
                    bymodels[cell[0]].add(cell[1])
                    xidmap[cell].append((i, j))
        for model, ids in bymodels.items():
            for record, xid in self.env[model].browse(ids)._ensure_xml_ids():
                for i, j in xidmap.pop((record._name, record.id)):
                    lines[i][j] = xid
        if xidmap:
            raise RuntimeError(
                "failed to export xids for "
                + ", ".join(f"{k}:{v}" for k, v in xidmap.items())
            )

    def export_data(self, fields_to_export: list[str]) -> dict[str, list]:
        if not (
            self.env.is_admin() or self.env.user.has_group("base.group_allow_export")
        ):
            raise UserError(
                _(
                    "You don't have the rights to export data. Please contact an Administrator."
                )
            )
        fields_to_export = [fix_import_export_id_paths(f) for f in fields_to_export]
        return {"datas": self._export_rows(fields_to_export)}
