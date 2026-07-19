"""Data-export operations for BaseModel (ExportMixin).

The :meth:`export_data` pipeline resolves field paths, fetches values, injects
external ids, and formats rows for the web client / data export. Disjoint from
the ``load()`` import pipeline (see :mod:`.load`).
"""

import collections
import contextlib
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
    """Data-export operations, inherited by BaseModel."""

    __slots__ = ()

    def _ensure_xml_ids(self, skip: bool = False) -> Iterator[tuple[Self, str | None]]:
        """Create missing external ids for records in ``self``, and return an
        iterator of pairs ``(record, xmlid)`` for the records in ``self``.
        """
        if skip:
            return ((record, None) for record in self)

        if not self:
            return iter([])

        if not self._is_an_ordinary_table():
            raise UserError(
                f"You can not export the column ID of model {self._name}, because the "
                f"table {self._table} is not an ordinary table."
            )

        modname = "__export__"

        cr = self.env.cr
        cr.execute(
            SQL(
                """
            SELECT res_id, module, name
            FROM ir_model_data
            WHERE model = %s AND res_id = ANY(%s)
        """,
                self._name,
                list(self.ids),
            )
        )
        xids = {res_id: (module, name) for res_id, module, name in cr.fetchall()}

        def to_xid(record_id):
            module, name = xids[record_id]
            return f"{module}.{name}" if module else name

        # create missing xml ids
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

    def _export_rows(
        self, fields: list[list[str]], *, _is_toplevel_call: bool = True
    ) -> list[list]:
        """Export fields of the records in ``self``.

        :param fields: list of lists of fields to traverse
        :param _is_toplevel_call: internal recursion flag; do not pass externally
        :return: list of lists of corresponding values
        """
        import_compatible = self.env.context.get("import_compat", True)
        lines = []

        if not _is_toplevel_call:
            # {properties_field: {property_name: [property_type, {record_id: value}]}}
            cache_properties = self.env.cr.cache["export_properties_cache"]
        else:
            cache_properties = self.env.cr.cache["export_properties_cache"] = (
                defaultdict(dict)
            )
            self._export_fetch_fields(self, fields, cache_properties)

        for record in self:
            # main line of record, initially empty
            current = [""] * len(fields)
            lines.append(current)

            # primary fields already exported with their secondary field(s)
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
                    prop_name = None
                    if "." in name:  # properties field
                        fname, prop_name = name.split(".")
                        field = record._fields[fname]
                        field_type, cache_value = cache_properties[field].get(
                            prop_name, ("char", None)
                        )
                        value = cache_value.get(record.id, "") if cache_value else ""
                    else:  # normal field
                        field = record._fields[name]
                        field_type = field.type
                        value = record[name]

                    # convoluted, but kept this way to reproduce former behavior
                    if not is_recordset(value):
                        current[i] = field.convert_to_export(value, record)

                    elif import_compatible and field_type == "reference":
                        current[i] = f"{value._name},{value.id}"

                    else:
                        primary_done.add(name)
                        # recursively export the fields that follow name; use
                        # 'display_name' where no subfield is exported
                        fields2 = [
                            (p[1:] or ["display_name"] if p and p[0] == name else [])
                            for p in fields
                        ]

                        # in import_compat mode, m2m exports as a comma-separated
                        # list of xids or names in a single cell
                        if import_compatible and field_type == "many2many":
                            index = None
                            # find which subfield the user wants and its column
                            # (may not be the first one we encounter)
                            for name in ["id", "name", "display_name"]:
                                with contextlib.suppress(ValueError):
                                    index = fields2.index([name])
                                    break
                            if index is None:
                                # none found: default to display_name, first column
                                name = None
                                index = i

                            if name == "id":
                                xml_ids = [xid for _, xid in value._ensure_xml_ids()]
                                current[index] = ",".join(xml_ids)
                            else:
                                current[index] = (
                                    ",".join(value.mapped("display_name"))
                                    if value
                                    else ""
                                )
                            continue

                        lines2 = value._export_rows(fields2, _is_toplevel_call=False)
                        if lines2:
                            # merge first line with record's main line
                            for j, val in enumerate(lines2[0]):
                                if val or isinstance(val, (int, float)):
                                    current[j] = val
                            # append the other lines at the end
                            lines += lines2[1:]
                        else:
                            current[i] = ""

        # export xids only at toplevel
        if _is_toplevel_call and any(f[-1] == "id" for f in fields):
            self._inject_export_xids(lines, fields)

        if _is_toplevel_call:
            self.env.cr.cache.pop("export_properties_cache", None)

        return lines

    def _export_fill_properties_cache(
        self, records, fnames_by_path, fname, cache_properties
    ):
        """Fill the export cache for the ``fname`` properties field."""
        cache_properties_field = cache_properties[records._fields[fname]]

        # read() runs Properties.convert_to_read_multi
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
                    value = self.env[prop["comodel"]].browse(
                        [val[0] for val in value]
                    )
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
        """Recursively fill the cache of ``records`` for all ``field_paths``,
        including properties.
        """
        if not records:
            return

        fnames_by_path = dict(
            groupby(
                [
                    path
                    for path in field_paths
                    if path and path[0] not in ("id", ".id")
                ],
                lambda path: path[0],
            )
        )

        # fetch needed fields (drop the '.property_name' part)
        fnames = list(unique(fname.split(".")[0] for fname in fnames_by_path))
        records.fetch(fnames)
        for fname in fnames:
            field = records._fields[fname]
            if field.type == "properties":
                self._export_fill_properties_cache(
                    records, fnames_by_path, fname, cache_properties
                )

        # recurse on relational fields (incl. relational properties)
        for fname, paths in fnames_by_path.items():
            if "." in fname:  # properties field
                fname, prop_name = fname.split(".")
                field = records._fields[fname]
                # raise (not assert): under python -O a dotted non-property
                # field would silently export blank data.
                if not (field.type == "properties" and prop_name):
                    raise ValueError(
                        f"export expected a properties subfield, got {field!r}.{prop_name!r}"
                    )

                property_type, property_cache = cache_properties[field].get(
                    prop_name, ("char", None)
                )
                if (
                    property_type not in ("many2one", "many2many")
                    or not property_cache
                ):
                    continue
                model = next(iter(property_cache.values())).browse()
                subrecords = model.union(
                    *[
                        property_cache[rec_id]
                        for rec_id in records.ids
                        if rec_id in property_cache
                    ]
                )
            else:  # normal field
                field = records._fields[fname]
                if not field.relational:
                    continue
                subrecords = records[fname]

            paths = [path[1:] or ["display_name"] for path in paths]
            self._export_fetch_fields(subrecords, paths, cache_properties)

    def _inject_export_xids(self, lines, fields):
        """Resolve ``(model, id)`` placeholder cells in ``lines`` to xml-ids."""
        bymodels = collections.defaultdict(set)
        xidmap = collections.defaultdict(list)
        # collect the (model, id) tuples in "lines" with their coordinates
        for i, line in enumerate(lines):
            for j, cell in enumerate(line):
                if isinstance(cell, tuple):
                    bymodels[cell[0]].add(cell[1])
                    xidmap[cell].append((i, j))
        # per model, resolve xids and inject them into the matrix
        for model, ids in bymodels.items():
            for record, xid in self.env[model].browse(ids)._ensure_xml_ids():
                for i, j in xidmap.pop((record._name, record.id)):
                    lines[i][j] = xid
        # raise (not assert): under python -O leftover xids would ship raw
        # (model, id) tuples in exported cells.
        if xidmap:
            raise RuntimeError(
                "failed to export xids for "
                + ", ".join(f"{k}:{v}" for k, v in xidmap.items())
            )

    def export_data(self, fields_to_export: list[str]) -> dict[str, list]:
        """Export fields for selected objects, for the client's export menu.

        :param fields_to_export: list of fields
        :returns: dictionary with a *datas* matrix
        """
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
