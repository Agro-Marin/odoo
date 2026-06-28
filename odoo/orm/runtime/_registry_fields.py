"""Field-dependency graph: triggers, inverses, computed-field deps.

Extracted from the Registry god-class; mixed into Registry (registry.py).
"""

import functools
import logging
import typing
import warnings
from collections import defaultdict
from collections.abc import Callable, Iterator

from odoo.tools.misc import Collector

from ..components.model_graph import TriggerTree
from ._registry_stubs import _RegistryStubs

if typing.TYPE_CHECKING:
    from odoo.fields import Field


_logger = logging.getLogger("odoo.registry")
_schema = logging.getLogger("odoo.schema")


class _RegistryFieldsMixin(_RegistryStubs):
    """Field-dependency graph: triggers, inverses, computed-field deps."""

    @property
    def field_depends(self) -> typing.Any:
        """Field dependencies — delegates to model_graph (single source of truth)."""
        return self.model_graph._depends

    @property
    def field_depends_context(self) -> typing.Any:
        """Context dependencies — delegates to model_graph (single source of truth)."""
        return self.model_graph._depends_context

    @functools.cached_property
    def field_inverses(self) -> Collector[Field, Field]:
        result = Collector()
        for model_cls in self.models.values():
            for field in model_cls._fields.values():
                if field.relational:
                    field.setup_inverses(self, result)
        self.model_graph._inverses = result
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
        self.model_graph._computed = computed
        return computed

    def get_trigger_tree(
        self, fields: list[Field], select: Callable[[Field], bool] = bool
    ) -> TriggerTree:
        """Return the trigger tree to traverse when ``fields`` have been modified.

        ``select`` is called on each field to choose which fields to keep in the
        tree nodes. Delegates to ``model_graph``.
        """
        self._field_triggers  # noqa: B018 — ensure trigger data is computed
        return self.model_graph.get_trigger_tree(fields, select)

    def get_dependent_fields(self, field: Field) -> Iterator[Field]:
        """Return an iterable on the fields that depend on ``field``.

        Delegates to ``model_graph``.
        """
        self._field_triggers  # noqa: B018 — ensure trigger data is computed
        return self.model_graph.get_dependent_fields(field)

    def _discard_fields(self, fields: list[Field]) -> None:
        """Discard the given fields from the registry's internal data structures."""
        for f in fields:
            # tests usually don't reload the registry, so when they create
            # custom fields those may not have the entire dependency setup, and
            # may be missing from these maps
            self.field_depends.pop(f, None)

        # Invalidate every field-derived cached_property so each rebuilds on next
        # access. ``_field_triggers`` reads ``field_inverses``/``field_computed``,
        # so stale caches there would feed it bad data.
        for _prop in ("_field_triggers", "field_inverses", "field_computed"):
            self.__dict__.pop(_prop, None)

        # discard from model_graph's data structures (inverses, triggers,
        # computed, depends) and clear its trigger tree caches
        self.model_graph.discard_fields(fields)

    def get_field_trigger_tree(self, field: Field) -> TriggerTree:
        """Return a field's trigger tree (transitive closure of field triggers).

        Delegates to ``model_graph``, which handles the closure, path
        simplification (m2o→o2m cancellation), and caching.
        """
        self._field_triggers  # noqa: B018 — ensure trigger data is computed
        return self.model_graph.get_field_trigger_tree(field)

    @functools.cached_property
    def _field_triggers(self) -> dict:
        """Return the field triggers (the inverse of field dependencies) as
        ``{field: {path: fields}}``: ``field`` is a dependency, ``path`` is the
        sequence of fields to inverse, and ``fields`` depend on ``field``.

        Built incrementally into ``model_graph`` via its ``add_trigger`` API.
        """
        # Reset and rebuild triggers incrementally into model_graph
        self.model_graph.reset_triggers()

        for Model in self.models.values():
            if Model._abstract:
                continue
            for field in Model._fields.values():
                try:
                    dependencies = list(field.resolve_depends(self))
                except Exception:
                    # dependencies of custom fields may not exist; ignore that case
                    if not field.base_field.manual:
                        raise
                else:
                    for dependency in dependencies:
                        *path, dep_field = dependency
                        self.model_graph.add_trigger(
                            dep_field, tuple(reversed(path)), [field]
                        )

        # Ensure lazy properties (field_inverses, field_computed) are built
        # and stored into model_graph (via their cached_property side effects).
        self.field_inverses  # noqa: B018 — trigger lazy build
        self.field_computed  # noqa: B018 — trigger lazy build

        # The trigger graph is now complete. Eagerly populate its derived
        # caches (trigger trees, modifying-relations, recompute order) so the
        # process-shared graph is read-only during request handling: reads
        # become pure lookups instead of lazy first-read rebuilds. On a
        # free-threaded build that avoids N threads redundantly rebuilding the
        # same trees on a cold cache (measured ~4x); it is not a corruption fix
        # (CPython's dicts are thread-safe), but it makes the "static after
        # construction" contract real. Re-runs whenever the graph is rebuilt
        # (this is a cached_property reset on registry invalidation).
        self.model_graph.freeze()

        return self.model_graph._triggers

    def is_modifying_relations(self, field: Field) -> bool:
        """Return whether ``field`` has dependent fields on some records, and
        that modifying ``field`` might change the dependent records.

        Delegates to ``model_graph``.
        """
        self._field_triggers  # noqa: B018 — ensure trigger data is computed
        return self.model_graph.is_modifying_relations(field)
