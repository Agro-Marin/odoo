import functools
import logging
import typing
import warnings
from collections import defaultdict
from collections.abc import Callable, Iterator

from odoo.libs.func import locked
from odoo.tools import OrderedSet
from odoo.tools.misc import Collector

from ..components.model_graph import ModelGraph, TriggerTree
from ._registry_stubs import _RegistryStubs

if typing.TYPE_CHECKING:
    from odoo.fields import Field


_logger = logging.getLogger("odoo.registry")
_schema = logging.getLogger("odoo.schema")


class _RegistryFieldsMixin(_RegistryStubs):
    #: Owned here rather than declared in ``_RegistryStubs`` and assigned by
    #: ``Registry.init`` — see the note on ``_RegistrySchemaMixin`` for why that
    #: combination made these invisible to the coupling gate.
    model_graph: ModelGraph
    field_setup_dependents: Collector[Field, Field]
    many2one_company_dependents: Collector[str, Field]
    many2many_relations: defaultdict[tuple[str, str, str], OrderedSet]

    def _init_field_state(self) -> None:
        """Initialise this mixin's own state. Called by ``Registry.init``."""
        self.model_graph = ModelGraph()
        self.field_setup_dependents = Collector()
        self.many2one_company_dependents = Collector()
        self.many2many_relations = defaultdict(OrderedSet)

    def _publish_field_metadata(self) -> tuple:
        return self.field_inverses, self.field_computed

    def _ensure_field_triggers(self) -> dict:
        refused_at = self.__dict__.get("_field_triggers_refused_at")
        if refused_at is not None and refused_at != self.model_graph.trigger_epoch:
            self.__dict__.pop("_field_triggers", None)
            self.__dict__.pop("_field_triggers_refused_at", None)
        return self._field_triggers

    @property
    def field_depends(self) -> typing.Any:
        return self.model_graph.field_depends

    @property
    def field_depends_context(self) -> typing.Any:
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
        self._ensure_field_triggers()
        return self.model_graph.get_trigger_tree(fields, select)

    def get_dependent_fields(self, field: Field) -> Iterator[Field]:
        self._ensure_field_triggers()
        return self.model_graph.get_dependent_fields(field)

    @locked
    def _discard_fields(self, fields: list[Field]) -> None:
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
        self._ensure_field_triggers()
        return self.model_graph.get_field_trigger_tree(field)

    @functools.cached_property
    def _field_triggers(self) -> dict:
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
            self.__dict__["_field_triggers_refused_at"] = graph.trigger_epoch
            return graph.published_triggers

        self.__dict__.pop("_field_triggers_refused_at", None)

        self._publish_field_metadata()

        graph.freeze()

        return graph.published_triggers

    def is_modifying_relations(self, field: Field) -> bool:
        self._ensure_field_triggers()
        return self.model_graph.is_modifying_relations(field)
