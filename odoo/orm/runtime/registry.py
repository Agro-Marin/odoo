"""Models registries."""

import functools
import inspect
import logging
import os
import threading
import time
import typing
import warnings
from collections import defaultdict, deque
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import ExitStack, closing, nullcontext
from functools import partial
from operator import attrgetter

import psycopg
from psycopg import sql as psycopg_sql

from odoo import db
from odoo.libs import gc
from odoo.libs.func import locked, reset_cached_properties
from odoo.libs.lru import LRU
from odoo.tools import (
    SQL,
    OrderedSet,
    config,
    lazy_classproperty,
    remove_accents,
    sql,
)
from odoo.tools.misc import Collector, format_frame

from .. import registration
from ..components.model_graph import ModelGraph, TriggerTree
from ..primitives import SUPERUSER_ID

if typing.TYPE_CHECKING:
    from odoo.db import BaseCursor, Connection, Cursor
    from odoo.fields import Field
    from odoo.models import BaseModel
    from odoo.modules import module_graph


_logger = logging.getLogger("odoo.registry")
_schema = logging.getLogger("odoo.schema")


_REGISTRY_CACHES = {
    "default": 8192,
    "assets": 512,
    "stable": 1024,
    "templates": 1024,
    "routing": 1024,  # 2 entries per website
    "routing.rewrites": 8192,  # url_rewrite entries
    "templates.cached_values": 2048,  # arbitrary
    "groups": 64,  # see res.groups
}

# cache invalidation dependencies: {cache_key: (cache_container, ...)}
_CACHES_BY_KEY = {
    "default": ("default", "templates.cached_values"),
    "assets": ("assets", "templates.cached_values"),
    "stable": ("stable", "default", "templates.cached_values"),
    "templates": ("templates", "templates.cached_values"),
    "routing": ("routing", "routing.rewrites", "templates.cached_values"),
    "groups": (
        "groups",
        "templates",
        "templates.cached_values",
    ),  # The processing of groups is saved in the view
}

_REPLICA_RETRY_TIME = 20 * 60  # 20 minutes


def _unaccent(
    x: SQL | str | psycopg_sql.Composable,
) -> SQL | str | psycopg_sql.Composed:
    if isinstance(x, SQL):
        return SQL("unaccent(%s)", x)
    if isinstance(x, psycopg_sql.Composable):
        return psycopg_sql.SQL("unaccent({})").format(x)
    return f"unaccent({x})"


class Registry(Mapping[str, type["BaseModel"]]):
    """Model registry for a database: a mapping of model names to model classes.

    One registry instance per database.
    """

    _lock: threading.RLock | DummyRLock = threading.RLock()

    @lazy_classproperty
    def registries(self) -> LRU[str, Registry]:
        """A mapping from database names to registries."""
        size = config.get("registry_lru_size", None)
        if not size:
            # Size the LRU depending of the memory limits
            if os.name != "posix":
                # cannot specify the memory limit soft on windows...
                size = 42
            else:
                # A registry takes 10MB of memory on average, so we reserve
                # 10Mb (registry) + 5Mb (working memory) per registry
                avgsz = 15 * 1024 * 1024
                limit_memory_soft = (
                    config["limit_memory_soft"]
                    if config["limit_memory_soft"] > 0
                    else (2048 * 1024 * 1024)
                )
                size = (limit_memory_soft // avgsz) or 1
        return LRU(size)

    def __new__(cls, db_name: str):
        """Return the registry for the given database name."""
        assert db_name, "Missing database name"
        with cls._lock:
            try:
                return cls.registries[db_name]
            except KeyError:
                return cls.new(db_name)

    _init: bool  # whether init needs to be done
    ready: bool  # whether everything is set up
    loaded: bool  # whether all modules are loaded
    models: dict[str, type[BaseModel]]

    @classmethod
    @locked
    def new(
        cls,
        db_name: str,
        *,
        update_module: bool = False,
        install_modules: Collection[str] = (),
        upgrade_modules: Collection[str] = (),
        reinit_modules: Collection[str] = (),
        new_db_demo: bool | None = None,
        models_to_check: set[str] | None = None,
    ) -> Registry:
        """Create and return a new registry for the given database name.

        :param db_name: The name of the database to associate with the Registry instance.
        :param update_module: If ``True``, update modules while loading the registry. Defaults to ``False``.
        :param install_modules: Names of modules to install.

          * If a specified module is **not installed**, it and all of its direct and indirect
            dependencies will be installed.

          Defaults to an empty tuple.

        :param upgrade_modules: Names of modules to upgrade. Their direct or indirect dependent
          modules will also be upgraded. Defaults to an empty tuple.
        :param reinit_modules: Names of modules to reinitialize.

          * If a specified module is **already installed**, it and all of its installed direct and
            indirect dependents will be re-initialized. Re-initialization means the module will be
            upgraded without running upgrade scripts, but with data loaded in ``'init'`` mode.

        :param new_db_demo: Whether to install demo data for the new database. If set to ``None``, the value will be
          determined by the ``config['with_demo']``. Defaults to ``None``
        """
        t0 = time.time()
        registry: Registry = object.__new__(cls)
        registry.init(db_name)
        registry.new = registry.init = registry.registries = None  # type: ignore
        first_registry = not cls.registries

        # init calls general code that calls Registry() back to get the registry
        # being built, so publish it in the registries dict now; remove it on
        # exception.
        cls.delete(db_name)
        cls.registries[db_name] = registry  # pylint: disable=unsupported-assignment-operation
        try:
            registry.setup_signaling()
            with registry.cursor() as cr:
                # critical section for multi-worker concurrency: on commit the
                # first worker proceeds to upgrade; others hit a serialization
                # error and retry, then find no upgrade marker. cuts concurrent
                # upgrades. kept outside the try-except below so a worker that
                # fails on the serialization error doesn't call
                # reset_modules_state while the first worker is upgrading.
                from odoo.modules import db

                if db.is_initialized(cr):
                    cr.execute(
                        "DELETE FROM ir_config_parameter WHERE key='base.partially_updated_database'"
                    )
                    if cr.rowcount:
                        update_module = True
            # This should be a method on Registry
            from odoo.modules.loading import (
                load_modules,
                reset_modules_state,
            )

            exit_stack = ExitStack()
            try:
                if upgrade_modules or install_modules or reinit_modules:
                    update_module = True
                if new_db_demo is None:
                    new_db_demo = config["with_demo"]
                if first_registry:
                    exit_stack.enter_context(gc.disabling_gc())
                load_modules(
                    registry,
                    update_module=update_module,
                    upgrade_modules=upgrade_modules,
                    install_modules=install_modules,
                    reinit_modules=reinit_modules,
                    new_db_demo=new_db_demo,
                    models_to_check=models_to_check,
                )
            except Exception:
                reset_modules_state(db_name)
                raise
            finally:
                exit_stack.close()
        except Exception:
            _logger.error("Failed to load registry")
            del cls.registries[db_name]  # pylint: disable=unsupported-delete-operation
            raise

        del registry._reinit_modules

        # load_modules() above may replace the registry by calling new() again
        # (when modules must be uninstalled), so re-read it.
        registry = cls.registries[db_name]  # pylint: disable=unsubscriptable-object

        registry._init = False
        registry.ready = True
        registry.registry_invalidated = bool(update_module)

        # After module upgrades, idle pooled connections may hold
        # stale prepared statement caches referencing old schema.
        # drain() replaces them with freshly configured connections.
        if update_module:
            from odoo.db import drain_all

            drain_all()
        registry.signal_changes()

        _logger.info("Registry loaded in %.3fs", time.time() - t0)
        return registry

    def init(self, db_name: str) -> None:
        self._init = True
        self.loaded = False
        self.ready = False

        self.models: dict[
            str, type[BaseModel]
        ] = {}  # model name/model instance mapping
        self._sql_constraints = set()  # type: ignore
        self._database_translated_fields: dict[
            str, str
        ] = {}  # {"model.field": "translate_func"} for translated db fields
        self._database_company_dependent_fields: set[str] = (
            set()
        )  # names of company dependent fields in database
        if config["test_enable"]:
            from odoo.tests.result import OdooTestResult

            self._assertion_report: OdooTestResult | None = OdooTestResult()
        else:
            self._assertion_report = None
        self._ordinary_tables: set[str] | None = None  # cached names of regular tables
        self._constraint_queue: dict[
            typing.Any, Callable[[BaseCursor], None]
        ] = {}  # queue of functions to call on finalization of constraints
        self.__caches: dict[str, LRU] = {
            cache_name: LRU(cache_size)
            for cache_name, cache_size in _REGISTRY_CACHES.items()
        }

        # update context during loading modules
        self._force_upgrade_scripts: set[str] = (
            set()
        )  # force the execution of the upgrade script for these modules
        self._reinit_modules: set[str] = set()  # modules to reinitialize

        # modules fully loaded (maintained during init phase by `loading` module)
        self._init_modules: set[str] = set()  # modules have been initialized
        self.updated_modules: list[str] = []  # installed/updated modules
        self.loaded_xmlids: set[str] = set()

        self.db_name = db_name
        self._db: Connection = db.db_connect(db_name, readonly=False)
        self._db_readonly: Connection | None = None
        self._db_readonly_failed_time: float | None = None
        if (
            config["db_replica_host"]
            or config["test_enable"]
            or "replica" in config["dev_mode"]
        ):  # readonly pool only when a db_replica_host is defined
            self._db_readonly = db.db_connect(db_name, readonly=True)

        # field_depends and field_depends_context are @property delegations
        # to model_graph._depends and model_graph._depends_context (see below).

        # field inverses
        self.many2many_relations: defaultdict[
            tuple[str, str, str], OrderedSet[tuple[str, str]]
        ] = defaultdict(OrderedSet)

        # invalidate the setup of related fields when a dependency is
        # invalidated (incremental model setup)
        self.field_setup_dependents: Collector[Field, Field] = Collector()

        # company dependent
        self.many2one_company_dependents: Collector[str, Field] = (
            Collector()
        )  # {model_name: (field1, field2, ...)}

        # constraint checks
        self.not_null_fields: set[Field] = set()

        # single source of truth for field metadata (inverses, depends,
        # depends_context, computed, triggers); Registry writes during setup,
        # then delegates reads here.
        self.model_graph = ModelGraph()

        # inter-process signaling: the `orm_signaling_registry` sequence signals
        # a full registry reload; each `orm_signaling_<cache>` sequence signals
        # that the corresponding cache must be invalidated (cleared).
        self.registry_sequence: int = -1
        self.cache_sequences: dict[str, int] = {}

        # Flags indicating invalidation of the registry or the cache.
        self._invalidation_flags = threading.local()

        from odoo.modules import db as modules_db

        with closing(self.cursor()) as cr:
            self.has_unaccent = modules_db.has_unaccent(cr)
            self.has_trigram = modules_db.has_trigram(cr)

        self.unaccent = _unaccent if self.has_unaccent else lambda x: x  # type: ignore
        self.unaccent_python = remove_accents if self.has_unaccent else lambda x: x

    @classmethod
    @locked
    def delete(cls, db_name: str) -> None:
        """Delete the registry linked to a given database."""
        if db_name in cls.registries:  # pylint: disable=unsupported-membership-test
            del cls.registries[db_name]  # pylint: disable=unsupported-delete-operation

    @classmethod
    @locked
    def delete_all(cls):
        """Delete all the registries."""
        cls.registries.clear()

    # Mapping abstract methods; the mixin provides keys, items, values, get,
    # __eq__, __ne__.
    def __len__(self) -> int:
        """Return the size of the registry."""
        return len(self.models)

    def __iter__(self) -> Iterator[str]:
        """Return an iterator over all model names."""
        return iter(self.models)

    def __getitem__(self, model_name: str) -> type[BaseModel]:
        """Return the model with the given name or raise KeyError if it doesn't exist."""
        return self.models[model_name]

    def __setitem__(self, model_name: str, model: type[BaseModel]) -> None:
        """Add or replace a model in the registry."""
        self.models[model_name] = model

    def __delitem__(self, model_name: str) -> None:
        """Remove a (custom) model from the registry."""
        del self.models[model_name]
        # the custom model can inherit from mixins ('mail.thread', ...)
        for Model in self.models.values():
            Model._inherit_children.discard(model_name)

    def descendants(
        self,
        model_names: Iterable[str],
        *kinds: typing.Literal["_inherit", "_inherits"],
    ) -> OrderedSet[str]:
        """Return the models corresponding to ``model_names`` and all those
        that inherit/inherits from them.
        """
        assert all(kind in ("_inherit", "_inherits") for kind in kinds)
        funcs = [attrgetter(kind + "_children") for kind in kinds]

        models: OrderedSet[str] = OrderedSet()
        queue = deque(model_names)
        while queue:
            model = self.get(queue.popleft())
            if model is None or model._name in models:
                continue
            models.add(model._name)
            for func in funcs:
                queue.extend(func(model))
        return models

    def load(self, module: module_graph.ModuleNode) -> list[str]:
        """Load a given module in the registry, and return the names of the
        directly modified models.

        At the Python level, the modules are already loaded, but not yet on a
        per-registry level. This method populates a registry with the given
        modules, i.e. it instantiates all the classes of a the given module
        and registers them in the registry.

        In order to determine all the impacted models, one should invoke method
        :meth:`descendants` with `'_inherit'` and `'_inherits'`.
        """
        from .. import models

        # clear cache to ensure consistency, but do not signal it
        for cache in self.__caches.values():
            cache.clear()

        reset_cached_properties(self)
        self.model_graph.clear_caches()

        # Instantiate registered classes (via the MetaModel automatic discovery
        # or via explicit constructor call), and add them to the pool.
        model_names = []
        for model_def in models.MetaModel._module_to_models__.get(module.name, []):
            # models register themselves in self.models
            model_cls = registration.add_to_registry(self, model_def)
            model_names.append(model_cls._name)

        return model_names

    @locked
    def _setup_models__(
        self, cr: BaseCursor, model_names: Iterable[str] | None = None
    ) -> None:
        """Perform the setup of models.
        This must be called after loading modules and before using the ORM.

        When given ``model_names``, it performs an incremental setup: only the
        models impacted by the given ``model_names`` and all the already-marked
        models will be set up. Otherwise, all models are set up.
        """
        from .environment import Environment

        env = Environment(cr, SUPERUSER_ID, {})
        env.invalidate_all()

        # uninstall registry hooks (only on a fully loaded registry, not one
        # still loading)
        if self.ready:
            for model in env.values():
                model._unregister_hook()

        # clear cache to ensure consistency, but do not signal it
        for cache in self.__caches.values():
            cache.clear()

        reset_cached_properties(self)
        self.model_graph.clear_caches()
        self.registry_invalidated = True

        # model classes on which to *not* recompute field_depends[_context]
        models_field_depends_done = set()

        if model_names is None:
            self.many2many_relations.clear()
            self.field_setup_dependents.clear()

            # mark all models for setup
            for model_cls in self.models.values():
                model_cls._setup_done__ = False

            # Reset all field metadata in model_graph (inverses, depends,
            # depends_context, computed).  They'll be rebuilt below and
            # lazily via cached_properties.
            self.model_graph.reset_field_metadata()

        else:
            # only mark impacted models for setup and invalidate related fields
            model_names_to_setup = self.descendants(
                model_names, "_inherit", "_inherits"
            )
            for fields in self.many2many_relations.values():
                for pair in list(fields):
                    if pair[0] in model_names_to_setup:
                        fields.discard(pair)

            for model_name in model_names_to_setup:
                self[model_name]._setup_done__ = False

            # recursively mark fields to re-setup
            todo = []
            for model_cls in self.models.values():
                if model_cls._custom:
                    # custom models are going to be reloaded and set up below
                    model_cls._setup_done__ = False
                if model_cls._setup_done__:
                    models_field_depends_done.add(model_cls)
                else:
                    todo.extend(model_cls._fields.values())

            done = set()
            for field in todo:
                if field in done:
                    continue

                model_cls = self[field.model_name]
                if model_cls._setup_done__ and field._base_fields__:
                    # the field has been created by registration._setup() as
                    # Field(_base_fields__=...); restore it to force its setup
                    name = field.name
                    base_fields = field._base_fields__

                    field.__dict__.clear()
                    field.__init__(_base_fields__=base_fields)
                    field._toplevel = True
                    field.__set_name__(model_cls, name)
                    field._setup_done = False

                    models_field_depends_done.discard(model_cls)

                # partial invalidation of field_depends[_context]
                self.field_depends.pop(field, None)
                self.field_depends_context.pop(field, None)

                done.add(field)
                todo.extend(self.field_setup_dependents.pop(field, ()))

        self.many2one_company_dependents.clear()

        registration.setup_model_classes(env)

        # determine field_depends and field_depends_context
        for model_cls in self.models.values():
            if model_cls in models_field_depends_done:
                continue
            model = model_cls(env, (), ())
            for field in model._fields.values():
                depends, depends_context = field.get_depends(model)
                self.field_depends[field] = tuple(depends)
                self.field_depends_context[field] = tuple(depends_context)

        # clean again in case cached by another ongoing readonly request
        reset_cached_properties(self)

        # reinstall registry hooks (only on a fully loaded registry, not one
        # still loading)
        if self.ready:
            for model in env.values():
                model._register_hook()
            env.flush_all()

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

    @functools.cached_property
    def field_fk_refs(self) -> dict[str, list[tuple]]:
        """Return a mapping from model_name to the Many2one fields on other
        models that reference it via a real foreign key, together with their
        ``ondelete`` policy.

        ``{target_model: [(m2o_field, ondelete), ...]}``

        Company-dependent fields are excluded (JSONB, no PG FK constraint).
        Used by :meth:`~odoo.orm.models.mixins.crud.CrudMixin.unlink` for
        targeted cache invalidation after DELETE.
        """
        refs: dict[str, list[tuple]] = defaultdict(list)
        for Model in self.models.values():
            if Model._abstract:
                continue
            for field in Model._fields.values():
                if (
                    field.type == "many2one"
                    and field.is_column
                    and not field.company_dependent
                ):
                    refs[field.comodel_name].append(
                        (field, field.ondelete or "set null")
                    )
        return dict(refs)

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
        # so stale caches there would feed it bad data; ``field_fk_refs`` isn't
        # touched by ``model_graph.discard_fields`` and would otherwise keep the
        # discarded fields.
        for _prop in ("_field_triggers", "field_inverses", "field_computed", "field_fk_refs"):
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

        return self.model_graph._triggers

    def is_modifying_relations(self, field: Field) -> bool:
        """Return whether ``field`` has dependent fields on some records, and
        that modifying ``field`` might change the dependent records.

        Delegates to ``model_graph``.
        """
        self._field_triggers  # noqa: B018 — ensure trigger data is computed
        return self.model_graph.is_modifying_relations(field)

    def post_init(self, func: Callable, *args, **kwargs) -> None:
        """Register a function to call at the end of :meth:`~.init_models`."""
        self._post_init_queue.append(partial(func, *args, **kwargs))

    def post_constraint(
        self, cr: BaseCursor, func: Callable[[BaseCursor], None], key
    ) -> None:
        """Call the given function, and delay it if it fails during an upgrade."""
        try:
            if key not in self._constraint_queue:
                # skip if already queued: module A may fail to apply a constraint
                # and module B (inheriting A) reapply it successfully; running
                # the queued one again at end of cycle would fail on the
                # already-existing constraint.
                with cr.savepoint(flush=False):
                    func(cr)
        except Exception as e:
            if self._is_install:
                _schema.error(*e.args)
            else:
                _schema.info(*e.args)
                self._constraint_queue[key] = func

    def finalize_constraints(self, cr: Cursor) -> None:
        """Call the delayed functions from above."""
        for func in self._constraint_queue.values():
            try:
                with cr.savepoint(flush=False):
                    func(cr)
            except Exception as e:
                # warn only, this is not a deployment showstopper, and
                # can sometimes be a transient error
                _schema.warning(*e.args)
        self._constraint_queue.clear()

    def init_models(
        self,
        cr: Cursor,
        model_names: Iterable[str],
        context: dict[str, typing.Any],
        install: bool = True,
    ):
        """Initialize a list of models (given by their name). Call methods
        ``_auto_init`` and ``init`` on each model to create or update the
        database tables supporting the models.

        The ``context`` may contain the following items:
         - ``module``: the name of the module being installed/updated, if any;
         - ``update_custom_fields``: whether custom fields should be updated.
        """
        if not model_names:
            return

        if "module" in context:
            _logger.info(
                "module %s: creating or updating database tables",
                context["module"],
            )
        elif context.get("models_to_check", False):
            _logger.info("verifying fields for every extended model")

        from .environment import Environment

        env = Environment(cr, SUPERUSER_ID, context)
        models = [env[model_name] for model_name in model_names]

        try:
            self._post_init_queue: deque[Callable] = deque()
            # (table1, column1) -> (table2, column2, ondelete, model, module)
            self._foreign_keys: dict[
                tuple[str, str], tuple[str, str, str, BaseModel, str]
            ] = {}
            self._is_install: bool = install

            for model in models:
                model._auto_init()
                model.init()

            env["ir.model"]._reflect_models(model_names)
            env["ir.model.fields"]._reflect_fields(model_names)
            env["ir.model.fields.selection"]._reflect_selections(model_names)
            env["ir.model.constraint"]._reflect_constraints(model_names)
            env["ir.model.inherit"]._reflect_inherits(model_names)

            self._ordinary_tables = None

            while self._post_init_queue:
                func = self._post_init_queue.popleft()
                func()

            self.check_indexes(cr, model_names)
            self.check_foreign_keys(cr)

            env.flush_all()

            # make sure all tables are present
            self.check_tables_exist(cr)

        finally:
            del self._post_init_queue
            del self._foreign_keys
            del self._is_install

    def check_null_constraints(self, cr: Cursor) -> None:
        """Check that all not-null constraints are set."""
        cr.execute("""
            SELECT c.relname, a.attname
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = current_schema
            AND a.attnotnull = true
            AND a.attnum > 0
            AND a.attname != 'id';
        """)
        not_null_columns = set(cr.fetchall())

        self.not_null_fields.clear()
        for Model in self.models.values():
            if Model._auto and not Model._abstract:
                for field_name, field in Model._fields.items():
                    if field_name == "id":
                        self.not_null_fields.add(field)
                        continue
                    if field.column_type and field.store and field.required:
                        if (Model._table, field_name) in not_null_columns:
                            self.not_null_fields.add(field)
                        else:
                            _schema.warning("Missing not-null constraint on %s", field)

    def check_indexes(self, cr: Cursor, model_names: Iterable[str]) -> None:
        """Create or drop column indexes for the given models."""

        expected = [
            (sql.make_index_name(Model._table, field.name), Model._table, field)
            for model_name in model_names
            for Model in [self.models[model_name]]
            if Model._auto and not Model._abstract
            for field in Model._fields.values()
            if field.column_type and field.store
        ]
        if not expected:
            return

        # retrieve existing indexes with their corresponding table
        cr.execute(
            "SELECT indexname, tablename FROM pg_indexes WHERE indexname = ANY(%s)",
            [[row[0] for row in expected]],
        )
        existing = dict(cr.fetchall())

        for indexname, tablename, field in expected:
            index = field.index
            assert index in (
                "btree",
                "btree_not_null",
                "trigram",
                True,
                False,
                None,
            )
            if index and indexname not in existing:
                if index == "trigram" and not self.has_trigram:
                    # Ignore if trigram index is not supported
                    continue
                if field.translate and index != "trigram":
                    _schema.warning(
                        f"Index attribute on {field!r} ignored, only trigram index is supported for translated fields"
                    )
                    continue

                column_expression = f'"{field.name}"'
                if index == "trigram":
                    if field.translate:
                        column_expression = f"""(jsonb_path_query_array({column_expression}, '$.*')::text)"""
                    # add `unaccent` to the trigram index only because the
                    # trigram indexes are mainly used for (=)ilike search and
                    # unaccent is added only in these cases when searching
                    from odoo.modules.db import FunctionStatus

                    if self.has_unaccent == FunctionStatus.INDEXABLE:
                        column_expression = self.unaccent(column_expression)
                    elif self.has_unaccent:
                        warnings.warn(
                            "PostgreSQL function 'unaccent' is present but not immutable, "
                            "therefore trigram indexes may not be effective.",
                            stacklevel=1,
                        )
                    expression = f"{column_expression} gin_trgm_ops"
                    method = "gin"
                    where = ""
                elif index == "btree_not_null" and field.company_dependent:
                    # company dependent condition will use extra
                    # `AND col IS NOT NULL` to use the index.
                    expression = f"({column_expression} IS NOT NULL)"
                    method = "btree"
                    where = f"{column_expression} IS NOT NULL"
                else:  # index in ['btree', 'btree_not_null', True]
                    expression = f"{column_expression}"
                    method = "btree"
                    where = (
                        f"{column_expression} IS NOT NULL"
                        if index == "btree_not_null"
                        else ""
                    )
                try:
                    with cr.savepoint(flush=False):
                        sql.create_index(
                            cr,
                            indexname,
                            tablename,
                            [expression],
                            method,
                            where,
                        )
                except psycopg.OperationalError:
                    _schema.error("Unable to add index %r for %s", indexname, self)

            elif not index and tablename == existing.get(indexname):
                _schema.info(
                    "Keep unexpected index %s on table %s", indexname, tablename
                )

    def add_foreign_key(
        self,
        table1: str,
        column1: str,
        table2: str,
        column2: str,
        ondelete: str,
        model: BaseModel,
        module: str,
        force: bool = True,
    ) -> None:
        """Specify an expected foreign key."""
        key = (table1, column1)
        val = (table2, column2, ondelete, model, module)
        if force:
            self._foreign_keys[key] = val
        else:
            self._foreign_keys.setdefault(key, val)

    def check_foreign_keys(self, cr: Cursor) -> None:
        """Create or update the expected foreign keys."""
        if not self._foreign_keys:
            return

        # determine existing foreign keys on the tables
        tablenames = {table for table, column in self._foreign_keys}
        existing = {
            (table1, column1): (name, table2, column2, deltype)
            for name, table1, column1, table2, column2, deltype in sql.get_fk_constraints_batch(
                cr, tablenames
            )
        }

        # create or update foreign keys
        for key, val in self._foreign_keys.items():
            table1, column1 = key
            table2, column2, ondelete, model, module = val
            deltype = sql._CONFDELTYPES[ondelete.upper()]
            spec = existing.get(key)
            if spec is None:
                sql.add_foreign_key(cr, table1, column1, table2, column2, ondelete)
                conname = sql.get_foreign_keys(
                    cr, table1, column1, table2, column2, ondelete
                )[0]
                model.env["ir.model.constraint"]._reflect_constraint(
                    model, conname, "f", None, module
                )
            elif (spec[1], spec[2], spec[3]) != (table2, column2, deltype):
                sql.drop_constraint(cr, table1, spec[0])
                sql.add_foreign_key(cr, table1, column1, table2, column2, ondelete)
                conname = sql.get_foreign_keys(
                    cr, table1, column1, table2, column2, ondelete
                )[0]
                model.env["ir.model.constraint"]._reflect_constraint(
                    model, conname, "f", None, module
                )

    def check_tables_exist(self, cr: Cursor) -> None:
        """
        Verify that all tables are present and try to initialize those that are missing.
        """
        from .environment import Environment

        env = Environment(cr, SUPERUSER_ID, {})
        table2model = {
            model._table: name
            for name, model in env.registry.items()
            if not model._abstract and not model._table_query
        }
        missing_tables = set(table2model).difference(
            sql.existing_tables(cr, table2model)
        )

        if missing_tables:
            missing = {table2model[table] for table in missing_tables}
            _logger.info("Models have no table: %s.", ", ".join(missing))
            # recreate missing tables
            for name in missing:
                _logger.info("Recreate table of model %s.", name)
                env[name].init()
            env.flush_all()
            # check again, and log errors if tables are still missing
            missing_tables = set(table2model).difference(
                sql.existing_tables(cr, table2model)
            )
            for table in missing_tables:
                _logger.error("Model %s has no table.", table2model[table])

    def clear_cache(self, *cache_names: str) -> None:
        """Clear the caches associated to methods decorated with
        ``tools.ormcache``if cache is in `cache_name` subset."""
        cache_names = cache_names or ("default",)
        # raise (not assert) — under python -O an invalid composite name like
        # "templates.cached_values" would slip through and produce a less
        # helpful KeyError on the ``_CACHES_BY_KEY[cache_name]`` lookup below.
        for cache_name in cache_names:
            if "." in cache_name:
                raise ValueError(
                    f"clear_cache: invalid cache name {cache_name!r} (no dots allowed)"
                )
        for cache_name in cache_names:
            for cache in _CACHES_BY_KEY[cache_name]:
                self.__caches[cache].clear()
            self.cache_invalidated.add(cache_name)

        if _logger.isEnabledFor(logging.DEBUG):
            # debug, not info: would need to minimize invalidation first
            # (mainly in some setUpClass and crons)
            caller_info = format_frame(inspect.currentframe().f_back)  # type: ignore
            _logger.debug(
                "Invalidating %s model caches from %s",
                ",".join(cache_names),
                caller_info,
            )

    def clear_all_caches(self) -> None:
        """Clear the caches associated to methods decorated with
        ``tools.ormcache``.
        """
        for cache_name, caches in _CACHES_BY_KEY.items():
            for cache in caches:
                self.__caches[cache].clear()
            self.cache_invalidated.add(cache_name)

        caller_info = format_frame(inspect.currentframe().f_back)  # type: ignore
        log = _logger.info if self.loaded else _logger.debug
        log("Invalidating all model caches from %s", caller_info)

    def is_an_ordinary_table(self, model: BaseModel) -> bool:
        """Return whether the given model has an ordinary table."""
        if self._ordinary_tables is None:
            cr = model.env.cr
            query = """
                SELECT c.relname
                  FROM pg_class c
                  JOIN pg_namespace n ON (n.oid = c.relnamespace)
                 WHERE c.relname = ANY(%s)
                   AND c.relkind = 'r'
                   AND n.nspname = current_schema
            """
            tables = [m._table for m in self.models.values()]
            cr.execute(query, [tables])
            self._ordinary_tables = {row[0] for row in cr.fetchall()}

        return model._table in self._ordinary_tables

    @property
    def registry_invalidated(self) -> bool:
        """Determine whether the current thread has modified the registry."""
        return getattr(self._invalidation_flags, "registry", False)

    @registry_invalidated.setter
    def registry_invalidated(self, value: bool) -> None:
        self._invalidation_flags.registry = value

    @property
    def cache_invalidated(self) -> set[str]:
        """Determine whether the current thread has modified the cache."""
        try:
            return self._invalidation_flags.cache
        except AttributeError:
            names = self._invalidation_flags.cache = set()
            return names

    def setup_signaling(self) -> None:
        """Setup the inter-process signaling on this registry."""
        with self.cursor() as cr:
            # `orm_signaling_registry` signals registry reload; each
            # `orm_signaling_<cache>` signals cache invalidation.
            signaling_tables = tuple(
                f"orm_signaling_{cache_name}"
                for cache_name in ["registry", *_CACHES_BY_KEY]
            )
            existing_sig_tables = tuple(sql.existing_tables(cr, signaling_tables))
            # insert-only tables, not sequences: sequences don't replicate
            # https://www.postgresql.org/docs/current/logical-replication-restrictions.html
            for table_name in signaling_tables:
                if table_name not in existing_sig_tables:
                    cr.execute(
                        SQL(
                            "CREATE TABLE %s (id SERIAL PRIMARY KEY, date TIMESTAMP DEFAULT now())",
                            SQL.identifier(table_name),
                        )
                    )
                    cr.execute(
                        SQL(
                            "INSERT INTO %s DEFAULT VALUES",
                            SQL.identifier(table_name),
                        )
                    )

            db_registry_sequence, db_cache_sequences = self.get_sequences(cr)
            self.registry_sequence = db_registry_sequence
            self.cache_sequences.update(db_cache_sequences)

            _logger.debug(
                "Multiprocess load registry signaling: [Registry: %s] %s",
                self.registry_sequence,
                " ".join(f"[Cache {k}: {v}]" for k, v in self.cache_sequences.items()),
            )

    def get_sequences(self, cr: BaseCursor) -> tuple[int, dict[str, int]]:
        signaling_tables = tuple(
            f"orm_signaling_{cache_name}"
            for cache_name in ["registry", *_CACHES_BY_KEY]
        )
        signaling_selects = SQL(", ").join(
            [
                SQL("( SELECT max(id) FROM %s)", SQL.identifier(signaling_table))
                for signaling_table in signaling_tables
            ]
        )
        cr.execute(SQL("SELECT %s", signaling_selects))
        row = cr.fetchone()
        assert row is not None, "No result when reading signaling sequences"
        registry_sequence, *cache_sequences_values = row
        cache_sequences = dict(
            zip(_CACHES_BY_KEY, cache_sequences_values, strict=False)
        )
        return registry_sequence, cache_sequences

    def check_signaling(self, cr: BaseCursor | None = None) -> Registry:
        """Check whether the registry has changed, and performs all necessary
        operations to update the registry. Return an up-to-date registry.
        """
        try:
            with (
                nullcontext(cr)
                if cr is not None
                else closing(self.cursor(readonly=True))
            ) as cr:  # noqa: PLR1704 — rebind to the resolved cursor
                assert cr is not None
                db_registry_sequence, db_cache_sequences = self.get_sequences(cr)
                changes = ""
                # Check if the model registry must be reloaded
                if self.registry_sequence != db_registry_sequence:
                    _logger.info(
                        "Reloading the model registry after database signaling."
                    )
                    # another worker changed the schema. this worker's idle
                    # pooled connections hold stale auto-prepared statements
                    # (re-execute fails "cached plan must not change result
                    # type") and stale binary-COPY schema caches (which do NOT
                    # self-heal). drain_all() in load_modules() ran only in the
                    # upgrading worker, so drain here to get fresh connections.
                    from odoo.db import drain_db

                    drain_db(self.db_name)
                    self = Registry.new(self.db_name)
                    self.registry_sequence = db_registry_sequence
                    if _logger.isEnabledFor(logging.DEBUG):
                        changes += f"[Registry - {self.registry_sequence} -> {db_registry_sequence}]"
                # Check if the model caches must be invalidated.
                else:
                    invalidated = []
                    for (
                        cache_name,
                        cache_sequence,
                    ) in self.cache_sequences.items():
                        expected_sequence = db_cache_sequences[cache_name]
                        if cache_sequence != expected_sequence:
                            for cache in _CACHES_BY_KEY[
                                cache_name
                            ]:  # don't call clear_cache to avoid signal loop
                                if cache not in invalidated:
                                    invalidated.append(cache)
                                    self.__caches[cache].clear()
                            self.cache_sequences[cache_name] = expected_sequence
                            if _logger.isEnabledFor(logging.DEBUG):
                                changes += f"[Cache {cache_name} - {cache_sequence} -> {expected_sequence}]"
                    if invalidated:
                        _logger.info(
                            "Invalidating caches after database signaling: %s",
                            sorted(invalidated),
                        )
                if changes:
                    _logger.debug("Multiprocess signaling check: %s", changes)
        except (psycopg.OperationalError, db.PoolError):
            if cr is None:
                # We couldn't open a cursor — database likely unreachable
                # (e.g. dropped). Remove stale registry to prevent repeated hangs.
                type(self).delete(self.db_name)
            raise
        return self

    def signal_changes(self) -> None:
        """Notifies other processes if registry or cache has been invalidated."""
        if not self.ready:
            _logger.warning(
                "Calling signal_changes when registry is not ready is not supported"
            )
            return

        if self.registry_invalidated:
            _logger.info("Registry changed, signaling through the database")
            with self.cursor() as cr:
                cr.execute("INSERT INTO orm_signaling_registry DEFAULT VALUES")
                # if another process updated the registry concurrently this
                # becomes out-of-date, and the next check_signaling() detects it
                # and triggers a reload; otherwise it equals cr.fetchone()[0].
                self.registry_sequence += 1

        # no need to notify cache invalidation in case of registry invalidation,
        # because reloading the registry implies starting with an empty cache
        elif self.cache_invalidated:
            _logger.info(
                "Caches invalidated, signaling through the database: %s",
                sorted(self.cache_invalidated),
            )
            with self.cursor() as cr:
                for cache_name in self.cache_invalidated:
                    cr.execute(
                        SQL(
                            "INSERT INTO %s DEFAULT VALUES",
                            SQL.identifier(f"orm_signaling_{cache_name}"),
                        )
                    )
                    # if another process updated the cache concurrently this
                    # becomes out-of-date, and the next check_signaling() detects
                    # it and invalidates; otherwise it equals cr.fetchone()[0].
                    self.cache_sequences[cache_name] += 1

        self.registry_invalidated = False
        self.cache_invalidated.clear()

    def reset_changes(self) -> None:
        """Reset the registry and cancel all invalidations."""
        if self.registry_invalidated:
            with closing(self.cursor()) as cr:
                self._setup_models__(cr)
                self.registry_invalidated = False
        if self.cache_invalidated:
            for cache_name in self.cache_invalidated:
                for cache in _CACHES_BY_KEY[cache_name]:
                    self.__caches[cache].clear()
            self.cache_invalidated.clear()

    def cursor(self, /, readonly: bool = False) -> BaseCursor:
        """Return a new cursor for the database. The cursor itself may be used
        as a context manager to commit/rollback and close automatically.

        :param readonly: Attempt to acquire a cursor on a replica database.
            Acquire a read/write cursor on the primary database in case no
            replica exists or that no readonly cursor could be acquired.
        """
        if readonly and self._db_readonly is not None:
            if (
                self._db_readonly_failed_time is None
                or time.monotonic()
                > self._db_readonly_failed_time + _REPLICA_RETRY_TIME
            ):
                try:
                    cr = self._db_readonly.cursor()
                    self._db_readonly_failed_time = None
                    # replica succeeded — clear any "ro->rw" cursor_mode left by
                    # an earlier fallback in this thread, else it keeps reporting
                    # the resolved fallback state.
                    threading.current_thread().cursor_mode = "ro"
                    return cr
                except (psycopg.OperationalError, db.PoolError):
                    self._db_readonly_failed_time = time.monotonic()
                    _logger.warning(
                        "Failed to open a readonly cursor, falling back to read-write cursor for %dmin %dsec",
                        *divmod(_REPLICA_RETRY_TIME, 60),
                    )
            threading.current_thread().cursor_mode = "ro->rw"
        return self._db.cursor()


class DummyRLock:
    """Dummy reentrant lock, to be used while running rpc and js tests"""

    def acquire(self) -> None:
        pass

    def release(self) -> None:
        pass

    def __enter__(self) -> None:
        self.acquire()

    def __exit__(
        self,
        type: type[BaseException] | None,
        value: BaseException | None,
        traceback: typing.Any,
    ) -> None:
        self.release()


# TriggerTree has been moved to odoo.orm.components.model_graph.
# It is imported at the top of this module and re-exported via __init__.py
# for backward compatibility.
