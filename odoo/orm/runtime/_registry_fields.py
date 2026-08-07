"""Field-dependency graph: triggers, inverses, computed-field deps.

Extracted from the Registry god-class; mixed into Registry (registry.py).
"""

import functools
import logging
import typing
import warnings
from collections import defaultdict
from collections.abc import Callable, Iterator

from odoo.libs.func import locked
from odoo.tools.misc import Collector

from ..components.model_graph import TriggerTree
from ._registry_stubs import _RegistryStubs

if typing.TYPE_CHECKING:
    from odoo.fields import Field


_logger = logging.getLogger("odoo.registry")
_schema = logging.getLogger("odoo.schema")


class _RegistryFieldsMixin(_RegistryStubs):
    """Field-dependency graph: triggers, inverses, computed-field deps."""

    def _publish_field_metadata(self) -> tuple:
        """Return the inverses and co-computed groups, publishing them on the way.

        Both are ``cached_property`` whose evaluation publishes into
        ``model_graph``, and the trigger build needs them there before it
        freezes. Callers that only need the publication discard the result.
        """
        return self.field_inverses, self.field_computed

    def _ensure_field_triggers(self) -> dict:
        """Return the trigger map, building and publishing it if needed.

        Callers that only need the graph published into ``model_graph`` before
        reading it discard the result; naming the barrier keeps that intent
        readable, where the bare ``self._field_triggers`` it replaces looked
        like dead code.

        Also the retry point for a build that lost the publication race.  The
        marker is compared against the *current* epoch rather than merely being
        present, so the rebuild happens once the teardown that refused us has
        ended (``end_invalidation`` bumps the epoch) instead of on every call
        while it is still open -- a full rebuild walks every field of every
        model, so retrying inside the window would turn a teardown into a
        rebuild storm.
        """
        refused_at = self.__dict__.get("_field_triggers_refused_at")
        if refused_at is not None and refused_at != self.model_graph.trigger_epoch:
            self.__dict__.pop("_field_triggers", None)
            self.__dict__.pop("_field_triggers_refused_at", None)
        return self._field_triggers

    @property
    def field_depends(self) -> typing.Any:
        """Field dependencies — delegates to model_graph (single source of truth)."""
        return self.model_graph.field_depends

    @property
    def field_depends_context(self) -> typing.Any:
        """Context dependencies — delegates to model_graph (single source of truth)."""
        return self.model_graph.field_depends_context

    @functools.cached_property
    def field_inverses(self) -> Collector[Field, Field]:
        result = Collector()
        for model_cls in self.models.values():
            for field in model_cls._fields.values():
                if field.relational:
                    field.setup_inverses(self, result)
        self.model_graph.set_inverses(result)
        return result

    @functools.cached_property
    def field_computed(self) -> dict[Field, list[Field]]:
        """Return a dict mapping each field to the fields computed by the same method."""
        computed: dict[Field, list[Field]] = {}
        for model_name, Model in self.models.items():
            groups: defaultdict[Field, list[Field]] = defaultdict(list)
            for field in Model._fields.values():
                if field.compute:
                    computed[field] = group = groups[field.compute]
                    group.append(field)
            for fields in groups.values():
                if len(fields) < 2:
                    continue
                if len({field.compute_sudo for field in fields}) > 1:
                    fnames = ", ".join(field.name for field in fields)
                    warnings.warn(
                        f"{model_name}: inconsistent 'compute_sudo' for computed fields {fnames}. "
                        f"Either set 'compute_sudo' to the same value on all those fields, or "
                        f"use distinct compute methods for sudoed and non-sudoed fields.",
                        stacklevel=1,
                    )
                if len({field.precompute for field in fields}) > 1:
                    fnames = ", ".join(field.name for field in fields)
                    warnings.warn(
                        f"{model_name}: inconsistent 'precompute' for computed fields {fnames}. "
                        f"Either set all fields as precompute=True (if possible), or "
                        f"use distinct compute methods for precomputed and non-precomputed fields.",
                        stacklevel=1,
                    )
                if len({field.store for field in fields}) > 1:
                    fnames1 = ", ".join(
                        field.name for field in fields if not field.store
                    )
                    fnames2 = ", ".join(field.name for field in fields if field.store)
                    warnings.warn(
                        f"{model_name}: inconsistent 'store' for computed fields, "
                        f"accessing {fnames1} may recompute and update {fnames2}. "
                        f"Use distinct compute methods for stored and non-stored fields.",
                        stacklevel=1,
                    )
        self.model_graph.set_computed(computed)
        return computed

    def get_trigger_tree(
        self, fields: list[Field], select: Callable[[Field], bool] = bool
    ) -> TriggerTree:
        """Return the trigger tree to traverse when ``fields`` have been modified.

        ``select`` is called on each field to choose which fields to keep in the
        tree nodes. Delegates to ``model_graph``.
        """
        self._ensure_field_triggers()
        return self.model_graph.get_trigger_tree(fields, select)

    def get_dependent_fields(self, field: Field) -> Iterator[Field]:
        """Return an iterable on the fields that depend on ``field``.

        Delegates to ``model_graph``.
        """
        self._ensure_field_triggers()
        return self.model_graph.get_dependent_fields(field)

    @locked
    def _discard_fields(self, fields: list[Field]) -> None:
        """Discard the given fields from the registry's internal data structures.

        Taken under ``Registry._lock`` (writer side): this is called from a
        request thread (``ir.model.fields.unlink`` → ``pool._discard_fields``)
        while other request threads read the shared ``model_graph`` lock-free
        on the ``_search``/flush hot path. The published trigger map is
        therefore never mutated in place: ``ModelGraph.discard_fields``
        copy-scrubs it and atomically swaps in a fresh snapshot, and the eager
        ``_field_triggers`` rebuild below republishes the fully-rebuilt graph
        (the real publication — ``pop_field`` already removed the fields from
        the model classes before this method runs, so the rebuild cannot see
        them). The begin/end_invalidation bracket makes any reader-triggered
        rebuild that started before or during the discard lose the publication
        race: its map may still contain the discarded fields.
        """
        # try/finally: the window must close even if the discard raises, else
        # the graph refuses every later epoch-validated publication with
        # nothing logged.  See Registry._setup_models__ for the same bracket.
        self.model_graph.begin_invalidation()
        try:
            for f in fields:
                self.field_depends.pop(f, None)

            self.field_setup_dependents.discard_keys_and_values(fields)

            for _prop in ("_field_triggers", "field_inverses", "field_computed"):
                self.__dict__.pop(_prop, None)

            self.model_graph.discard_fields(fields)
        finally:
            self.model_graph.end_invalidation()

        self.__dict__.pop("_field_triggers", None)
        self._ensure_field_triggers()

    def get_field_trigger_tree(self, field: Field) -> TriggerTree:
        """Return a field's trigger tree (transitive closure of field triggers).

        Delegates to ``model_graph``, which handles the closure, path
        simplification (m2o→o2m cancellation), and caching.
        """
        self._ensure_field_triggers()
        return self.model_graph.get_field_trigger_tree(field)

    @functools.cached_property
    def _field_triggers(self) -> dict:
        """Return the field triggers (the inverse of field dependencies) as
        ``{field: {path: fields}}``: ``field`` is a dependency, ``path`` is the
        sequence of fields to inverse, and ``fields`` depend on ``field``.

        Built locally, then published to ``model_graph`` as one snapshot.
        """
        graph = self.model_graph
        start_epoch = graph.trigger_epoch
        new_triggers: defaultdict = defaultdict(lambda: defaultdict(list))
        for Model in self.models.values():
            if Model._abstract:
                continue
            for field in Model._fields.values():
                try:
                    dependencies = list(field.resolve_depends(self))
                except Exception as e:
                    if not field.base_field.manual:
                        raise
                    _logger.info(
                        "Could not resolve dependencies of manual field %s.%s; "
                        "ignoring them (%s: %s)",
                        field.model_name,
                        field.name,
                        type(e).__name__,
                        e,
                    )
                else:
                    for dependency in dependencies:
                        *path, dep_field = dependency
                        bucket = new_triggers[dep_field][tuple(reversed(path))]
                        if field not in bucket:
                            bucket.append(field)

        if not graph.set_triggers(new_triggers, epoch=start_epoch):
            # Lost the publication race: a teardown began while we were
            # building, so this map may describe half-set-up models and the
            # teardown's own rebuild is authoritative.  Record the epoch we
            # lost at so `_ensure_field_triggers` can retry once the teardown
            # ends -- `_field_triggers` is a cached_property, so without that
            # marker this refused build would be memoized permanently, and
            # `_publish_field_metadata()` and `graph.freeze()` below would stay
            # un-run with nothing left to trigger a retry.  (Popping the memo
            # here cannot work: cached_property writes it *after* this returns.)
            self.__dict__["_field_triggers_refused_at"] = graph.trigger_epoch
            return graph.published_triggers

        self.__dict__.pop("_field_triggers_refused_at", None)

        self._publish_field_metadata()

        graph.freeze()

        return graph.published_triggers

    def is_modifying_relations(self, field: Field) -> bool:
        """Return whether ``field`` has dependent fields on some records, and
        that modifying ``field`` might change the dependent records.

        Delegates to ``model_graph``.
        """
        self._ensure_field_triggers()
        return self.model_graph.is_modifying_relations(field)
