"""Field recomputation and flush mixin for BaseModel.

The DB-coupled half of the cache subsystem: ``modified`` trigger-tree
traversal, recompute scheduling, and the batched flush of dirty fields to the
database. The in-memory record cache and invalidation live in the sibling
:class:`~odoo.orm.models.mixins.cache.CacheMixin`.

This mixin drives the pure-Python
:class:`~odoo.orm.components.recompute.RecomputeScheduler` (``components/recompute.py``):
the scheduler is the DB-free accumulator, this mixin does the model-/DB-side
traversal and SQL.
"""

import itertools
import logging
import typing
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from itertools import batched
from typing import Self

from odoo.exceptions import MissingError
from odoo.tools import OrderedSet
from odoo.tools.misc import PENDING
from odoo.tools.orm_profiler import _OrmProfile

from ... import decorators as api
from ...components.recompute import RecomputeScheduler
from ...helpers import own_class_memo
from ...primitives import NewId
from ._model_stubs import _ModelStubs

_orm_cache = logging.getLogger("odoo.orm.cache")
_orm_compute = logging.getLogger("odoo.orm.compute")

if typing.TYPE_CHECKING:
    from ..._typing import IdType
    from ...fields.base import Field
    from ...runtime import TriggerTree


class RecomputeMixin(_ModelStubs):
    """Mixin providing field recomputation and database flush for recordsets."""

    __slots__ = ()

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
            ``True`` uses the old dependency graph to capture what needs
            recomputation before values change; ``False`` (default) marks
            fields based on the new state.
        """
        if not self or not fnames:
            return

        core = self.env._core

        # Both modes seed the scheduler's recursive-field prune from the
        # engine's live pending map (see OrmCore.new_scheduler): ids already
        # pending from earlier modified() calls are not re-traversed.
        if before:
            # Pre-modification: collect what depends on self via the OLD graph,
            # then batch-schedule.
            scheduler = core.new_scheduler()
            self._modified_trigger_loop(fnames, False, scheduler)

            for field, ids in scheduler.to_recompute.items():
                records = self.env[field.model_name].browse(ids)
                self.env.add_to_compute(field, records)
        else:
            # Post-modification: the scheduler pushes each entry's delta into
            # pending inline, so the lazy trigger-tree iterator sees newly
            # pending fields when resolving inverse edges.  Needed for
            # cascades: the iterator reads stored-computed fields via __get__,
            # which only computes if the field is pending.
            scheduler = core.new_scheduler(inline=True)
            self._modified_trigger_loop(fnames, create, scheduler)

        # Non-stored invalidation is drained inline during the trigger walk
        # (see _modified_trigger_loop), so to_invalidate is always empty here —
        # a post-loop pass would be dead code.

    def _modified_before(self, fnames: Collection[str]) -> None:
        """Capture dependencies BEFORE records in ``self`` are modified.

        Calls ``self.modified(fnames, before=True)`` (via the method, so
        subclass overrides are respected), using the OLD dependency graph.

        Callers pass different scopes: ``write()`` passes only relational fields
        (a scalar change doesn't move who depends on it; a relational change
        moves the dependency path and needs both passes). ``unlink()`` passes
        ALL fields, since deletion breaks every path and has no
        post-modification pass.

        :param fnames: iterable of field names about to be modified
        """
        return self.modified(fnames, before=True)

    def _modified_trigger_loop(
        self,
        fnames: Collection[str],
        create: bool,
        scheduler: RecomputeScheduler,
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
        :param scheduler: accumulates recompute/invalidate decisions.  An
            inline scheduler (``core.new_scheduler(inline=True)``) additionally
            pushes each entry's delta into the engine's pending set immediately
            (required for ``before=False``, so the lazy iterator's __get__
            reads trigger ``ensure_computed`` on them)
        """
        prof = _OrmProfile(_orm_compute)
        if prof.debug:
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
            prof.stop()
            if prof.debug:
                _orm_compute.debug(
                    "[%.3f ms] modified %s: %d fields on %d records (create=%s, no triggers)",
                    prof.elapsed * 1000,
                    self._name,
                    len(_fnames_list),
                    len(self),
                    create,
                )
            if prof.agg and (p := self.env.transaction._orm_profiler):
                p.record_modified(self._name, len(self), prof.elapsed)
            return

        # determine what to trigger (with iterators)
        todo = [self._modified(fields, create)]
        prof.mark("tree")

        # Process trigger entries lazily.  This loop only does trigger traversal
        # (DB-coupled inverse resolution) and recursive expansion; the scheduler
        # handles protection, cycle detection, routing, and (in inline mode)
        # per-entry delta scheduling into the engine's pending set.
        env = self.env
        for field, records, entry_create in itertools.chain.from_iterable(todo):
            # Recursive non-stored fields: pass cached IDs so the scheduler can
            # filter to IDs that actually have data to invalidate.
            cached_ids = None
            if field.recursive and not field.is_stored_computed:
                cached_ids = field._get_all_cache_ids(env).keys()

            # OrderedSet keeps the recordset's id order all the way into the
            # engine's OrderedSet pending map (deterministic recompute order).
            recursive_ids = scheduler.process_entry(
                field,
                OrderedSet(records._ids),
                cached_ids=cached_ids,
            )

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
                todo.append(
                    records.browse(recursive_ids)._modified([field], entry_create)
                )

            if prof.debug:
                n = len(recursive_ids) if recursive_ids else len(records)
                if field.is_stored_computed:
                    _mark_count += n
                else:
                    _invalidate_count += n

        prof.stop()
        if prof.debug:
            _orm_compute.debug(
                "[%.3f ms] modified %s: %d fields on %d records (create=%s)"
                " | tree=%.1f traverse=%.1f marked=%d invalidated=%d",
                prof.elapsed * 1000,
                self._name,
                len(_fnames_list),
                len(self),
                create,
                prof.ms("start", "tree"),
                prof.ms("tree", "end"),
                _mark_count,
                _invalidate_count,
            )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record_modified(self._name, len(self), prof.elapsed)

    def _modified(
        self, fields: list[Field], create: bool
    ) -> Iterable[tuple[Field, Self, bool]]:
        """Build the merged field-trigger tree for ``fields`` on ``self`` and
        delegate the traversal to :meth:`_modified_triggers`.

        Prunes subtrees of non-stored computed fields with no cached data
        (nothing to invalidate), then runs the traversal as ``sudo`` with
        ``active_test=False`` when the tree has relational edges (inverse
        traversal needs ACL bypass and must see archived records). Yields the
        ``(field, records, created)`` triples to recompute.
        """

        # Merge the fields' trigger trees to evaluate all triggers at once.
        # For non-stored computed fields, `_modified_triggers` may traverse the
        # tree (extra queries) only to learn which cached records to invalidate.
        # Fields with no cache data can be ignored, so `select` discards
        # subtrees that only contain them.
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
        """Iterate a tree of field triggers on ``self``, walking backwards along
        field dependencies and yielding ``(field, records, created)`` triples to
        recompute.
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

                    # When self holds new records (NewId), the inverse lookup
                    # returns real IDs; re-wrap them as NewId so cache lookups
                    # work for unsaved records (which have no DB row).
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

        Memoized per-class via :func:`own_class_memo` (own-``__dict__`` read, so
        a child never reuses a parent's tuple). The class survives re-setup
        (``__bases__`` reassigned in place), so ``registration._prepare_setup``
        clears the memo explicitly when fields change.
        """
        return own_class_memo(
            cls,
            "_stored_computed_fields__",
            lambda: tuple(f for f in cls._fields.values() if f.is_stored_computed),
        )

    def _recompute_model(self, fnames: Collection[str] | None = None) -> None:
        """Process the pending computations of the fields of ``self``'s model.

        :param fnames: optional iterable of field names to compute
        """
        core = self.env._core
        if not core.has_pending():
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
        if not core.has_pending():
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

        prof = _OrmProfile(_orm_compute)

        # do not force recomputation on new records; those will be
        # recomputed by accessing the field on the records
        records = self.browse(tuple(id_ for id_ in ids if id_))
        field.recompute(records)

        prof.stop()
        if prof.debug:
            _orm_compute.debug(
                "[%.3f ms] recompute_field %s.%s: %d records",
                prof.elapsed * 1000,
                field.model_name,
                field.name,
                len(records),
            )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record_recompute(field.model_name, len(records), prof.elapsed)

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
            if not core.has_pending() and not core.is_any_dirty():
                return

        prof = _OrmProfile(_orm_cache)

        self._recompute_model(fnames)
        prof.mark("recompute")
        core = self.env._core
        if fnames is None or any(
            core.has_dirty_field(self._fields[fname]) for fname in fnames
        ):
            # Flush ALL dirty fields (see the dirty-guard note in the docstring):
            # a partial flush could write a row with stale computed dependents.
            self._flush()

        prof.stop()
        if prof.debug:
            _orm_cache.debug(
                "[%.3f ms] flush_model %s | recompute=%.1f flush=%.1f",
                prof.elapsed * 1000,
                self._name,
                prof.ms("start", "recompute"),
                prof.ms("recompute", "end"),
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
            if not core.has_pending() and not core.is_any_dirty():
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

        prof = _OrmProfile(_orm_cache)

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
        prof.mark("collect")
        if prof.debug:
            _batch_count = 0

        # Perform updates in batches to limit memory footprint.
        # Pipeline keeps all batch UPDATEs in a single round-trip.
        BATCH_SIZE = 1000
        with env.cr.pipeline():
            for some_ids in batched(dirty_ids, BATCH_SIZE, strict=False):
                if prof.debug:
                    _batch_count += 1
                vals_list = []
                _new = object.__new__
                try:
                    for id_ in some_ids:
                        # HOT per-record loop: inline mirror of `_spawn` (keep
                        # slot assignments in sync), no prefetch.
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
                    # RuntimeError, not AssertionError: this is a runtime data-
                    # integrity failure, and test frameworks that catch
                    # AssertionError generically would misreport it as a test
                    # failure rather than a fatal ORM error.
                    raise RuntimeError(
                        f"Could not find all values of {self._name}({id_}) to flush them\n"
                        f"    Context: {env.context}\n"
                        f"    Cache: {env.cache!r}"
                    ) from e
                model.browse(some_ids)._write_multi(vals_list)

        prof.stop()
        if prof.debug:
            _orm_cache.debug(
                "[%.3f ms] _flush %s: %d fields, %d records, %d batches"
                " | collect=%.1f update=%.1f",
                prof.elapsed * 1000,
                self._name,
                len(dirty_field_ids),
                len(dirty_ids),
                _batch_count,
                prof.ms("start", "collect"),
                prof.ms("collect", "end"),
            )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record_flush(self._name, len(dirty_ids), prof.elapsed)
