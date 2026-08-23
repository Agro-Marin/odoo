import typing
from collections import defaultdict
from itertools import batched
from operator import attrgetter
from typing import Self

from odoo.libs.profiling import _n1_enabled, _OrmProfile
from odoo.tools import SQL, OrderedSet, clean_context
from odoo.tools.misc import PENDING

from ... import decorators as api
from ..._typing import ValuesType
from ...helpers import own_class_memo
from ...primitives import (
    INSERT_BATCH_SIZE,
    SQL_DEFAULT,
    Command,
)
from ._crud_common import (
    _BAD_NAMES_LOG,
    COPY_DISABLED,
    COPY_THRESHOLD,
    _orm_crud,
    bad_field_names,
)
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from ...fields.base import Field


class CreateMixin(_ModelStubs):
    __slots__ = ()

    @api.model
    def default_get(self, fields: list[str]) -> ValuesType:
        env = self.env
        _fields = self._fields
        defaults = {}
        parent_fields = defaultdict(list)
        ir_defaults = env["ir.default"]._get_model_defaults(self._name)
        context_defaults = env._context_defaults

        for name in fields:
            if name in context_defaults:
                defaults[name] = context_defaults[name]
                continue

            field = _fields.get(name)
            if not field:
                continue

            if not (field.default or field.inherited or name in ir_defaults):
                continue

            if not field.company_dependent and name in ir_defaults:
                defaults[name] = ir_defaults[name]
                continue

            if field.default:
                defaults[name] = field.default(self)
                continue

            if field.company_dependent and name in ir_defaults:
                defaults[name] = ir_defaults[name]
                continue

            if (
                field.inherited
                and self._has_field_access(field, "write")
                and field.related_field is not None
            ):
                field = field.related_field
                parent_fields[field.model_name].append(field.name)

        for fname, value in defaults.items():
            field = _fields.get(fname)
            if field is not None:
                value = field.convert_to_cache(value, self, validate=False)
                defaults[fname] = field.convert_to_write(value, self)

        for model, names in parent_fields.items():
            defaults.update(env[model].default_get(names))

        return defaults

    @api.model
    def _add_missing_default_values(
        self,
        values: ValuesType,
        _missing_defaults_cache: dict[frozenset[str], list[str]] | None = None,
    ) -> ValuesType:
        vals_keys = frozenset(values)
        if _missing_defaults_cache is not None and vals_keys in _missing_defaults_cache:
            missing_defaults = _missing_defaults_cache[vals_keys]
        else:
            avoid_models = set()

            def collect_models_to_avoid(model):
                for parent_mname, parent_fname in model._inherits.items():
                    if parent_fname in values:
                        avoid_models.add(parent_mname)
                    else:
                        collect_models_to_avoid(self.env[parent_mname])

            collect_models_to_avoid(self)

            def avoid(field):
                if avoid_models:
                    while field.inherited:
                        field = field.related_field
                        if field.model_name in avoid_models:
                            return True
                return False

            missing_defaults = [
                name
                for name, field in self._fields.items()
                if name not in values
                if not avoid(field)
            ]
            if _missing_defaults_cache is not None:
                _missing_defaults_cache[vals_keys] = missing_defaults

        if missing_defaults:
            defaults = self.default_get(missing_defaults)
            _fields = self._fields
            for name, value in defaults.items():
                field_type = _fields[name].type
                if not value:
                    continue
                if field_type == "many2many":
                    if isinstance(value[0], int):
                        defaults[name] = [Command.set(value)]
                elif field_type == "one2many" and isinstance(value[0], dict):
                    defaults[name] = [Command.create(x) for x in value]
            defaults.update(values)

        else:
            defaults = dict(values)

        cls = type(self)
        properties_names = own_class_memo(
            cls,
            "_properties_field_names__",
            lambda: tuple(
                fname for fname, field in self._fields.items() if field.is_properties
            ),
        )
        for name in properties_names:
            defaults[name] = self._fields[name]._add_default_values(self.env, defaults)

        return defaults

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        if not isinstance(vals_list, (list, tuple)):
            raise TypeError(
                f"create() expects a list of dicts, got {type(vals_list).__name__}"
            )
        if not vals_list:
            return self.browse()

        prof = _OrmProfile(_orm_crud)

        if _n1_enabled and (tracker := self.env.transaction._n1_tracker):
            fnames = frozenset(fname for vals in vals_list for fname in vals)
            tracker.record("create", self._name, len(vals_list), fnames)

        self = self.browse()
        self.check_access("create")

        field_names = OrderedSet(fname for vals in vals_list for fname in vals)
        field_names.update(
            field_name
            for context_key in self.env.context
            if context_key.startswith("default_")
            and (field_name := context_key.removeprefix("default_"))
            and field_name in self._fields
        )
        for field_name in field_names:
            field = self._fields.get(field_name)
            if field is None:
                raise ValueError(f"Invalid field {field_name!r} in {self._name!r}")
            self._check_field_access(field, "write")
        prof.mark("acl")

        new_vals_list = self._prepare_create_values(vals_list)

        data_list = []
        determine_inverses = defaultdict(OrderedSet)
        bypass_access_ids: defaultdict[Field, OrderedSet] = defaultdict(OrderedSet)

        for vals in new_vals_list:
            precomputed = vals.pop("__precomputed__", ())

            data = {}
            data["stored"] = stored = {}
            data["inversed"] = inversed = {}
            data["cached_only"] = cached_only = {}
            data["inherited"] = inherited = defaultdict(dict)
            data["protected"] = protected = set()
            for key, val in vals.items():
                field = self._fields.get(key)
                if not field:
                    raise ValueError(f"Invalid field {key!r} on model {self._name!r}")
                if field.store:
                    stored[key] = val
                if field.inherited and field.related_field is not None:
                    inherited[field.related_field.model_name][key] = val
                elif field.inverse and field not in precomputed:
                    inversed[key] = val
                    determine_inverses[field.inverse].add(field)
                elif not field.store and not field.compute:
                    cached_only[key] = val
                if (
                    field.compute and (not field.readonly or field.precompute)
                ) or key in cached_only:
                    protected.update(self.pool.field_computed.get(field, [field]))
                if field.is_many2one and field.bypass_search_access and not self.env.su:
                    # Collected, not checked here. `check_access` on a
                    # one-record recordset has to fetch whatever the comodel's
                    # ir.rule reads, and a recordset of one has nothing to
                    # prefetch with -- so a rule as small as ("name","!=",x)
                    # cost one SELECT per record. Indexing the map with a falsy
                    # co_id on purpose: it creates the entry, so a batch that
                    # only ever sets the field to False still pays the
                    # model-level ACL check it paid before.
                    co_ids = bypass_access_ids[field]
                    if co_id := field.convert_to_cache(val, self):
                        co_ids.add(co_id)

            data_list.append(data)

        for field, co_ids in bypass_access_ids.items():
            self.env[field.comodel_name].browse(co_ids).check_access("read")
        prof.mark("prep")

        for model_name, parent_name in self._inherits.items():
            parent_data_list = []
            for data in data_list:
                if not data["stored"].get(parent_name):
                    parent_data_list.append(data)
                elif data["inherited"][model_name]:
                    parent = self.env[model_name].browse(data["stored"][parent_name])
                    parent.write(data["inherited"][model_name])

            if parent_data_list:
                parents = self.env[model_name].create(
                    [data["inherited"][model_name] for data in parent_data_list]
                )
                for parent, data in zip(parents, parent_data_list, strict=True):
                    data["stored"][parent_name] = parent.id

        prof.mark("parent")

        records = self._create(data_list)
        prof.mark("sql")

        protected_fields = [(data["protected"], data["record"]) for data in data_list]
        with self.env.protecting(protected_fields):
            for data in data_list:
                if vals := data["cached_only"]:
                    data["record"]._update_cache(vals)
            for fields in determine_inverses.values():
                inv_names = {field.name for field in fields}
                inv_rec_ids = []
                for data in data_list:
                    if inv_names.isdisjoint(data["inversed"]):
                        continue
                    record = data["record"]
                    record._update_cache(
                        {
                            fname: value
                            for fname, value in data["inversed"].items()
                            if fname in inv_names and fname not in data["stored"]
                        }
                    )
                    inv_rec_ids.append(record.id)

                inv_records = self.browse(inv_rec_ids)
                next(iter(fields)).determine_inverse(inv_records)
                inv_relational_fnames = [
                    field.name
                    for field in fields
                    if field.is_x2many and not field.store
                ]
                inv_records.invalidate_recordset(fnames=inv_relational_fnames)
        prof.mark("trigger")

        for data in data_list:
            data["record"]._validate_fields(data["inversed"], data["stored"])

        if self._check_company_auto:
            records._check_company()

        prof.stop()
        if prof.debug:
            _orm_crud.debug(
                "[%.3f ms] create %s: %d records, %d fields"
                " | acl=%.1f prep=%.1f parent=%.1f sql=%.1f trigger=%.1f validate=%.1f",
                prof.elapsed * 1000,
                self._name,
                len(records),
                len(field_names),
                prof.ms("start", "acl"),
                prof.ms("acl", "prep"),
                prof.ms("prep", "parent"),
                prof.ms("parent", "sql"),
                prof.ms("sql", "trigger"),
                prof.ms("trigger", "end"),
            )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record_create(self._name, len(records), prof.elapsed)

        self._create_update_xmlids(records, vals_list)
        return records

    def _prepare_create_values(self, vals_list: list[ValuesType]) -> list[ValuesType]:
        bad_names = bad_field_names(self)

        cls = type(self)
        precompute_readonly = own_class_memo(
            cls,
            "_precompute_readonly_names__",
            lambda: frozenset(
                fname
                for fname, field in self._fields.items()
                if field.precompute and field.readonly
            ),
        )
        if precompute_readonly:
            bad_names |= precompute_readonly

        missing_defaults_cache: dict[frozenset[str], list[str]] = {}

        result_vals_list = []
        for vals in vals_list:
            vals = self._add_missing_default_values(vals, missing_defaults_cache)

            for fname in bad_names:
                vals.pop(fname, None)
            if self._log_access:
                vals.setdefault("create_uid", self.env.uid)
                vals.setdefault("create_date", self.env.cr.now())
                vals.setdefault("write_uid", self.env.uid)
                vals.setdefault("write_date", self.env.cr.now())

            result_vals_list.append(vals)

        self._add_precomputed_values(result_vals_list)

        return result_vals_list

    def _add_precomputed_values(self, vals_list: list[ValuesType]) -> None:
        precomputable = {
            fname: field for fname, field in self._fields.items() if field.precompute
        }
        if not precomputable:
            return

        vals_list_todo = [
            vals
            for vals in vals_list
            if any(fname not in vals for fname in precomputable)
        ]
        if not vals_list_todo:
            return

        records = self.browse().concat(*(self.new(vals) for vals in vals_list_todo))

        try:
            for record, vals in zip(records, vals_list_todo, strict=True):
                vals["__precomputed__"] = precomputed = set()
                for fname, field in precomputable.items():
                    if fname not in vals:
                        vals[fname] = field.convert_to_write(record[fname], self)
                        precomputed.add(field)
        finally:
            self._discard_precompute_scratch(records)

    def _discard_precompute_scratch(self, records: Self) -> None:
        ids = records._ids
        if not ids:
            return
        env = self.env
        for field in self._fields.values():
            field._invalidate_cache(env, ids)

    def _build_insert_rows(
        self, stored_list: list, columns: list[str], col_fields: list[Field]
    ) -> list[tuple]:
        return [
            tuple(
                field.convert_to_column_insert(stored[fname], self, stored)
                if fname in stored
                else None
                for fname, field in zip(columns, col_fields, strict=True)
            )
            for stored in stored_list
        ]

    @api.model
    def _create(self, data_list: list[ValuesType]) -> Self:
        if not data_list:
            raise ValueError("_create() called with empty data_list")
        prof = _OrmProfile(_orm_crud)

        ids: list[int] = []
        other_fields: OrderedSet[Field] = OrderedSet()

        for data_sublist in batched(data_list, INSERT_BATCH_SIZE, strict=False):
            stored_list = [data["stored"] for data in data_sublist]
            fnames = sorted({name for stored in stored_list for name in stored})

            columns: list[str] = []
            col_fields: list[Field] = []
            for fname in fnames:
                field = self._fields[fname]
                if field.column_type:
                    columns.append(fname)
                    col_fields.append(field)
                else:
                    other_fields.add(field)

                if field.is_properties:
                    other_fields.add(field)

            ids.extend(
                self.env.backend.create_rows(self, stored_list, columns, col_fields)
            )

        prof.mark("sql")

        records, inverses_update = self._populate_create_cache(ids, data_list)
        prof.mark("cache")

        for (field, value), record_ids in inverses_update.items():
            field._update_inverses(self.browse(record_ids), value)
        prof.mark("inverses")

        records._parent_store_create()

        protected = [(data["protected"], data["record"]) for data in data_list]
        with self.env.protecting(protected):
            records.modified(self._fields, create=True)

            if other_fields:
                others = records.with_context(clean_context(self.env.context))
                for field in sorted(other_fields, key=attrgetter("_sequence")):
                    field.create(
                        [
                            (other, data["stored"][field.name])
                            for other, data in zip(others, data_list, strict=True)
                            if field.name in data["stored"]
                        ]
                    )

                records.modified([field.name for field in other_fields], create=True)

        records._validate_fields(name for data in data_list for name in data["stored"])
        records.check_access("create")

        prof.stop()
        if prof.debug:
            _orm_crud.debug(
                "[%.3f ms] _create %s: %d records"
                " | sql=%.1f cache=%.1f inverses=%.1f trigger=%.1f",
                prof.elapsed * 1000,
                self._name,
                len(records),
                prof.ms("start", "sql"),
                prof.ms("sql", "cache"),
                prof.ms("cache", "inverses"),
                prof.ms("inverses", "end"),
            )
        return records

    def _create_rows_sql(
        self,
        stored_list: list[ValuesType],
        columns: list[str],
        col_fields: list[Field],
    ) -> list[int]:
        cr = self.env.cr
        ids: list[int] = []
        use_copy = (
            not COPY_DISABLED and col_fields and len(stored_list) >= COPY_THRESHOLD
        )
        subprof = _OrmProfile(_orm_crud)

        if use_copy:
            copy_rows = self._build_insert_rows(stored_list, columns, col_fields)
            batch_ids = cr.copy_from(
                self._table,
                columns,
                copy_rows,
                returning_ids=True,
                binary=True,
            )
            ids.extend(batch_ids)
            if subprof.debug:
                subprof.stop()
                _orm_crud.debug(
                    "[%.3f ms] _create %s: %d records via COPY (%d columns)",
                    subprof.elapsed * 1000,
                    self._name,
                    len(stored_list),
                    len(columns),
                )
        else:
            if col_fields:
                rows: list[tuple] = self._build_insert_rows(
                    stored_list, columns, col_fields
                )
            else:
                columns = ["id"]
                rows = [(SQL_DEFAULT,) for _ in stored_list]

            cr.execute(
                SQL(
                    'INSERT INTO %s (%s) VALUES %s RETURNING "id"',
                    SQL.identifier(self._table),
                    SQL(", ").join(map(SQL.identifier, columns)),
                    SQL(", ").join(SQL("(%s)", SQL(", ").join(row)) for row in rows),
                )
            )
            ids.extend(id_ for (id_,) in cr.fetchall())
            if subprof.debug:
                subprof.stop()
                _orm_crud.debug(
                    "[%.3f ms] _create %s: %d records via INSERT (%d columns)",
                    subprof.elapsed * 1000,
                    self._name,
                    len(stored_list),
                    len(columns),
                )
        return ids

    def _populate_create_cache(
        self, ids: list[int], data_list: list[dict]
    ) -> tuple[Self, dict]:
        records = self.browse(ids)
        inverses_update = defaultdict(list)
        common_set_vals = _BAD_NAMES_LOG

        env = self.env
        _stored_x2m_caches = []
        _stored_scalar_caches = []
        for field in self._fields.values():
            if not field.store:
                continue
            if field.is_x2many:
                _stored_x2m_caches.append((field, field._get_cache(env)))
            else:
                default = PENDING if field.is_stored_computed else None
                _stored_scalar_caches.append(
                    (field, field.name, field._get_cache(env), default)
                )

        _fields = self._fields
        _field_inverses = self.pool.field_inverses

        vals_list = []
        set_vals_list = []
        record_ids = []
        for data, record in zip(
            data_list, records.with_context(bin_size=False), strict=True
        ):
            data["record"] = record
            vals = dict(
                {k: v for d in data["inherited"].values() for k, v in d.items()},
                **data["stored"],
            )
            vals_list.append((vals, record))
            set_vals_list.append(common_set_vals.union(vals))
            record_ids.append(record._ids[0])

        supplied = set().union(*set_vals_list) if set_vals_list else set()
        for _field, cache in _stored_x2m_caches:
            cache.update(dict.fromkeys(record_ids, ()))
        for _field, fname, cache, default in _stored_scalar_caches:
            if fname not in supplied:
                cache.update(dict.fromkeys(record_ids, default))
            else:
                cache.update(
                    (rid, default)
                    for rid, set_vals in zip(record_ids, set_vals_list, strict=True)
                    if fname not in set_vals
                )

        for vals, record in vals_list:
            for fname, value in vals.items():
                field = _fields[fname]
                if not (field.is_x2many or field.is_html):
                    cache_value = field.convert_to_cache(value, record)
                    field._update_cache(record, cache_value)
                    if (
                        field.is_many2one or field.is_many2one_reference
                    ) and _field_inverses[field]:
                        inverses_update[(field, cache_value)].append(record.id)

        return records, inverses_update

    @api.model
    def _create_update_xmlids(self, records: Self, vals_list: list[ValuesType]) -> None:
        import_module = self.env.context.get("_import_current_module")
        if not import_module:
            return

        noupdate = self.env.context.get("noupdate", False)
        xids = (v.get("id") for v in vals_list)
        self.env["ir.model.data"]._update_xmlids(
            [
                {
                    "xml_id": (xid if "." in xid else f"{import_module}.{xid}"),
                    "record": rec,
                    "noupdate": noupdate,
                }
                for rec, xid in zip(records, xids, strict=False)
                if xid and isinstance(xid, str)
            ]
        )

    def _parent_store_create(self) -> None:
        if not self._parent_store:
            return
        if not self.env.backend.supports_parent_store:
            return

        updated = self.env.execute_query(
            SQL(
                """ UPDATE %(table)s node
                SET parent_path=concat((
                        SELECT parent.parent_path
                        FROM %(table)s parent
                        WHERE parent.id=node.%(parent)s
                    ), node.id, '/')
                WHERE node.id IN %(ids)s
                RETURNING node.id, node.parent_path """,
                table=SQL.identifier(self._table),
                parent=SQL.identifier(self._parent_name),
                ids=tuple(self.ids),
            )
        )

        self._fields["parent_path"]._update_cache_items(self.env, updated)
