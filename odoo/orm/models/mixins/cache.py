"""Cache and recomputation management mixin for BaseModel.

Manages the record cache, invalidation, flushing, and field recomputation.
"""

import itertools
import logging
import time
import typing
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from itertools import batched
from typing import Self

from odoo.exceptions import MissingError
from odoo.tools import OrderedSet
from odoo.tools.misc import PENDING
from odoo.tools.orm_profiler import _orm_profiling_enabled

from ... import decorators as api
from ...components.recompute import RecomputeScheduler
from ...primitives import NewId

_orm_cache = logging.getLogger("odoo.orm.cache")
_orm_compute = logging.getLogger("odoo.orm.compute")

if typing.TYPE_CHECKING:
    from ..._typing import IdType
    from ...fields.base import Field
    from ...runtime import TriggerTree


class RecordCache(Mapping):
    """A mapping from field names to values, to read the cache of a record."""

    __slots__ = ["_record"]

    def __init__(self, record) -> None:
        # raise (not assert) so the contract holds under python -O.
        if len(record) != 1:
            raise ValueError(f"Unexpected RecordCache({record})")
        self._record = record

    def __contains__(self, name: object) -> bool:
        """Return whether `record` has a cached value for field ``name``."""
        record = self._record
        field = record._fields[name]
        return record.id in field._get_cache(record.env)

    def __getitem__(self, name: str) -> object:
        """Return the cached value of field ``name`` for `record`."""
        record = self._record
        field = record._fields[name]
        return field._get_cache(record.env)[record.id]

    def __iter__(self) -> typing.Iterator[str]:
        """Iterate over the field names with a cached value."""
        record = self._record
        id_ = record.id
        env = record.env
        model_name = record._name
        depends_context = env._field_depends_context
        for field, cache in env._core.iter_field_items():
            if field.model_name != model_name:
                continue
            if field in depends_context:
                # context-dependent: cache is {context_key: {id: value}}
                cache = cache.get(env.cache_key(field))
                if cache and id_ in cache:
                    yield field.name
            elif id_ in cache:
                yield field.name

    def __len__(self) -> int:
        """Return the number of fields with a cached value."""
        return sum(1 for name in self)


class CacheMixin:
    """Mixin providing cache and recomputation management for recordsets."""

    __slots__ = ()

    @property
    def _cache(self) -> RecordCache:
        """Return the cache of ``self``, mapping field names to values."""
        return RecordCache(self)

    @api.private
    def invalidate_model(
        self, fnames: Collection[str] | None = None, flush: bool = True
    ) -> None:
        """Invalidate the cache of all records of ``self``'s model, when the
        cached values no longer correspond to the database values.  If the
        parameter is given, only the given fields are invalidated from cache.

        :param fnames: optional iterable of field names to invalidate
        :param flush: whether pending updates should be flushed before invalidation.
            It is ``True`` by default, which ensures cache consistency.
            Do not use this parameter unless you know what you are doing.
        """
        if flush:
            self.flush_model(fnames)
        self._invalidate_cache(fnames)
        if _orm_cache.isEnabledFor(logging.DEBUG):
            _orm_cache.debug("invalidate_model %s: fnames=%s", self._name, fnames)

    @api.private
    def invalidate_recordset(
        self, fnames: Collection[str] | None = None, flush: bool = True
    ) -> None:
        """Invalidate the cache of the records in ``self``, when the cached
        values no longer correspond to the database values.  If the parameter
        is given, only the given fields on ``self`` are invalidated from cache.

        :param fnames: optional iterable of field names to invalidate
        :param flush: whether pending updates should be flushed before invalidation.
            It is ``True`` by default, which ensures cache consistency.
            Do not use this parameter unless you know what you are doing.
        """
        if flush:
            self.flush_recordset(fnames)
        self._invalidate_cache(fnames, self._ids)
        if _orm_cache.isEnabledFor(logging.DEBUG):
            _orm_cache.debug(
                "invalidate_recordset %s: %d records, fnames=%s",
                self._name,
                len(self),
                fnames,
            )

    def _invalidate_cache(
        self,
        fnames: Collection[str] | None = None,
        ids: Sequence[IdType] | None = None,
    ) -> None:
        if (
            ids is not None and not ids
        ):  # Avoid invalidating field_inverses for no reason
            return

        if fnames is None:
            fields = self._fields.values()
        else:
            fields = [self._fields[fname] for fname in fnames]

        env = self.env
        field_inverses = self.pool.field_inverses
        for field in fields:
            field._invalidate_cache(env, ids)
            # Also flush+invalidate inverse fields (e.g. the O2M inverse of a
            # M2O) to avoid stale reverse lookups.
            if inverses := field_inverses.get(field):
                for invf in inverses:
                    env[invf.model_name].flush_model([invf.name])
                    invf._invalidate_cache(env)

    @api.private
    def modified(
        self,
        fnames: Collection[str],
        create: bool = False,
        before: bool = False,
    ) -> None:
        """Notify that fields have been modified on ``self``.  This
        invalidates the cache where necessary, and prepares the recomputation
        of dependent stored fields.

        :param fnames: iterable of field names modified on records ``self``
        :param create: whether called in the context of record creation
        :param before: whether called BEFORE the modification takes place.
            When ``True``, uses the current (old) dependency graph to capture
            what needs recomputation before values change.  When ``False``
            (default), marks fields to recompute based on the new state.
        """
        if not self or not fnames:
            return

        core = self.env._core
        engine = core.engine

        if before:
            # Pre-modification: collect what depends on self via the OLD graph,
            # then batch-schedule.  ``marked=engine.pending`` enables cycle
            # detection against fields already scheduled.
            scheduler = RecomputeScheduler(engine, marked=engine.pending)
            self._modified_trigger_loop(fnames, False, scheduler)

            for field, ids in scheduler.to_recompute.items():
                records = self.env[field.model_name].browse(ids)
                self.env.add_to_compute(field, records)
        else:
            # Post-modification: schedule inline into engine.pending so the lazy
            # trigger-tree iterator sees newly pending fields when resolving
            # inverse edges.  Needed for cascades: the iterator reads stored-
            # computed fields via __get__, which only computes if field is
            # pending.
            scheduler = RecomputeScheduler(engine, marked={})
            self._modified_trigger_loop(fnames, create, scheduler, engine=engine)

        # Non-stored invalidation is drained inline during the trigger walk
        # (see _modified_trigger_loop), so to_invalidate is always empty here —
        # a post-loop pass would be dead code.

    def _modified_before(self, fnames: Collection[str]) -> None:
        """Capture dependencies BEFORE records in ``self`` are modified.

        Calls ``self.modified(fnames, before=True)`` (via the method, so
        subclass overrides are respected), using the OLD dependency graph.

        Scope asymmetry by design: ``write()`` passes only relational fields
        (a scalar change doesn't move who depends on it, so the post pass
        suffices; relational changes move the dependency path and need both).
        ``unlink()`` passes ALL fields, since deletion breaks every path and
        there is no post-modification pass afterwards.

        :param fnames: iterable of field names about to be modified
        """
        return self.modified(fnames, before=True)

    def _modified_trigger_loop(
        self,
        fnames: Collection[str],
        create: bool,
        scheduler: RecomputeScheduler,
        *,
        engine: typing.Any = None,
    ) -> None:
        """Shared trigger-tree traversal for :meth:`modified` /
        :meth:`_modified_before`.

        Walks the trigger tree for ``fnames``, delegating each scheduling
        decision (protection, cycle detection, recompute vs invalidate) to the
        :class:`RecomputeScheduler`.

        A field F's trigger tree holds the fields that depend on F plus the
        inverse fields used to find which records to recompute.  E.g. if G
        depends on F, H on X.F, I on W.X.F, and J on Y.F::

                                      [G]
                                    X/   \\Y
                                  [H]     [J]
                                W/
                              [I]

        When F is modified, mark G on records, H on inverse(X, records), I on
        inverse(W, inverse(X, records)), and J on inverse(Y, records).

        :param fnames: field names that were (or will be) modified
        :param create: whether in record-creation context
        :param scheduler: accumulates recompute/invalidate decisions
        :param engine: if given, stored-computed entries are scheduled into
            ``engine.pending`` immediately (required for ``before=False``, so the
            lazy iterator's __get__ reads trigger ensure_computed on them)
        """
        _debug = _orm_compute.isEnabledFor(logging.DEBUG)
        _agg = _orm_profiling_enabled
        if _debug or _agg:
            _t0 = time.perf_counter()
        if _debug:
            _fnames_list = (
                list(fnames) if not isinstance(fnames, (list, dict)) else fnames
            )
            _mark_count = 0
            _invalidate_count = 0

        # Fast path: skip traversal when no modified field has dependents.
        _field_triggers = self.pool._field_triggers
        _fields = self._fields
        fields = [_fields[fname] for fname in fnames]
        if not any(f in _field_triggers for f in fields):
            if _debug:
                _orm_compute.debug(
                    "[%.3f ms] modified %s: %d fields on %d records (create=%s, no triggers)",
                    (time.perf_counter() - _t0) * 1000,
                    self._name,
                    len(_fnames_list),
                    len(self),
                    create,
                )
            if _agg and (p := self.env.transaction._orm_profiler):
                p.record_modified(self._name, len(self), time.perf_counter() - _t0)
            return

        # determine what to trigger (with iterators)
        todo = [self._modified(fields, create)]
        if _debug:
            _t_tree = time.perf_counter()

        # Process trigger entries lazily.  This loop only does trigger traversal
        # (DB-coupled inverse resolution) and recursive expansion; the scheduler
        # handles protection, cycle detection, and routing.
        env = self.env
        for field, records, create in itertools.chain.from_iterable(todo):
            # Recursive non-stored fields: pass cached IDs so the scheduler can
            # filter to IDs that actually have data to invalidate.
            cached_ids = None
            if field.recursive and not field.is_stored_computed:
                cached_ids = field._get_all_cache_ids(env).keys()

            recursive_ids = scheduler.process_entry(
                field,
                set(records._ids),
                create,
                cached_ids=cached_ids,
            )

            # Inline scheduling: make stored-computed entries visible in
            # engine.pending for the trigger-tree iterator.
            if engine is not None:
                new_ids = scheduler.to_recompute.get(field)
                if new_ids:
                    engine.schedule(field, new_ids)

            # Inline invalidation: invalidate non-stored fields now so a stored-
            # computed recompute triggered mid-traversal (via __get__) reads
            # fresh dependencies, not a stale cached related/computed value
            # (e.g. product_tmpl_id still pointing at the old product).
            if scheduler.to_invalidate:
                for inv_field, inv_ids in scheduler.to_invalidate:
                    inv_field._invalidate_cache(env, inv_ids)
                scheduler.to_invalidate.clear()

            if recursive_ids:
                # Recurse into the field's dependents.
                todo.append(records.browse(recursive_ids)._modified([field], create))

            if _debug:
                n = len(recursive_ids) if recursive_ids else len(records)
                if field.is_stored_computed:
                    _mark_count += n
                else:
                    _invalidate_count += n

        if _debug or _agg:
            _t_end = time.perf_counter()
        if _debug:
            _orm_compute.debug(
                "[%.3f ms] modified %s: %d fields on %d records (create=%s)"
                " | tree=%.1f traverse=%.1f marked=%d invalidated=%d",
                (_t_end - _t0) * 1000,
                self._name,
                len(_fnames_list),
                len(self),
                create,
                (_t_tree - _t0) * 1000,
                (_t_end - _t_tree) * 1000,
                _mark_count,
                _invalidate_count,
            )
        if _agg and (p := self.env.transaction._orm_profiler):
            p.record_modified(self._name, len(self), _t_end - _t0)

    def _modified(
        self, fields: list[Field], create: bool
    ) -> Iterable[tuple[Field, Self, bool]]:
        """Return an iterator traversing a tree of field triggers on ``self``,
        traversing backwards field dependencies along the way, and yielding
        tuple ``(field, records, created)`` to recompute.
        """

        # The fields' trigger trees are merged in order to evaluate all triggers
        # at once. For non-stored computed fields, `_modified_triggers` might
        # traverse the tree (at the cost of extra queries) only to know which
        # records to invalidate in cache. But in many cases, most of these
        # fields have no data in cache, so they can be ignored from the start.
        # This allows us to discard subtrees from the merged tree when they
        # only contain such fields.
        def select(field):
            return field.is_stored_computed or bool(field._get_all_cache_ids(self.env))

        tree = self.pool.get_trigger_tree(fields, select=select)
        if not tree:
            return ()

        # sudo + active_test=False is only needed when the tree has edges
        # (relational inverse traversal reads self[invf.name] which needs
        # ACL bypass and must include archived records).  For root-only trees
        # (all dependents on the same model), the trigger loop only uses
        # self._ids, so the original recordset is sufficient.
        if len(tree):
            records = self.sudo().with_context(active_test=False)
        else:
            records = self
        return records._modified_triggers(tree, create)

    def _modified_triggers(
        self, tree: TriggerTree, create: bool = False
    ) -> Iterable[tuple[Field, Self, bool]]:
        """Return an iterator traversing a tree of field triggers on ``self``,
        traversing backwards field dependencies along the way, and yielding
        tuple ``(field, records, created)`` to recompute.
        """
        if not self:
            return

        # first yield what to compute
        for field in tree.root:
            yield field, self, create

        # then traverse dependencies backwards, and proceed recursively
        for field, subtree in tree.items():
            if create and field.type in ("many2one", "many2one_reference"):
                # upon creation, no other record has a reference to self
                continue

            # subtree is another tree of dependencies
            model = self.env[field.model_name]
            for invf in model.pool.field_inverses[field]:
                # use an inverse of field without domain
                if not (invf.type in ("one2many", "many2many") and invf.domain):
                    if invf.type == "many2one_reference":
                        rec_ids = OrderedSet()
                        for rec in self:
                            try:
                                if rec[invf.model_field] == field.model_name:
                                    rec_ids.add(rec[invf.name])
                            except MissingError:
                                continue
                        records = model.browse(rec_ids)
                    else:
                        try:
                            records = self[invf.name]
                        except MissingError:
                            records = self.exists()[invf.name]

                    # When self contains new records (NewId), the inverse
                    # lookup returns real IDs, but we need NewId-wrapped
                    # versions so that cache lookups work correctly for
                    # unsaved records.  This wrapping is the simplest fix
                    # given that NewId records don't exist in the database.
                    if field.model_name == records._name:
                        if not any(self._ids):
                            # if self are new, records should be new as well
                            records = records.browse(
                                it and NewId(it) for it in records._ids
                            )
                        break
            else:
                new_records = self.filtered(lambda r: not r.id)
                real_records = self - new_records
                records = model.browse()
                if real_records:
                    records = model.search(
                        [(field.name, "in", real_records.ids)], order="id"
                    )
                if new_records:
                    field_cache = field._get_cache(model.env)
                    cache_records = model.browse(field_cache)
                    new_ids = set(self._ids)
                    records |= cache_records.filtered(
                        lambda r, field=field, new_ids=new_ids: not set(r[field.name]._ids).isdisjoint(new_ids)
                    )

            yield from records._modified_triggers(subtree)

    @classmethod
    def _get_stored_computed_fields(cls) -> tuple[Field, ...]:
        """Cached tuple of stored-computed fields for this model.

        The result is cached on the class object and naturally invalidated
        when the class is rebuilt during module loading (``_setup_fields``
        creates new model classes).

        The memo is read from and written to ``cls``'s *own* ``__dict__``,
        never via normal attribute lookup.  Attribute lookup walks the MRO,
        and a model that prototype-inherits another (``_inherit`` with a
        different ``_name``) has the parent's runtime class among its bases.
        A plain ``cls.<attr>`` read would therefore return the *parent's*
        cached tuple whenever the parent populated its memo first — and,
        because the read would succeed, the child would never record its
        own.  That leak is sticky for the registry's lifetime and silently
        drops the child's extra stored-computed fields from recompute
        (``_recompute_model``/``_recompute_recordset`` iterate this tuple).
        """
        cache = cls.__dict__
        if "_stored_computed_fields__" in cache:
            return cache["_stored_computed_fields__"]
        result = tuple(f for f in cls._fields.values() if f.is_stored_computed)
        cls._stored_computed_fields__ = result
        return result

    def _recompute_model(self, fnames: Collection[str] | None = None) -> None:
        """Process the pending computations of the fields of ``self``'s model.

        :param fnames: optional iterable of field names to compute
        """
        core = self.env._core
        if not core.has_any_pending():
            return

        if fnames is None:
            # Iterate stored-computed fields of the model rather than
            # just the currently-pending ones.  An inverse method called from
            # inside a compute may add OTHER fields to the pending set
            # (e.g. _inverse_name adds payment_reference); a snapshot of
            # pending_fields() would miss these newly-added entries.
            for field in self._get_stored_computed_fields():
                self._recompute_field(field)
        else:
            for fname in fnames:
                field = self._fields[fname]
                if field.is_stored_computed:
                    self._recompute_field(field)

    def _recompute_recordset(self, fnames: Collection[str] | None = None) -> None:
        """Process the pending computations of the fields of the records in ``self``.

        :param fnames: optional iterable of field names to compute
        """
        core = self.env._core
        if not core.has_any_pending():
            return

        if fnames is None:
            # Same rationale as _recompute_model: iterate stored-computed
            # fields to handle cascading additions to the pending set.
            ids = self._ids
            for field in self._get_stored_computed_fields():
                self._recompute_field(field, ids)
        else:
            for fname in fnames:
                field = self._fields[fname]
                if field.is_stored_computed:
                    self._recompute_field(field, self._ids)

    def _recompute_field(
        self, field: Field, ids: Sequence[IdType] | None = None
    ) -> None:
        ids_to_compute = self.env._core.pending_ids(field)
        if ids is None:
            ids = ids_to_compute
        else:
            ids = [id_ for id_ in ids if id_ in ids_to_compute]
        if not ids:
            return

        _debug = _orm_compute.isEnabledFor(logging.DEBUG)
        _agg = _orm_profiling_enabled
        if _debug or _agg:
            _t0 = time.perf_counter()

        # do not force recomputation on new records; those will be
        # recomputed by accessing the field on the records
        records = self.browse(tuple(id_ for id_ in ids if id_))
        field.recompute(records)

        if _debug or _agg:
            _t_end = time.perf_counter()
        if _debug:
            _orm_compute.debug(
                "[%.3f ms] recompute_field %s.%s: %d records",
                (_t_end - _t0) * 1000,
                field.model_name,
                field.name,
                len(records),
            )
        if _agg and (p := self.env.transaction._orm_profiler):
            p.record_recompute(field.model_name, len(records), _t_end - _t0)

    @api.private
    def flush_model(self, fnames: Collection[str] | None = None) -> None:
        """Process the pending computations and database updates on ``self``'s
        model.  When the parameter is given, the method guarantees that at least
        the given fields are flushed to the database.  More fields can be
        flushed, though.

        **Important:** ``fnames`` acts as a **dirty guard**, not a filter.
        If *any* of the given fields are dirty, ALL dirty fields for this model
        are flushed (partial flushes would leave computed dependents stale).
        If *none* of the given fields are dirty, no flush occurs.
        Pass ``None`` to flush unconditionally.

        :param fnames: optional iterable of field names to check for dirtiness
        """
        # Fast path: when fnames is given and there's nothing pending at all
        # (no fields to recompute, no dirty fields), skip the entire method.
        # This is the common case during search/read operations.
        if fnames is not None:
            core = self.env._core
            if not core.has_any_pending() and not core.is_any_dirty():
                return

        _debug = _orm_cache.isEnabledFor(logging.DEBUG)
        if _debug:
            _t0 = time.perf_counter()

        self._recompute_model(fnames)
        if _debug:
            _t_recompute = time.perf_counter()
        core = self.env._core
        if fnames is None or any(
            core.has_dirty_field(self._fields[fname]) for fname in fnames
        ):
            # Flush ALL dirty fields, not just the requested ones.  Partial
            # flushes would leave computed dependents stale — e.g. flushing
            # 'amount' without 'tax_amount' that depends on it could write
            # an inconsistent row.  The "at least fnames" contract is correct.
            self._flush()

        if _debug:
            _t_end = time.perf_counter()
            _orm_cache.debug(
                "[%.3f ms] flush_model %s | recompute=%.1f flush=%.1f",
                (_t_end - _t0) * 1000,
                self._name,
                (_t_recompute - _t0) * 1000,
                (_t_end - _t_recompute) * 1000,
            )

    @api.private
    def flush_recordset(self, fnames: Collection[str] | None = None) -> None:
        """Process the pending computations and database updates on the records
        ``self``.   When the parameter is given, the method guarantees that at
        least the given fields on records ``self`` are flushed to the database.
        More fields and records can be flushed, though.

        :param fnames: optional iterable of field names to flush
        """
        if not self:
            return
        # Fast path: if nothing is pending globally, skip everything
        if fnames is not None:
            core = self.env._core
            if not core.has_any_pending() and not core.is_any_dirty():
                return
        self._recompute_recordset(fnames)
        if fnames is None:
            fields = self._fields.values()
        else:
            fields = [self._fields[fname] for fname in fnames]
        core = self.env._core
        # Singleton fast path: avoid set creation for the common case
        # of flushing a single record (e.g. before reading one field).
        ids = self._ids
        if len(ids) == 1:
            id_ = ids[0]
            if any(id_ in (core.get_dirty(field) or ()) for field in fields):
                self._flush()
        else:
            id_set = set(ids)
            if not all(
                id_set.isdisjoint(core.get_dirty(field) or ()) for field in fields
            ):
                self._flush()

    def _flush(self) -> None:
        # pop dirty fields and their corresponding record ids from cache
        core = self.env._core
        dirty_field_ids = core.pop_dirty_for_model(self._name)
        if not dirty_field_ids:
            return

        _debug = _orm_cache.isEnabledFor(logging.DEBUG)
        _agg = _orm_profiling_enabled
        if _debug or _agg:
            _t0 = time.perf_counter()

        model = self
        env = self.env
        cls = type(model)
        _no_prefetch = ()

        # Pre-invert {field: ids} → {id: [fields]} to avoid N*M membership
        # tests in the inner loop. This is O(total_dirty_entries) upfront
        # instead of O(n_fields * n_records) per-record.
        id_to_fields: dict[int, list] = defaultdict(list)
        for field, ids in dirty_field_ids.items():
            for id_ in ids:
                id_to_fields[id_].append(field)

        dirty_ids = list(id_to_fields)
        if _debug:
            _t_collect = time.perf_counter()
            _batch_count = 0

        # Perform updates in batches to limit memory footprint.
        # Pipeline keeps all batch UPDATEs in a single round-trip.
        BATCH_SIZE = 1000
        with env.cr.pipeline():
            for some_ids in batched(dirty_ids, BATCH_SIZE):
                if _debug:
                    _batch_count += 1
                vals_list = []
                _new = object.__new__
                try:
                    for id_ in some_ids:
                        # Lightweight record: inline creation, no prefetch
                        record = _new(cls)
                        record.env = env
                        record._ids = (id_,)
                        record._prefetch_ids = _no_prefetch
                        vals_list.append(
                            {
                                f.name: col_val
                                for f in id_to_fields[id_]
                                if (col_val := f.get_column_update(record))
                                is not PENDING
                            }
                        )
                except KeyError as e:
                    # AssertionError was misleading — this is a runtime
                    # data-integrity failure, not a broken assertion.  Some
                    # test frameworks catch AssertionError generically and
                    # would treat it as a failed test rather than a fatal
                    # ORM error.  RuntimeError is the right semantic class.
                    raise RuntimeError(
                        f"Could not find all values of {self._name}({id_}) to flush them\n"
                        f"    Context: {env.context}\n"
                        f"    Cache: {env.cache!r}"
                    ) from e
                model.browse(some_ids)._write_multi(vals_list)

        if _debug or _agg:
            _t_end = time.perf_counter()
        if _debug:
            _orm_cache.debug(
                "[%.3f ms] _flush %s: %d fields, %d records, %d batches"
                " | collect=%.1f update=%.1f",
                (_t_end - _t0) * 1000,
                self._name,
                len(dirty_field_ids),
                len(dirty_ids),
                _batch_count,
                (_t_collect - _t0) * 1000,
                (_t_end - _t_collect) * 1000,
            )
        if _agg and (p := self.env.transaction._orm_profiler):
            p.record_flush(self._name, len(dirty_ids), _t_end - _t0)
