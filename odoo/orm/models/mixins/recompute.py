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
from odoo.libs.profiling import _OrmProfile
from odoo.tools import OrderedSet
from odoo.tools.misc import PENDING

from ... import decorators as api
from ...components.recompute import RecomputeScheduler
from ...helpers import own_class_memo, resolve_fnames
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

        if before:
            scheduler = core.new_scheduler()
            self._modified_trigger_loop(fnames, False, scheduler)

            for field, ids in scheduler.to_recompute.items():
                records = self.env[field.model_name].browse(ids)
                self.env.add_to_compute(field, records)
        else:
            scheduler = core.new_scheduler(inline=True)
            self._modified_trigger_loop(fnames, create, scheduler)

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

        # Through the barrier, never the bare attribute: `_field_triggers` is a
        # cached_property, so a build that lost the publication race to a
        # concurrent teardown is memoized holding the *pre-teardown* snapshot
        # (publication swaps a fresh _TriggerState rather than mutating), and
        # nothing but `_ensure_field_triggers()` ever pops it.  Reading the
        # attribute here would let the early-exit below consult a permanently
        # stale map and skip recompute/invalidate for triggers added since.
        # See orm/tests/test_trigger_publication_staleness.py.
        _field_triggers = self.pool._ensure_field_triggers()
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

        todo = [self._modified(fields, create)]
        prof.mark("tree")

        env = self.env
        for field, records, entry_create in itertools.chain.from_iterable(todo):
            cached_ids = None
            if field.recursive and not field.is_stored_computed:
                cached_ids = field._get_all_cache_ids(env).keys()

            recursive_ids = scheduler.process_entry(
                field,
                OrderedSet(records._ids),
                cached_ids=cached_ids,
            )

            if scheduler.to_invalidate:
                for inv_field, inv_ids in scheduler.to_invalidate:
                    inv_field._invalidate_cache(env, inv_ids)
                scheduler.to_invalidate.clear()

            if recursive_ids:
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

        def select(field):
            return field.is_stored_computed or bool(field._get_all_cache_ids(self.env))

        tree = self.pool.get_trigger_tree(fields, select=select)
        if not tree:
            return ()

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

        for field in tree.root:
            yield field, self, create

        for field, subtree in tree.items():
            if create and field.type in ("many2one", "many2one_reference"):
                continue

            model = self.env[field.model_name]
            for invf in model.pool.field_inverses[field]:
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

                    if field.model_name == records._name:
                        if not any(self._ids):
                            records = records.browse(
                                it and NewId(it) for it in records._ids
                            )
                        break
            else:
                self_ids = self._ids
                real_ids = [id_ for id_ in self_ids if id_]
                records = model.browse()
                if real_ids:
                    records = model.search([(field.name, "in", real_ids)], order="id")
                if len(real_ids) != len(self_ids):
                    field_cache = field._get_cache(model.env)
                    cache_records = model.browse(field_cache)
                    new_ids = set(self_ids)
                    records |= cache_records.filtered(
                        lambda r, field=field, new_ids=new_ids: (
                            not set(r[field.name]._ids).isdisjoint(new_ids)
                        )
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

        Names are resolved before the "nothing pending" shortcut, so an invalid
        one is rejected whether or not there happened to be work to do.

        :param fnames: optional iterable of field names to compute
        """
        self._recompute_fields(self._resolve_recompute_fields(fnames), None)

    def _recompute_recordset(self, fnames: Collection[str] | None = None) -> None:
        """Process the pending computations of the fields of the records in ``self``.

        Names are resolved before the "nothing pending" shortcut, so an invalid
        one is rejected whether or not there happened to be work to do.

        :param fnames: optional iterable of field names to compute
        """
        self._recompute_fields(self._resolve_recompute_fields(fnames), self._ids)

    def _resolve_recompute_fields(
        self, fnames: Collection[str] | None
    ) -> Collection[Field]:
        """Resolve *fnames* to fields, defaulting to this model's stored-computed ones."""
        if fnames is None:
            return self._get_stored_computed_fields()
        return resolve_fnames(self, fnames)

    def _recompute_fields(
        self, fields: Collection[Field], ids: Sequence[IdType] | None
    ) -> None:
        """Process the pending computations of already-resolved *fields*.

        The shared tail of :meth:`_recompute_model` / :meth:`_recompute_recordset`
        and the flush entry points, which resolve their names once and hand the
        fields down rather than re-resolving them here.
        """
        if not self.env._core.has_pending():
            return
        for field in fields:
            if field.is_stored_computed:
                self._recompute_field(field, ids)

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

        Invalid names are rejected before the "nothing dirty" shortcut, so the
        rejection does not depend on transaction state.

        :param fnames: optional iterable of field names to check for dirtiness
        """
        fields = None if fnames is None else resolve_fnames(self, fnames)
        if fields is not None:
            core = self.env._core
            if not core.has_pending() and not core.is_any_dirty():
                return

        prof = _OrmProfile(_orm_cache)

        self._recompute_fields(
            self._get_stored_computed_fields() if fields is None else fields, None
        )
        prof.mark("recompute")
        core = self.env._core
        if fields is None or any(map(core.has_dirty_field, fields)):
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

        Invalid names are rejected before the "empty recordset" and "nothing
        dirty" shortcuts, so the rejection does not depend on either.

        :param fnames: optional iterable of field names to flush
        """
        named_fields = None if fnames is None else resolve_fnames(self, fnames)
        if not self:
            return
        if named_fields is not None:
            core = self.env._core
            if not core.has_pending() and not core.is_any_dirty():
                return
        self._recompute_fields(
            self._get_stored_computed_fields()
            if named_fields is None
            else named_fields,
            self._ids,
        )
        fields: Collection[Field] = (
            self._fields.values() if named_fields is None else named_fields
        )
        core = self.env._core
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
        core = self.env._core
        dirty_field_ids = core.pop_dirty_for_model(self._name)
        if not dirty_field_ids:
            return

        prof = _OrmProfile(_orm_cache)

        model = self
        env = self.env
        cls = type(model)
        _no_prefetch = ()

        id_to_fields: dict[int, list] = defaultdict(list)
        for field, ids in dirty_field_ids.items():
            for id_ in ids:
                id_to_fields[id_].append(field)

        dirty_ids = list(id_to_fields)
        prof.mark("collect")
        if prof.debug:
            _batch_count = 0

        BATCH_SIZE = 1000
        with env.cr.pipeline():
            for some_ids in batched(dirty_ids, BATCH_SIZE, strict=False):
                if prof.debug:
                    _batch_count += 1
                vals_list = []
                _new = object.__new__
                try:
                    for id_ in some_ids:
                        record = _new(cls)
                        record.env = env
                        record._ids = (id_,)
                        record._prefetch_ids = _no_prefetch
                        vals = {}
                        for f in id_to_fields[id_]:
                            col_val = f.get_column_update(record)
                            if col_val is not PENDING:
                                vals[f.name] = col_val
                            elif core.is_pending(f, id_):
                                # Awaiting recomputation: hand the dirty flag
                                # back (it was popped above) so the next pass
                                # writes the value once it exists.  Dropping it
                                # here is what silently lost the write.
                                core.mark_dirty(f, (id_,))
                            else:
                                raise RuntimeError(
                                    f"Cannot flush {f}: the cached value is "
                                    f"PENDING on {self._name}({id_}) but the "
                                    f"field is not scheduled for recomputation, "
                                    f"so the value can never materialize"
                                )
                        vals_list.append(vals)
                except KeyError as e:
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
