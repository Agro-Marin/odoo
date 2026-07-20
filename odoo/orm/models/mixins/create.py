"""Record creation: ``create``/``default_get`` and their helpers.

Split out of the former CrudMixin; see _crud_common.py for shared
constants. Copy/duplication lives in copy.py (CopyMixin).
"""

import typing
from collections import defaultdict
from itertools import batched
from operator import attrgetter
from typing import Self

from odoo.tools import SQL, OrderedSet, clean_context
from odoo.tools.misc import PENDING
from odoo.tools.nplusone import _n1_enabled
from odoo.tools.orm_profiler import _OrmProfile

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
    """Record creation: ``create``/``default_get`` and their helpers."""

    __slots__ = ()

    @api.model
    def default_get(self, fields: list[str]) -> ValuesType:
        """Return default values for the named ``fields``, determined by the
        context, user defaults, user fallbacks and the model itself.

        :param fields: names of fields whose default is requested
        :return: dict mapping field names to their default value, when they have
            one. Fields not in ``fields`` are not considered.
        """
        defaults = {}
        parent_fields = defaultdict(list)
        ir_defaults = self.env["ir.default"]._get_model_defaults(self._name)

        # Extract the context "default_<name>" overrides once, rather than
        # building "default_" + name (and a context lookup) for every requested
        # field: default_get runs per-record on the create hot path and models
        # have dozens of fields, so the per-field string allocation dominated.
        context_defaults = {
            key[8:]: value
            for key, value in self.env.context.items()
            if key.startswith("default_")
        }

        for name in fields:
            # 1. look up context
            if name in context_defaults:
                defaults[name] = context_defaults[name]
                continue

            field = self._fields.get(name)
            if not field:
                continue

            # 2. look up default for non-company_dependent fields
            if not field.company_dependent and name in ir_defaults:
                defaults[name] = ir_defaults[name]
                continue

            # 3. look up field.default
            if field.default:
                defaults[name] = field.default(self)
                continue

            # 4. look up fallback for company_dependent fields
            if field.company_dependent and name in ir_defaults:
                defaults[name] = ir_defaults[name]
                continue

            # 5. delegate to parent model
            if field.inherited and self._has_field_access(field, 'write'):
                field = field.related_field
                parent_fields[field.model_name].append(field.name)

        # Convert via the cache (not _convert_to_write) for x2many: the latter
        # yields [(LINK, 2), (LINK, 3)] which the web client rejects as a
        # default; the cache round-trip normalizes to [(SET, 0, [2, 3])].
        for fname, value in defaults.items():
            if fname in self._fields:
                field = self._fields[fname]
                value = field.convert_to_cache(value, self, validate=False)
                defaults[fname] = field.convert_to_write(value, self)

        # add default values for inherited fields
        for model, names in parent_fields.items():
            defaults.update(self.env[model].default_get(names))

        return defaults

    @api.model
    def _add_missing_default_values(
        self,
        values: ValuesType,
        _missing_defaults_cache: dict[frozenset[str], list[str]] | None = None,
    ) -> ValuesType:
        # _missing_defaults_cache memoizes the missing-fields computation per
        # unique set of provided keys, so a batch create with uniform keys does
        # not iterate all model fields per record.
        vals_keys = frozenset(values)
        if _missing_defaults_cache is not None and vals_keys in _missing_defaults_cache:
            missing_defaults = _missing_defaults_cache[vals_keys]
        else:
            # avoid overriding inherited values when parent is set
            avoid_models = set()

            def collect_models_to_avoid(model):
                for parent_mname, parent_fname in model._inherits.items():
                    if parent_fname in values:
                        avoid_models.add(parent_mname)
                    else:
                        # manage the case where an ancestor parent field is set
                        collect_models_to_avoid(self.env[parent_mname])

            collect_models_to_avoid(self)

            def avoid(field):
                # check whether the field is inherited from one of avoid_models
                if avoid_models:
                    while field.inherited:
                        field = field.related_field
                        if field.model_name in avoid_models:
                            return True
                return False

            # compute missing fields
            missing_defaults = [
                name
                for name, field in self._fields.items()
                if name not in values
                if not avoid(field)
            ]
            if _missing_defaults_cache is not None:
                _missing_defaults_cache[vals_keys] = missing_defaults

        if missing_defaults:
            # provided values override defaults, never the other way around
            defaults = self.default_get(missing_defaults)
            for name, value in defaults.items():
                if (
                    self._fields[name].type == "many2many"
                    and value
                    and isinstance(value[0], int)
                ):
                    # convert a list of ids into a list of commands
                    defaults[name] = [Command.set(value)]
                elif (
                    self._fields[name].type == "one2many"
                    and value
                    and isinstance(value[0], dict)
                ):
                    # convert a list of dicts into a list of commands
                    defaults[name] = [Command.create(x) for x in value]
            defaults.update(values)

        else:
            # Copy: the properties loop below and the caller mutate the result
            # in place; aliasing ``values`` would leak that back into the
            # caller's vals_list. (The branch above already builds a fresh dict.)
            defaults = dict(values)

        # delegate the default properties to the properties field(s).  Memoize
        # the (usually empty) set of properties-field names per class instead of
        # rescanning every field on every record of a create batch.
        cls = type(self)
        properties_names = own_class_memo(
            cls,
            "_properties_field_names__",
            lambda: tuple(
                fname
                for fname, field in self._fields.items()
                if field.type == "properties"
            ),
        )
        for name in properties_names:
            defaults[name] = self._fields[name]._add_default_values(self.env, defaults)

        return defaults

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Create new records for the model.

        The new records are initialized using the values from the list of dicts
        ``vals_list``, and if necessary those from :meth:`~.default_get`.

        :param vals_list:
            values for the model's fields, as a list of dictionaries::

                [{'field_name': field_value, ...}, ...]

            For backward compatibility, ``vals_list`` may be a dictionary.
            It is treated as a singleton list ``[vals]``, and a single record
            is returned.

            see :meth:`~.write` for details

        :return: the created records
        :raise AccessError: if the user may not create records of this model
        :raise ValidationError: on an invalid value for a selection field
        :raise ValueError: if a field name in the create values does not exist
        :raise UserError: if the operation would create a loop in an object
          hierarchy (e.g. setting an object as its own parent)
        """
        # raise (not assert): the contract must hold under python -O, else a
        # non-list crashes much later in field classification with an opaque
        # error.
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

        # Model-level ACL: check that the user can create this model at all.
        # Called on an empty recordset so only ir.model.access is checked,
        # not ir.rules (which need actual record ids).
        self = self.browse()
        self.check_access("create")

        # check access to all user-provided fields
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

        # classify fields for each record
        data_list = []
        determine_inverses = defaultdict(OrderedSet)  # {inverse: fields}

        for vals in new_vals_list:
            precomputed = vals.pop("__precomputed__", ())

            # distribute fields into sets for various purposes
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
                if field.inherited:
                    inherited[field.related_field.model_name][key] = val
                elif field.inverse and field not in precomputed:
                    inversed[key] = val
                    determine_inverses[field.inverse].add(field)
                elif not field.store and not field.compute:
                    # cache-only fields with field.inverse are handled by inversed
                    cached_only[key] = val
                # protect editable computed fields and precomputed fields
                # against (re)computation
                if (field.compute and (not field.readonly or field.precompute)) or key in cached_only:
                    protected.update(self.pool.field_computed.get(field, [field]))
                if (
                    field.type == "many2one"
                    and field.bypass_search_access
                    and not self.env.su
                ):
                    co_id = field.convert_to_cache(val, self)
                    self.env[field.comodel_name].browse(co_id).check_access("read")

            data_list.append(data)
        prof.mark("prep")

        # create or update parent records
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

        # create records with stored fields
        records = self._create(data_list)
        prof.mark("sql")

        # Two-pass validation: pass 1 (in _create) validates stored fields;
        # pass 2 (below) validates inversed fields, excluding those also touching
        # stored (covered by pass 1). Inverses run BETWEEN the two passes (after
        # pass 1 inside _create, before pass 2) since they write to related
        # models that pass 2's constraints may need to exist. (write() validates
        # non-inversed first — its dirty values are already in cache.)

        # protect fields being written against recomputation
        protected_fields = [(data["protected"], data["record"]) for data in data_list]
        with self.env.protecting(protected_fields):
            # fill cache-only fields (non-stored, non-computed)
            for data in data_list:
                if vals := data["cached_only"]:
                    data["record"]._update_cache(vals)
            # call inverse method for each group of fields
            for fields in determine_inverses.values():
                # determine which records to inverse for those fields
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
                # non-stored fields were cached before the inverse ran, so for
                # x2many create commands the cache may hold NewId records;
                # invalidate them now.
                inv_relational_fnames = [
                    field.name
                    for field in fields
                    if field.type in ("one2many", "many2many") and not field.store
                ]
                inv_records.invalidate_recordset(fnames=inv_relational_fnames)
        prof.mark("trigger")

        # Pass 2: validate constraints touching inversed fields, excluding
        # those that also touch stored fields (already validated in pass 1).
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
        """Clean up and complete create values: add defaults and precomputed
        fields, strip forbidden (magic) fields. Return the new vals list.
        """
        bad_names = bad_field_names(self)

        # Also strip precomputed readonly fields to force their computation.
        # Cache the set on the class to avoid iterating all fields per call.
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
            bad_names = bad_names | precompute_readonly

        # Memoize missing_defaults per unique key set: batch creates usually
        # share keys, so this avoids iterating all fields N times.
        missing_defaults_cache: dict[frozenset[str], list[str]] = {}

        result_vals_list = []
        for vals in vals_list:
            vals = self._add_missing_default_values(vals, missing_defaults_cache)

            # strip bad_names, then set magic log-access fields
            for fname in bad_names:
                vals.pop(fname, None)
            if self._log_access:
                vals.setdefault("create_uid", self.env.uid)
                vals.setdefault("create_date", self.env.cr.now())
                vals.setdefault("write_uid", self.env.uid)
                vals.setdefault("write_date", self.env.cr.now())

            result_vals_list.append(vals)

        # add precomputed fields
        self._add_precomputed_values(result_vals_list)

        return result_vals_list

    def _add_precomputed_values(self, vals_list: list[ValuesType]) -> None:
        """Add missing ``precompute=True`` fields to ``vals_list``."""
        precomputable = {
            fname: field for fname, field in self._fields.items() if field.precompute
        }
        if not precomputable:
            return

        # determine which vals must be completed
        vals_list_todo = [
            vals
            for vals in vals_list
            if any(fname not in vals for fname in precomputable)
        ]
        if not vals_list_todo:
            return

        # create new records for the vals that must be completed
        records = self.browse().concat(*(self.new(vals) for vals in vals_list_todo))

        for record, vals in zip(records, vals_list_todo, strict=True):
            vals["__precomputed__"] = precomputed = set()
            for fname, field in precomputable.items():
                if fname not in vals:
                    # compute stored-column fields before create so required
                    # and constraints can apply to them
                    vals[fname] = field.convert_to_write(record[fname], self)
                    precomputed.add(field)

    def _build_insert_rows(
        self, stored_list: list, columns: list[str], col_fields: list[Field]
    ) -> list[tuple]:
        """Build one column-converted value tuple per record, for INSERT / COPY.

        Applies the rule shared by both branches of :meth:`_create`:
        ``convert_to_column_insert`` for a present column, ``None`` for a missing
        one (a gap means a NULL-defaulting non-required column, since Python
        defaults already filled required ones). ``columns`` and ``col_fields``
        are parallel.
        """
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
        """Create records from the stored field values in ``data_list``."""
        # raise (not assert): contract must hold under python -O — an empty
        # data_list would produce no records, confusing callers.
        if not data_list:
            raise ValueError("_create() called with empty data_list")
        cr = self.env.cr
        prof = _OrmProfile(_orm_crud)

        # insert rows in batches of maximum INSERT_BATCH_SIZE
        ids: list[int] = []  # ids of created records
        other_fields: OrderedSet[Field] = OrderedSet()  # non-column fields

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

                if field.type == "properties":
                    # force field.create() for properties: it may update the
                    # parent definition
                    other_fields.add(field)

            # Backend dispatch: in-memory backend or PostgreSQL (None = SQL).
            if (backend := self.env.backend) is not None:
                ids.extend(
                    backend.create_rows(self, stored_list, columns, col_fields)
                )
                continue

            use_copy = (
                not COPY_DISABLED and col_fields and len(stored_list) >= COPY_THRESHOLD
            )
            subprof = _OrmProfile(_orm_crud)

            if use_copy:
                # COPY path: 2-5x faster than INSERT for large batches. Missing
                # columns use None, not SQL_DEFAULT: _prepare_create_values
                # already applied Python defaults, so remaining gaps are
                # non-required fields whose DB default is NULL.
                copy_rows = self._build_insert_rows(stored_list, columns, col_fields)
                # Use binary COPY only when no column is numeric: psycopg's
                # binary numeric dumper needs Decimal, so a float->Decimal
                # conversion makes binary ~2x slower than text for Monetary /
                # Float-with-digits columns. Text COPY is byte-identical, so this
                # trades speed only, never correctness. jsonb numerics (company-
                # dependent / translated) pay no Decimal tax and stay binary.
                use_binary = not any(
                    field.column_type[0] == "numeric" for field in col_fields
                )
                batch_ids = cr.copy_from(
                    self._table,
                    columns,
                    copy_rows,
                    returning_ids=True,
                    binary=use_binary,
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
                # INSERT path: small batches and the empty-record edge case.
                # Missing columns use None, not SQL_DEFAULT (same rationale as
                # COPY): uniform rows with no DEFAULT keyword let the whole VALUES
                # clause use standard parameter binding.
                if col_fields:
                    rows: list[tuple] = self._build_insert_rows(
                        stored_list, columns, col_fields
                    )
                else:
                    # Empty-record edge case (e.g. create({})): synthesize an
                    # ``id`` column bound to DEFAULT so PostgreSQL pulls the
                    # next sequence value.
                    columns = ["id"]
                    rows = [(SQL_DEFAULT,) for _ in stored_list]

                cr.execute(
                    SQL(
                        'INSERT INTO %s (%s) VALUES %s RETURNING "id"',
                        SQL.identifier(self._table),
                        SQL(", ").join(map(SQL.identifier, columns)),
                        SQL(", ").join(
                            SQL("(%s)", SQL(", ").join(row)) for row in rows
                        ),
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

        prof.mark("sql")

        # put the new records in cache, and update inverse fields, for many2one
        records, inverses_update = self._populate_create_cache(ids, data_list)
        prof.mark("cache")

        for (field, value), record_ids in inverses_update.items():
            field._update_inverses(self.browse(record_ids), value)
        prof.mark("inverses")

        # update parent_path
        records._parent_store_create()

        # protect fields being written against recomputation
        protected = [(data["protected"], data["record"]) for data in data_list]
        with self.env.protecting(protected):
            # mark computed fields as todo
            records.modified(self._fields, create=True)

            if other_fields:
                # discard default values from context for other fields
                others = records.with_context(clean_context(self.env.context))
                for field in sorted(other_fields, key=attrgetter("_sequence")):
                    field.create(
                        [
                            (other, data["stored"][field.name])
                            for other, data in zip(others, data_list, strict=True)
                            if field.name in data["stored"]
                        ]
                    )

                # mark fields to recompute
                records.modified([field.name for field in other_fields], create=True)

        # Pass 1: validate constraints touching stored fields.
        records._validate_fields(name for data in data_list for name in data["stored"])
        # Record-level rules against the actual created records (e.g. multi-
        # company). Not a duplicate of the earlier model-level check, which ran
        # on an empty recordset.
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

    def _populate_create_cache(
        self, ids: list[int], data_list: list[dict]
    ) -> tuple[Self, dict]:
        """Populate the ORM cache for newly created records.

        Fills cache slots for all stored fields and collects M2O inverse updates.

        :param ids: list of newly created record IDs
        :param data_list: list of data dicts with 'stored' and 'inherited' keys
        :return: (records, inverses_update) — the browse recordset and a dict
            of {(field, cache_value): [record_ids]} for M2O inverse updates.
            Also mutates data_list entries to add 'record' key.
        """
        # using bin_size=False to put binary values in the right place
        records = self.browse(ids)
        inverses_update = defaultdict(list)  # {(field, value): ids}
        common_set_vals = _BAD_NAMES_LOG  # {id, parent_path} | LOG_ACCESS_COLUMNS

        # Pre-classify stored fields once (avoids re-checking per record).
        # Also pre-get field caches to avoid repeated _get_cache() calls.
        env = self.env
        _stored_x2m_caches = []  # x2many: [(field, cache)]
        _stored_scalar_caches = []  # scalar: [(field, field_name, cache, default)]
        for field in self._fields.values():
            if not field.store:
                continue
            if field.type in ("one2many", "many2many"):
                _stored_x2m_caches.append((field, field._get_cache(env)))
            else:
                # Stored computed fields get PENDING (not None) so cache reads
                # can distinguish "not yet computed" from "genuinely null".
                default = PENDING if field.is_stored_computed else None
                _stored_scalar_caches.append(
                    (field, field.name, field._get_cache(env), default)
                )

        _fields = self._fields
        _field_inverses = self.pool.field_inverses
        _x2m_html_types = frozenset(("one2many", "many2many", "html"))
        _m2o_types = frozenset(("many2one", "many2one_reference"))
        for data, record in zip(
            data_list, records.with_context(bin_size=False), strict=True
        ):
            data["record"] = record
            # DLE P104: test_inherit.py, test_50_search_one2many
            vals = dict(
                {k: v for d in data["inherited"].values() for k, v in d.items()},
                **data["stored"],
            )
            set_vals = common_set_vals.union(vals)

            record_id = record._ids[0]
            # put None/() in cache for all fields not part of the INSERT
            # Direct cache assignment avoids _update_cache() method overhead
            # (safe: new records have no dirty flags to check)
            for _field, cache in _stored_x2m_caches:
                cache[record_id] = ()
            for _field, fname, cache, default in _stored_scalar_caches:
                if fname not in set_vals:
                    cache[record_id] = default

            for fname, value in vals.items():
                field = _fields[fname]
                if field.type not in _x2m_html_types:
                    cache_value = field.convert_to_cache(value, record)
                    field._update_cache(record, cache_value)
                    if field.type in _m2o_types and _field_inverses[field]:
                        inverses_update[(field, cache_value)].append(record.id)

        return records, inverses_update

    @api.model
    def _create_update_xmlids(self, records: Self, vals_list: list[ValuesType]) -> None:
        """Update ir.model.data xmlids when creating records during import.

        Called at the end of create() to support setting xids directly by
        providing an "id" key during an import.
        """
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
                    # note: this is not used when updating o2ms above...
                    "noupdate": noupdate,
                }
                for rec, xid in zip(records, xids, strict=False)
                if xid and isinstance(xid, str)
            ]
        )

    def _parent_store_create(self) -> None:
        """Set the parent_path field on ``self`` after its creation."""
        if not self._parent_store:
            return
        # Backends without hierarchy support skip parent_path maintenance.
        backend = self.env.backend
        if backend is not None and not backend.supports_parent_store:
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

        # update the cache of updated nodes, and determine what to recompute
        field = self._fields["parent_path"]
        for id_, path in updated:
            field._update_cache(self.browse(id_), path)
