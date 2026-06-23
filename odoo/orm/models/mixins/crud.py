"""CRUD operations mixin for BaseModel: create, write, unlink and supporting
private methods. Copy/duplication lives in copy.py (CopyMixin).
"""

import logging
import os
import time
import typing
from collections import defaultdict
from itertools import batched
from operator import attrgetter
from typing import Self

from odoo.exceptions import AccessError, UserError
from odoo.libs.json import dumps as json_dumps
from odoo.libs.json import loads as json_loads
from odoo.tools import SQL, OrderedSet, clean_context
from odoo.tools.misc import PENDING
from odoo.tools.nplusone import _n1_enabled
from odoo.tools.orm_profiler import _orm_profiling_enabled
from odoo.tools.translate import _

from ... import decorators as api
from ..._typing import ValuesType
from ...primitives import (
    INSERT_BATCH_SIZE,
    LOG_ACCESS_COLUMNS,
    SQL_DEFAULT,
    SUPERUSER_ID,
    UPDATE_BATCH_SIZE,
    Command,
)

# Min batch size to use COPY instead of INSERT. COPY avoids SQL parsing
# overhead but adds +1 query (nextval) for ID pre-generation; below this,
# multi-row INSERT RETURNING is a single query. Break-even ~5 rows on PG18;
# 10 is conservative.
COPY_THRESHOLD = int(os.environ.get("ODOO_COPY_THRESHOLD", "10"))
COPY_DISABLED = os.environ.get("ODOO_DISABLE_COPY", "").lower() in (
    "1",
    "true",
    "yes",
)

# Names stripped from create()/write() vals, precomputed to avoid rebuilding
# per call. _BAD_NAMES_LOG adds the log-access columns for _log_access models;
# create() re-adds those via setdefault. Derived from LOG_ACCESS_COLUMNS.
_BAD_NAMES = frozenset({"id", "parent_path"})
_BAD_NAMES_LOG = _BAD_NAMES | frozenset(LOG_ACCESS_COLUMNS)

if typing.TYPE_CHECKING:
    from ...fields.base import Field


_logger = logging.getLogger("odoo.models")
_unlink = logging.getLogger("odoo.models.unlink")
_orm_crud = logging.getLogger("odoo.orm.crud")


class CrudMixin:
    """CRUD operations: create, write, unlink (plus default_get) and their
    SQL-supporting private methods. Copy/duplication is in CopyMixin (copy.py).

    Key asymmetries between the three mutators, by design:

    - **SQL timing**: write() is deferred (batched until flush); create() and
      unlink() are immediate. Raw SQL after write() sees OLD values until flush.
    - **modified() scope**: write() captures only RELATIONAL fields via
      _modified_before() (scalars don't change the dependency graph); unlink()
      captures ALL fields because deletion breaks every dependency path.
    - **Validation**: both are two-pass — create() validates stored→inversed,
      write() validates (vals-inversed)→inversed.
    - **ACL timing**: create() checks record-level rules LATE (records must
      exist); write()/unlink() check them EARLY.
    """

    __slots__ = ()

    # Default values

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

        for name in fields:
            # 1. look up context
            key = "default_" + name
            if key in self.env.context:
                defaults[name] = self.env.context[key]
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
            if field.inherited:
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

        # delegate the default properties to the properties field
        for field in self._fields.values():
            if field.type == "properties":
                defaults[field.name] = field._add_default_values(self.env, defaults)

        return defaults

    # Create

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

        _debug = _orm_crud.isEnabledFor(logging.DEBUG)
        _agg = _orm_profiling_enabled
        if _debug or _agg:
            _t0 = time.perf_counter()

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
        if _debug:
            _t_acl = time.perf_counter()

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

            data_list.append(data)
        if _debug:
            _t_prep = time.perf_counter()

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

        if _debug:
            _t_parent = time.perf_counter()

        # create records with stored fields
        records = self._create(data_list)
        if _debug:
            _t_sql = time.perf_counter()

        # Two-pass validation: pass 1 (in _create) validates stored fields;
        # pass 2 (below) validates inversed fields, excluding those also touching
        # stored (covered by pass 1). Inverses run BEFORE both passes since they
        # write to related models that constraints may need to exist. (write()
        # validates non-inversed first — its dirty values are already in cache.)

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
        if _debug:
            _t_trigger = time.perf_counter()

        # Pass 2: validate constraints touching inversed fields, excluding
        # those that also touch stored fields (already validated in pass 1).
        for data in data_list:
            data["record"]._validate_fields(data["inversed"], data["stored"])

        if self._check_company_auto:
            records._check_company()

        if _debug or _agg:
            _t_end = time.perf_counter()
        if _debug:
            _orm_crud.debug(
                "[%.3f ms] create %s: %d records, %d fields"
                " | acl=%.1f prep=%.1f parent=%.1f sql=%.1f trigger=%.1f validate=%.1f",
                (_t_end - _t0) * 1000,
                self._name,
                len(records),
                len(field_names),
                (_t_acl - _t0) * 1000,
                (_t_prep - _t_acl) * 1000,
                (_t_parent - _t_prep) * 1000,
                (_t_sql - _t_parent) * 1000,
                (_t_trigger - _t_sql) * 1000,
                (_t_end - _t_trigger) * 1000,
            )
        if _agg and (p := self.env.transaction._orm_profiler):
            p.record_create(self._name, len(records), _t_end - _t0)

        self._create_update_xmlids(records, vals_list)
        return records

    def _prepare_create_values(self, vals_list: list[ValuesType]) -> list[ValuesType]:
        """Clean up and complete create values: add defaults and precomputed
        fields, strip forbidden (magic) fields. Return the new vals list.
        """
        if self._log_access:
            # the superuser can set log_access fields while loading registry
            if not (self.env.uid == SUPERUSER_ID and not self.pool.ready):
                bad_names = _BAD_NAMES_LOG
            else:
                bad_names = _BAD_NAMES
        else:
            bad_names = _BAD_NAMES

        # Also strip precomputed readonly fields to force their computation.
        # Cache the set on the class to avoid iterating all fields per call.
        precompute_readonly = getattr(type(self), "_precompute_readonly_names", None)
        if precompute_readonly is None:
            precompute_readonly = frozenset(
                fname
                for fname, field in self._fields.items()
                if field.precompute and field.readonly
            )
            type(self)._precompute_readonly_names = precompute_readonly
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
        """Add missing precomputed fields to ``vals_list`` values.
        Only applies for precompute=True fields.
        """
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

    @api.model
    def _create(self, data_list: list[ValuesType]) -> Self:
        """Create records from the stored field values in ``data_list``."""
        # raise (not assert): contract must hold under python -O — an empty
        # data_list would produce no records, confusing callers.
        if not data_list:
            raise ValueError("_create() called with empty data_list")
        cr = self.env.cr
        _debug = _orm_crud.isEnabledFor(logging.DEBUG)
        if _debug:
            _tc0 = time.perf_counter()

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

            # Backend dispatch: in-memory storage vs PostgreSQL
            storage = self.env.transaction.storage
            if storage is not None:
                # In-memory path: convert values as the SQL paths do, but store
                # via the backend row API instead of issuing SQL.
                row_dicts: list[dict[str, typing.Any]] = []
                for stored in stored_list:
                    new_id = storage.next_id(self._table)
                    row_dict: dict[str, typing.Any] = {"id": new_id}
                    for fname, field in zip(columns, col_fields, strict=True):
                        if fname in stored:
                            row_dict[fname] = field.convert_to_column_insert(
                                stored[fname], self, stored
                            )
                        # Missing columns default to None (same as SQL NULL)
                    row_dicts.append(row_dict)
                    ids.append(new_id)
                storage.put_rows(self._table, row_dicts)
                continue

            use_copy = (
                not COPY_DISABLED and col_fields and len(stored_list) >= COPY_THRESHOLD
            )
            _debug = _orm_crud.isEnabledFor(logging.DEBUG)
            if _debug:
                _t0 = time.perf_counter()

            if use_copy:
                # COPY path: 2-5x faster than INSERT for large batches. Missing
                # columns use None, not SQL_DEFAULT: _prepare_create_values
                # already applied Python defaults, so remaining gaps are
                # non-required fields whose DB default is NULL.
                copy_rows = []
                for stored in stored_list:
                    row = tuple(
                        (
                            field.convert_to_column_insert(stored[fname], self, stored)
                            if fname in stored
                            else None
                        )
                        for fname, field in zip(columns, col_fields, strict=True)
                    )
                    copy_rows.append(row)
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
                if _debug:
                    _orm_crud.debug(
                        "[%.3f ms] _create %s: %d records via COPY (%d columns)",
                        (time.perf_counter() - _t0) * 1000,
                        self._name,
                        len(stored_list),
                        len(columns),
                    )
            else:
                # INSERT path: small batches and the empty-record edge case.
                # Missing columns use None, not SQL_DEFAULT (same rationale as
                # COPY): uniform rows with no DEFAULT keyword let the whole VALUES
                # clause use standard parameter binding.
                rows: list[list[typing.Any]] = [[] for _ in stored_list]
                if col_fields:
                    for fname, field in zip(columns, col_fields, strict=True):
                        for stored, row in zip(stored_list, rows, strict=True):
                            if fname in stored:
                                row.append(
                                    field.convert_to_column_insert(
                                        stored[fname], self, stored
                                    )
                                )
                            else:
                                row.append(None)
                else:
                    # Empty-record edge case (e.g. create({})): synthesize an
                    # ``id`` column bound to DEFAULT so PostgreSQL pulls the
                    # next sequence value.
                    columns = ["id"]
                    for row in rows:
                        row.append(SQL_DEFAULT)

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
                if _debug:
                    _orm_crud.debug(
                        "[%.3f ms] _create %s: %d records via INSERT (%d columns)",
                        (time.perf_counter() - _t0) * 1000,
                        self._name,
                        len(stored_list),
                        len(columns),
                    )

        if _debug:
            _tc_sql = time.perf_counter()

        # put the new records in cache, and update inverse fields, for many2one
        records, inverses_update = self._populate_create_cache(ids, data_list)
        if _debug:
            _tc_cache = time.perf_counter()

        for (field, value), record_ids in inverses_update.items():
            field._update_inverses(self.browse(record_ids), value)
        if _debug:
            _tc_inverses = time.perf_counter()

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

        if _debug:
            _tc_end = time.perf_counter()
            _orm_crud.debug(
                "[%.3f ms] _create %s: %d records"
                " | sql=%.1f cache=%.1f inverses=%.1f trigger=%.1f",
                (_tc_end - _tc0) * 1000,
                self._name,
                len(records),
                (_tc_sql - _tc0) * 1000,
                (_tc_cache - _tc_sql) * 1000,
                (_tc_inverses - _tc_cache) * 1000,
                (_tc_end - _tc_inverses) * 1000,
            )
        return records

    def _populate_create_cache(
        self, ids: list[int], data_list: list[dict]
    ) -> tuple[Self, dict]:
        """Populate the ORM cache for newly created records.

        Fills cache slots for all stored fields, converts values to cache
        format, and collects many2one inverse updates.

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

    def write(self, vals: ValuesType) -> typing.Literal[True]:
        """Update all records in ``self`` with the provided values.

        :param vals: fields to update and the value to set on them
        :raise AccessError: if the user may not modify these records/fields
        :raise ValidationError: on an invalid value for a selection field
        :raise UserError: if the operation would create a loop in an object
            hierarchy (e.g. setting an object as its own parent)

        * For numeric fields (:class:`~odoo.fields.Integer`,
          :class:`~odoo.fields.Float`) the value should be of the
          corresponding type
        * For :class:`~odoo.fields.Boolean`, the value should be a
          :class:`python:bool`
        * For :class:`~odoo.fields.Selection`, the value should match the
          selection values (generally :class:`python:str`, sometimes
          :class:`python:int`)
        * For :class:`~odoo.fields.Many2one`, the value should be the
          database identifier of the record to set
        * The expected value of a :class:`~odoo.fields.One2many` or
          :class:`~odoo.fields.Many2many` relational field is a list of
          :class:`~odoo.fields.Command` that manipulate the relation the
          implement. There are a total of 7 commands:
          :meth:`~odoo.fields.Command.create`,
          :meth:`~odoo.fields.Command.update`,
          :meth:`~odoo.fields.Command.delete`,
          :meth:`~odoo.fields.Command.unlink`,
          :meth:`~odoo.fields.Command.link`,
          :meth:`~odoo.fields.Command.clear`, and
          :meth:`~odoo.fields.Command.set`.
        * For :class:`~odoo.fields.Date` and `~odoo.fields.Datetime`,
          the value should be either a date(time), or a string.

          .. warning::

            If a string is provided for Date(time) fields,
            it must be UTC-only and formatted according to
            :const:`odoo.tools.misc.DEFAULT_SERVER_DATE_FORMAT` and
            :const:`odoo.tools.misc.DEFAULT_SERVER_DATETIME_FORMAT`

        * Other non-relational fields use a string for value

        .. note:: **Deferred SQL.** Unlike :meth:`create`/:meth:`unlink`,
            ``write()`` only updates the cache and marks fields dirty; the
            ``UPDATE`` is deferred to :meth:`flush_all` (or an implicit flush
            from ``search``/``read``/commit), batching writes into one
            ``UPDATE FROM VALUES``. So a raw SQL ``SELECT`` right after
            ``write()`` may see OLD values — read via the ORM, or
            ``flush_model()`` first.
        """
        if not self:
            return True

        _debug = _orm_crud.isEnabledFor(logging.DEBUG)
        _agg = _orm_profiling_enabled
        if _debug or _agg:
            _t0 = time.perf_counter()

        if _n1_enabled and (tracker := self.env.transaction._n1_tracker):
            tracker.record("write", self._name, len(self), frozenset(vals))

        self.check_access("write")
        for field_name in vals:
            try:
                self._check_field_access(self._fields[field_name], "write")
            except KeyError as e:
                raise ValueError(
                    f"Invalid field {field_name!r} in {self._name!r}"
                ) from e
        if _debug:
            _t_acl = time.perf_counter()
        env = self.env

        # Fields to strip from vals. The superuser may set log_access fields
        # while loading the registry.
        if self._log_access and not (env.uid == SUPERUSER_ID and not self.pool.ready):
            bad_names = _BAD_NAMES_LOG
        else:
            bad_names = _BAD_NAMES

        # set magic fields
        vals = {key: val for key, val in vals.items() if key not in bad_names}
        if self._log_access:
            vals.setdefault("write_uid", self.env.uid)
            vals.setdefault("write_date", self.env.cr.now())

        field_values = []  # [(field, value)]
        determine_inverses = defaultdict(list)  # {inverse: fields}
        fnames_modifying_relations = []
        protected = set()
        x2m_inverse_fnames = []
        for fname, value in vals.items():
            field = self._fields.get(fname)
            if not field:
                raise ValueError(f"Invalid field {fname!r} on model {self._name!r}")
            field_values.append((field, value))
            if field.inverse:
                if field.type in ("one2many", "many2many"):
                    x2m_inverse_fnames.append(fname)
                determine_inverses[field.inverse].append(field)
            if self.pool.is_modifying_relations(field):
                fnames_modifying_relations.append(fname)
            if field.inverse or (field.compute and not field.readonly):
                if field.store or field.type not in ("one2many", "many2many"):
                    # Protect the field from recomputation while it is being
                    # inversed. For non-stored x2many fields, the value may hold
                    # new records (from command 0) needed for inversing but that
                    # should not survive a later recompute; not protecting the
                    # field invalidates it from cache, forcing recomputation once
                    # dependencies are up-to-date.
                    protected.update(self.pool.field_computed.get(field, [field]))

        # Pre-read all x2many inverse fields in one batch. They use command-
        # based writes (add/remove/update), so their current value must be in
        # cache before the field is protected from recomputation. fetch() (vs
        # self[fname] per field) populates all records at once without
        # triggering ensure_one().
        if x2m_inverse_fnames:
            self.fetch(x2m_inverse_fnames)

        # force the computation of fields that are computed with some assigned
        # fields, but are not assigned themselves
        if protected:
            to_compute = [
                field.name
                for field in protected
                if field.compute and field.name not in vals
            ]
            if to_compute:
                self._recompute_recordset(to_compute)
        if _debug:
            _t_classify = time.perf_counter()

        # protect fields being written against recomputation
        with env.protecting(protected, self):
            # Modifying a relational field changes the "data path" between a
            # computed field and its dependency, so dependents must be recomputed
            # for both the OLD and NEW values (hence two modified() calls; only
            # needed for relational fields). E.g. moving a line from SO1 to SO2
            # (line.order_id = so2) must recompute the total amount on both
            # orders.
            if fnames_modifying_relations:
                self._modified_before(fnames_modifying_relations)
            if _debug:
                _t_before = time.perf_counter()

            # Fast path: singleton with a real ID — skip filtered("id") overhead
            _ids = self._ids
            if len(_ids) == 1 and _ids[0]:
                real_recs = self
            else:
                real_recs = self.filtered("id")

            # Process fields in write_sequence order (see Field.write_sequence):
            # 0=scalars/M2O → 10=monetary/properties → 20=x2many
            if len(field_values) > 1:
                field_values.sort(key=lambda item: item[0].write_sequence)
            for field, value in field_values:
                field.mark_dirty(self, value)
            if _debug:
                _t_dirty = time.perf_counter()

            # Call modified() after mark_dirty: it may trigger a search ->
            # flush -> recompute that would compute a field before its
            # dependencies are written. E.g. writing res.partner.name recomputes
            # display_name, which searches child_ids and flushes display_name
            # (it is in _order) before parent_id is written, computing too early.
            # (`test_01_website_reset_password_tour`)
            self.modified(vals)
            if _debug:
                _t_after = time.perf_counter()

            if self._parent_store and self._parent_name in vals:
                self.flush_model([self._parent_name])

            # Two-pass validation: pass 1 validates written fields excluding
            # inversed (their values are already in the dirty cache); inverses
            # run between the passes (they write to related models); pass 2
            # validates inversed fields. (create() runs inverses before both
            # passes since constraints may need the related records to exist.)
            inverse_fields = [f.name for fs in determine_inverses.values() for f in fs]
            real_recs._validate_fields(vals, inverse_fields)
            if _debug:
                _t_validate1 = time.perf_counter()

            for fields in determine_inverses.values():
                # write again on non-stored fields that have been invalidated from cache
                for field in fields:
                    if (
                        not field.store
                        and (
                            not field.inherited
                            or field.type not in ("one2many", "many2many")
                        )
                        and any(field._cache_missing_ids(real_recs))
                    ):
                        field.mark_dirty(real_recs, vals[field.name])

                # inverse records that are not being computed
                try:
                    fields[0].determine_inverse(real_recs)
                except AccessError as e:
                    if fields[0].inherited:
                        description = self.env["ir.model"]._get(self._name).name
                        raise AccessError(
                            _(
                                "%(previous_message)s\n\nImplicitly accessed through '%(document_kind)s' (%(document_model)s).",
                                previous_message=e.args[0],
                                document_kind=description,
                                document_model=self._name,
                            )
                        ) from e
                    raise

            # Pass 2: validate constraints touching inversed fields.
            real_recs._validate_fields(inverse_fields)

        if self._check_company_auto:
            self._check_company(list(vals))

        if _debug or _agg:
            _t_end = time.perf_counter()
        if _debug:
            _fnames = (
                ", ".join(sorted(vals)) if len(vals) <= 20 else f"{len(vals)} fields"
            )
            _orm_crud.debug(
                "[%.3f ms] write %s: %d records, %s"
                " | acl=%.1f classify=%.1f before=%.1f dirty=%.1f after=%.1f"
                " validate=%.1f inverse=%.1f",
                (_t_end - _t0) * 1000,
                self._name,
                len(self),
                _fnames,
                (_t_acl - _t0) * 1000,
                (_t_classify - _t_acl) * 1000,
                (_t_before - _t_classify) * 1000,
                (_t_dirty - _t_before) * 1000,
                (_t_after - _t_dirty) * 1000,
                (_t_validate1 - _t_after) * 1000,
                (_t_end - _t_validate1) * 1000,
            )
        if _agg and (p := self.env.transaction._orm_profiler):
            p.record_write(self._name, len(self), _t_end - _t0)

        return True

    def _write(self, vals: ValuesType) -> None:
        """Low-level implementation of write()"""
        self._write_multi([vals] * len(self))
        # _write_multi bypasses field.write() and modified(), so the cache
        # retains stale pre-_write values. Invalidate the updated fields so
        # filtered_domain / Field.__get__ read fresh DB values.
        if self:
            self.invalidate_recordset(list(vals), flush=False)

    def _write_multi(self, vals_list: list[ValuesType]) -> None:
        """Low-level implementation of write()"""
        # raise (not assert): under python -O a length mismatch would zip-
        # truncate rows and persist wrong values on the trailing records.
        if len(self) != len(vals_list):
            raise ValueError(
                f"_write_multi: len(records)={len(self)} != "
                f"len(vals_list)={len(vals_list)}"
            )

        if not self:
            return

        _debug = _orm_crud.isEnabledFor(logging.DEBUG)
        if _debug:
            _t0 = time.perf_counter()

        # determine records that require updating parent_path
        parent_records = (
            self._parent_store_update_prepare(vals_list) if self._parent_store else None
        )

        # Detect uniform vals (common: _write passes [vals]*N, all same object)
        uniform = len(vals_list) <= 1 or vals_list[0] is vals_list[-1]

        # Pipeline batches multiple UPDATE statements in a single round-trip.
        # Nesting is safe — psycopg3 reuses the active pipeline as a no-op.
        with self.env.cr.pipeline():
            if uniform:
                vals = vals_list[0]
                if self._log_access:
                    vals = {
                        "write_uid": self.env.uid,
                        "write_date": self.env.cr.now(),
                    } | vals
                fnames, template_row = zip(*sorted(vals.items()), strict=False)
                # iterate _ids directly — avoids N singleton recordset objects
                rows = [((id_,) + template_row) for id_ in self._ids]
                for sub_rows in batched(rows, UPDATE_BATCH_SIZE, strict=False):
                    self._execute_update(fnames, sub_rows)
            else:
                if self._log_access:
                    log_vals = {
                        "write_uid": self.env.uid,
                        "write_date": self.env.cr.now(),
                    }
                    vals_list = [(log_vals | vals) for vals in vals_list]
                updates = defaultdict(list)
                for id_, vals in zip(self._ids, vals_list, strict=True):
                    fnames, row = zip(*sorted(vals.items()), strict=False)
                    updates[fnames].append((id_,) + row)
                for fnames, rows in updates.items():
                    for sub_rows in batched(rows, UPDATE_BATCH_SIZE, strict=False):
                        self._execute_update(fnames, sub_rows)

        # update parent_path
        if parent_records:
            parent_records._parent_store_update()

        if _debug:
            _orm_crud.debug(
                "[%.3f ms] _write_multi %s: %d records, %s, %d batches",
                (time.perf_counter() - _t0) * 1000,
                self._name,
                len(self),
                "uniform" if uniform else f"{len(updates)} groups",
                (len(self) + UPDATE_BATCH_SIZE - 1) // UPDATE_BATCH_SIZE,
            )

    def _execute_update(self, fnames: tuple[str, ...], rows: list[tuple]) -> None:
        """Execute UPDATE FROM VALUES for a group of records sharing the same fields.

        :param fnames: Tuple of field names being updated (sorted).
        :param rows: List of tuples (id, val1, val2, ...) — one per record.
        """
        # Backend dispatch: in-memory storage vs PostgreSQL
        storage = self.env.transaction.storage
        if storage is not None:
            # In-memory path: store plain values, skipping the JSONB merge for
            # translated/company-dependent fields (enough for business tests).
            updates = [
                (row[0], dict(zip(fnames, row[1:], strict=True)))
                for row in rows
            ]
            storage.upsert_rows(self._table, updates)
            return

        columns = []
        assignments = []
        for fname in fnames:
            field = self._fields[fname]
            # raise (not assert): under python -O a non-column field would build
            # a malformed UPDATE failing later with an opaque column_type error.
            if not field.is_column:
                raise RuntimeError(
                    f"_execute_update: {field} is not a stored column field"
                )
            column = SQL.identifier(fname)
            # the type cast is necessary for some values, like NULLs
            expr = SQL('"__tmp".%s::%s', column, SQL(field.column_type[1]))
            if field.translate is True:
                # this is the SQL equivalent of:
                # None if expr is None else (
                #     (column or {'en_US': next(iter(expr.values()))}) | expr
                # )
                expr = SQL(
                    """CASE WHEN %(expr)s IS NULL THEN NULL ELSE
                        COALESCE(%(table)s.%(column)s, jsonb_build_object(
                            'en_US', jsonb_path_query_first(%(expr)s, '$.*')
                        )) || %(expr)s
                    END""",
                    table=SQL.identifier(self._table),
                    column=column,
                    expr=expr,
                )
            if field.company_dependent:
                fallbacks = self.env["ir.default"]._get_field_column_fallbacks(
                    self._name, fname
                )
                expr = SQL(
                    """(SELECT jsonb_object_agg(d.key, d.value)
                    FROM jsonb_each(COALESCE(%(table)s.%(column)s, '{}'::jsonb) || %(expr)s) d
                    JOIN jsonb_each(%(fallbacks)s) f
                    ON d.key = f.key AND d.value != f.value)""",
                    table=SQL.identifier(self._table),
                    column=column,
                    expr=expr,
                    fallbacks=fallbacks,
                )
            columns.append(column)
            assignments.append(SQL("%s = %s", column, expr))

        self.env.cr.execute(
            SQL(
                """ UPDATE %(table)s
                SET %(assignments)s
                FROM (VALUES %(values)s) AS "__tmp"("id", %(columns)s)
                WHERE %(table)s."id" = "__tmp"."id"
            """,
                table=SQL.identifier(self._table),
                assignments=SQL(", ").join(assignments),
                values=SQL(", ").join(rows),
                columns=SQL(", ").join(columns),
            )
        )

    def unlink(self) -> typing.Literal[True]:
        """Delete the records in ``self``.

        :raise AccessError: if the user may not delete all the given records
        :raise UserError: if a record is the default property of other records
        """
        if not self:
            return True

        _debug = _orm_crud.isEnabledFor(logging.DEBUG)
        _agg = _orm_profiling_enabled
        if _debug or _agg:
            _t0 = time.perf_counter()

        if _n1_enabled and (tracker := self.env.transaction._n1_tracker):
            tracker.record("unlink", self._name, len(self), frozenset())

        self.check_access("unlink")
        if _debug:
            _t_acl = time.perf_counter()

        from odoo.addons.base.models.ir_model import MODULE_UNINSTALL_FLAG

        for func in self._ondelete_methods:
            # func._ondelete is True if it should be called during uninstallation
            if func._ondelete or not self.env.context.get(MODULE_UNINSTALL_FLAG):
                func(self)
        if _debug:
            _t_ondelete = time.perf_counter()

        # TOFIX: avoids an infinite loop where recomputing a field triggers
        # recompute of another field sharing the same compute function, which
        # re-triggers both.
        core = self.env._core
        if core.has_any_pending():
            # Iterate pending entries (typically few) rather than all model
            # fields (often 100+); clear only entries for the current model.
            model_name = self._name
            deleted_ids = self._ids
            for field in list(core.pending_fields()):
                if field.model_name == model_name:
                    core.mark_done(field, deleted_ids)

        self.env.flush_all()

        if _debug:
            _t_flush = time.perf_counter()

        cr = self.env.cr
        Data = self.env["ir.model.data"].sudo().with_context({})
        Defaults = self.env["ir.default"].sudo()
        Attachment = self.env["ir.attachment"].sudo()
        ir_model_data_unlink = Data
        ir_attachment_unlink = Attachment

        # Capture ALL dependency paths before deletion (see _modified_before
        # docstring for why unlink passes ALL fields, not just relational ones).
        # Example: deleting a sale order line recomputes the order's total amount.
        with self.env.protecting(self._fields.values(), self):
            self._modified_before(self._fields)
        if _debug:
            _t_before = time.perf_counter()

        for sub_ids in batched(self.ids, cr.BATCH_SIZE, strict=False):
            data, attachments = self._unlink_process_batch(
                sub_ids,
                Data,
                Defaults,
                Attachment,
            )
            ir_model_data_unlink |= data
            ir_attachment_unlink |= attachments
        if _debug:
            _t_sql = time.perf_counter()

        # Invalidate the *whole* cache, since the ORM does not handle all
        # changes made in the database, like cascading delete, and targeted
        # invalidation misses non-stored computed/related fields that depend
        # on FK fields through multi-hop chains
        # (e.g. personal_stage_type_id → personal_stage_id → stage_id).
        self.env.invalidate_all(flush=False)

        if ir_model_data_unlink:
            ir_model_data_unlink.unlink()
        if ir_attachment_unlink:
            ir_attachment_unlink.unlink()

        # auditing: deletions are infrequent and leave no trace in the database
        _unlink.info(
            "User #%s deleted %s records with IDs: %r",
            self.env.uid,
            self._name,
            self.ids,
        )

        if _debug or _agg:
            _t_end = time.perf_counter()
        if _debug:
            _orm_crud.debug(
                "[%.3f ms] unlink %s: %d records"
                " | acl=%.1f ondelete=%.1f flush=%.1f before=%.1f"
                " sql=%.1f invalidate=%.1f",
                (_t_end - _t0) * 1000,
                self._name,
                len(self),
                (_t_acl - _t0) * 1000,
                (_t_ondelete - _t_acl) * 1000,
                (_t_flush - _t_ondelete) * 1000,
                (_t_before - _t_flush) * 1000,
                (_t_sql - _t_before) * 1000,
                (_t_end - _t_sql) * 1000,
            )
        if _agg and (p := self.env.transaction._orm_profiler):
            p.record_unlink(self._name, len(self), _t_end - _t0)

        return True

    def _unlink_process_batch(
        self,
        sub_ids: tuple[int, ...],
        Data: typing.Any,
        Defaults: typing.Any,
        Attachment: typing.Any,
    ) -> tuple[Self, Self]:
        """Process one batch of record deletions during unlink().

        Executes DELETE SQL, collects ir.model.data and ir.attachment records
        for cleanup, handles company-dependent M2O restrict/set-null cascade,
        and discards ir.default entries.

        :param sub_ids: tuple of record IDs to delete in this batch
        :param Data: ir.model.data model proxy (sudo, empty context)
        :param Defaults: ir.default model proxy (sudo)
        :param Attachment: ir.attachment model proxy (sudo)
        :return: (data_records, attachment_records) to unlink after all batches
        """
        # Backend dispatch: in-memory storage vs PostgreSQL
        storage = self.env.transaction.storage
        if storage is not None:
            # In-memory path: skip ir.model.data / ir.attachment / company-
            # dependent cleanup — those models may not exist in test context.
            storage.delete_rows(self._table, list(sub_ids))
            return Data.browse(), Attachment.browse()

        from odoo.addons.base.models.ir_model import MODULE_UNINSTALL_FLAG

        cr = self.env.cr
        records = self.browse(sub_ids)

        cr.execute(
            SQL(
                "DELETE FROM %s WHERE id = ANY(%s)",
                SQL.identifier(self._table),
                list(sub_ids),
            )
        )

        # Remove the ir_model_data reference for xml/csv-created records:
        # they have no real FK, so the reference would dangle. Done as
        # superuser and with no context to avoid access restrictions and
        # side-effects during admin calls.
        data = Data.search([("model", "=", self._name), ("res_id", "in", sub_ids)])

        # Likewise remove the relevant ir_attachment records (via raw SQL:
        # ir_attachment's search() is overridden to hide attachments of
        # deleted records).
        cr.execute(
            SQL(
                "SELECT id FROM ir_attachment WHERE res_model=%s AND res_id = ANY(%s)",
                self._name,
                list(sub_ids),
            )
        )
        attachments = Attachment.browse(row[0] for row in cr.fetchall())

        # block deleting a record used as an ir.default fallback for a company-
        # dependent m2o, unless MODULE_UNINSTALL_FLAG (then discard_records below
        # clears the fallback)
        if (
            many2one_fields := self.env.registry.many2one_company_dependents[self._name]
        ) and not self.env.context.get(MODULE_UNINSTALL_FLAG):
            IrModelFields = self.env["ir.model.fields"]
            field_ids = tuple(
                IrModelFields._get_ids(field.model_name).get(field.name)
                for field in many2one_fields
            )
            sub_ids_json_text = tuple(json_dumps(id_) for id_ in sub_ids)
            if default := Defaults.search(
                [
                    ("field_id", "in", field_ids),
                    ("json_value", "in", sub_ids_json_text),
                ],
                limit=1,
                order="id desc",
            ):
                ir_field = default.field_id.sudo()
                field = self.env[ir_field.model]._fields[ir_field.name]
                record = self.browse(json_loads(default.json_value))
                raise UserError(
                    _(
                        "Unable to delete %(record)s because it is used as the default value of %(field)s",
                        record=record,
                        field=field,
                    )
                )

        # on delete set null/restrict for jsonb company-dependent many2one.
        # Defensive: the JSONPath below interpolates each id via f-string
        # (psycopg can't bind parameters inside a jsonpath expression). Safe
        # because ``self.ids`` returns only ints; reject anything else loudly so
        # a future caller can't smuggle a SQL fragment through ``sub_ids``.
        if many2one_fields and not all(
            isinstance(id_, int) and id_ > 0 for id_ in sub_ids
        ):
            raise TypeError(
                f"_unlink_process_batch: sub_ids must be positive ints, got {sub_ids!r}"
            )
        for field in many2one_fields:
            model = self.env[field.model_name]
            if field.ondelete == "restrict" and not self.env.context.get(
                MODULE_UNINSTALL_FLAG
            ):
                if res := self.env.execute_query(
                    SQL(
                        """
                    SELECT id, %(field)s
                    FROM %(table)s
                    WHERE %(field)s IS NOT NULL
                    AND %(field)s @? %(jsonpath)s
                    ORDER BY id
                    LIMIT 1
                    """,
                        table=SQL.identifier(model._table),
                        field=SQL.identifier(field.name),
                        jsonpath=f"$.* ? ({' || '.join(f'@ == {id_}' for id_ in sub_ids)})",
                    )
                ):
                    on_restrict_id, field_json = res[0]
                    to_delete_id = next(iter(field_json.values()))
                    on_restrict_record = model.browse(on_restrict_id)
                    to_delete_record = self.browse(to_delete_id)
                    raise UserError(
                        _(
                            "You cannot delete %(to_delete_record)s, as it is used by %(on_restrict_record)s",
                            to_delete_record=to_delete_record,
                            on_restrict_record=on_restrict_record,
                        )
                    )
            else:
                # Set null on company-dependent M2O references.
                # RETURNING id lets us trigger modified() on affected
                # records so their computed dependents get recomputed.
                affected = self.env.execute_query(
                    SQL(
                        """
                    UPDATE %(table)s
                    SET %(field)s = (
                        SELECT jsonb_object_agg(
                            key,
                            CASE
                                WHEN value::int4 in %(ids)s THEN NULL
                                ELSE value::int4
                            END)
                        FROM jsonb_each_text(%(field)s)
                    )
                    WHERE %(field)s IS NOT NULL
                    AND %(field)s @? %(jsonpath)s
                    RETURNING id
                    """,
                        table=SQL.identifier(model._table),
                        field=SQL.identifier(field.name),
                        ids=sub_ids,
                        jsonpath=f"$.* ? ({' || '.join(f'@ == {id_}' for id_ in sub_ids)})",
                    )
                )
                if affected:
                    affected_recs = model.browse(row[0] for row in affected)
                    affected_recs.modified([field.name])

        # For the same reason, remove the defaults having some of the
        # records as value
        Defaults.discard_records(records)

        return data, attachments

    def _parent_store_create(self) -> None:
        """Set the parent_path field on ``self`` after its creation."""
        if not self._parent_store:
            return
        # DictBackend: skip parent_path SQL — hierarchy not supported yet
        if self.env.transaction.storage is not None:
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

    def _parent_store_update_prepare(self, vals_list: list[ValuesType]) -> Self:
        """Return the records in ``self`` that must update their parent_path
        field. This must be called before updating the parent field.
        """
        if not self._parent_store:
            return self.browse()
        # DictBackend: skip parent_path SQL — hierarchy not supported yet
        if self.env.transaction.storage is not None:
            return self.browse()

        # associate each new parent_id to its corresponding record ids
        parent_to_ids = defaultdict(list)
        for id_, vals in zip(self._ids, vals_list, strict=True):
            if self._parent_name in vals:
                parent_to_ids[vals[self._parent_name]].append(id_)

        if not parent_to_ids:
            return self.browse()

        self.flush_recordset([self._parent_name])

        # return the records for which the parent field will change
        sql_parent = SQL.identifier(self._parent_name)
        conditions = []
        for parent_id, ids in parent_to_ids.items():
            if parent_id:
                condition = SQL(
                    "(%s != %s OR %s IS NULL)",
                    sql_parent,
                    parent_id,
                    sql_parent,
                )
            else:
                condition = SQL("%s IS NOT NULL", sql_parent)
            conditions.append(SQL('("id" = ANY(%s) AND %s)', list(ids), condition))

        rows = self.env.execute_query(
            SQL(
                "SELECT id FROM %s WHERE %s ORDER BY id",
                SQL.identifier(self._table),
                SQL(" OR ").join(conditions),
            )
        )
        return self.browse(row[0] for row in rows)

    def _parent_store_update(self) -> None:
        """Update the parent_path field of ``self``."""
        for parent, records in self.grouped(self._parent_name).items():
            # determine new prefix of parent_path of records
            prefix = parent.parent_path or ""

            # check for recursion
            if prefix:
                parent_ids = {int(label) for label in prefix.split("/")[:-1]}
                if not parent_ids.isdisjoint(records._ids):
                    raise UserError(_("Recursion Detected."))

            # update parent_path of all records and their descendants
            updated = dict(
                self.env.execute_query(
                    SQL(
                        """ UPDATE %(table)s child
                    SET parent_path = concat(%(prefix)s::text, substr(child.parent_path,
                            length(node.parent_path) - length(node.id || '/') + 1))
                    FROM %(table)s node
                    WHERE node.id IN %(ids)s
                    AND child.parent_path LIKE concat(node.parent_path, %(wildcard)s::text)
                    RETURNING child.id, child.parent_path """,
                        table=SQL.identifier(self._table),
                        prefix=prefix,
                        ids=tuple(records.ids),
                        wildcard="%",
                    )
                )
            )

            # update the cache of updated nodes, and determine what to recompute
            field = self._fields["parent_path"]
            for id_, path in updated.items():
                field._update_cache(self.browse(id_), path)
            records = self.browse(updated)
            records.modified(["parent_path"])
