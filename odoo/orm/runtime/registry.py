"""Models registries."""

import inspect
import logging
import threading
import time
import typing
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
    remove_accents,
    sql,
)
from odoo.tools.misc import Collector, format_frame

from .. import registration
from ..components.model_graph import ModelGraph
from ..primitives import SUPERUSER_ID
from ._registry_fields import _RegistryFieldsMixin
from ._registry_schema import _RegistrySchemaMixin

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

# Inter-process signaling tables: ``orm_signaling_registry`` signals a full
# registry reload; each ``orm_signaling_<cache>`` signals invalidation of the
# corresponding cache group (see setup_signaling / get_sequences).
_SIGNALING_TABLES = tuple(
    f"orm_signaling_{cache_name}" for cache_name in ["registry", *_CACHES_BY_KEY]
)


class _RegistryCaches:
    """Owns a registry's ormcache LRU stores and their bulk-clear logic.

    A :class:`Registry` holds one of these as ``registry._caches`` (composition,
    not inheritance). It encapsulates the ``{cache_name: LRU}`` storage and the
    composite-key clearing (``clear_group`` / ``clear_all``); the thread-local
    dirty flags, inter-process sequences and signaling stay on ``Registry``.

    The ormcache decorator (:mod:`odoo.tools.cache`) reads the backing LRU for a
    cache name; ``Registry`` exposes it through the legacy name-mangled
    ``_Registry__caches`` property (a thin bridge over ``self.lrus``).
    """

    __slots__ = ("lrus",)

    def __init__(self) -> None:
        self.lrus: dict[str, LRU] = {
            cache_name: LRU(cache_size)
            for cache_name, cache_size in _REGISTRY_CACHES.items()
        }

    def clear_group(self, cache_name: str) -> None:
        """Clear every LRU backing the composite cache key ``cache_name``."""
        for cache in _CACHES_BY_KEY[cache_name]:
            self.lrus[cache].clear()

    def clear_all(self) -> None:
        """Clear every LRU store (used on registry reload / model setup)."""
        for lru in self.lrus.values():
            lru.clear()


def _unaccent(
    x: SQL | str | psycopg_sql.Composable,
) -> SQL | str | psycopg_sql.Composed:
    if isinstance(x, SQL):
        return SQL("unaccent(%s)", x)
    if isinstance(x, psycopg_sql.Composable):
        return psycopg_sql.SQL("unaccent({})").format(x)
    return f"unaccent({x})"


class Registry(
    _RegistryFieldsMixin,
    _RegistrySchemaMixin,
    Mapping[str, type["BaseModel"]],
):
    """Model registry for a database: a mapping of model names to model classes.

    One registry instance per database.
    """

    _lock: threading.RLock | DummyRLock = threading.RLock()

    # Import-time default; resized from ``config['registry_lru_size']`` in
    # ``new()`` once config is available.
    registries = LRU[str, "Registry"](42)
    """A mapping from database names to registries."""

    def __new__(cls, db_name: str):
        """Return the registry for the given database name."""
        # raise (not assert): the contract must hold under python -O, matching
        # the fork's other converted contract checks in this module.
        if not db_name:
            raise ValueError("Missing database name")
        # Lock-free fast path: `_lock` is class-global, so taking it serializes
        # requests across ALL databases — a request for db A would wait behind a
        # full registry build for db B. LRU reads are documented lock-free, and
        # `ready` only becomes True after `new()` finished building (registries
        # are published *before* loading, with ready=False, so an in-flight
        # build never short-circuits here and still waits on the locked path).
        reg = cls.registries.get(db_name)
        if reg is not None and reg.ready:
            return reg
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
        # Refuse cluster infrastructure outright: with update_module a registry
        # build would bootstrap Odoo tables into the database (load_modules
        # initializes), and even a plain load opens connections against it and
        # caches a broken registry. Every consumer (HTTP dispatch, RPC
        # `execute_kw(db, ...)` — which bypasses db_filter —, CLI, shell) funnels
        # through here, making this the root guard; the CLI and http layers
        # refuse earlier with friendlier errors.
        # Imported lazily to avoid an orm<->service import cycle.
        from odoo.service._db_helpers import SYSTEM_DBS

        if db_name in SYSTEM_DBS or db_name == config["db_template"]:
            raise ValueError(
                f"Refusing to build a registry over system or template "
                f"database {db_name!r}"
            )
        t0 = time.time()
        # Sync the registry-cache capacity from config: the class-level LRU is
        # sized at import time (before config is parsed), so honour an operator
        # override here rather than hardcoding how many databases stay cached
        # (beyond the limit, a live registry is evicted and fully reloaded).
        lru_size = config.get("registry_lru_size")
        if lru_size and cls.registries.count != lru_size:
            cls.registries.count = lru_size
        registry: Registry = object.__new__(cls)
        registry.init(db_name)
        registry.new = registry.init = registry.registries = None  # type: ignore[assignment, method-assign]
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
                # aliased (like init() below): a bare `db` would shadow the
                # module-level `from odoo import db` used elsewhere in the class
                from odoo.modules import db as modules_db

                if modules_db.is_initialized(cr):
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
            # membership-guarded delete: a NESTED Registry.new (uninstall reload
            # path, odoo/modules/loading.py) that failed already removed the key
            # on its way out; an unguarded `del` here would then raise KeyError
            # and mask the real exception (left only in __context__). `delete`
            # is @locked but the RLock is reentrant.
            cls.delete(db_name)
            raise

        del registry._reinit_modules

        # load_modules() above may replace the registry by calling new() again
        # (when modules must be uninstalled), so re-read it.
        registry = cls.registries[db_name]  # pylint: disable=unsubscriptable-object

        registry._init = False
        registry.ready = True
        registry.registry_invalidated = bool(update_module)

        # Build the field-dependency caches now, single-threaded under the setup
        # lock (`new` is @locked), instead of lazily on first request. These
        # cached_property builds mutate the shared model_graph (reset_triggers →
        # add_trigger loop → freeze); since cached_property has no internal lock
        # since Py 3.12, leaving them lazy lets the first concurrent request
        # threads double-compute and race the shared graph — a reliable
        # "dictionary changed size during iteration" on a free-threaded build.
        # Accessing `_field_triggers` also forces field_inverses/field_computed
        # and ModelGraph.freeze(). Mirrors ModelTestEnv's own setup.
        registry._field_triggers  # noqa: B018 — eager build for thread-safety

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
        self._caches = _RegistryCaches()

        # update context during loading modules
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

        self.unaccent = _unaccent if self.has_unaccent else lambda x: x  # type: ignore[return-value]
        self.unaccent_python = remove_accents if self.has_unaccent else lambda x: x

    @classmethod
    @locked
    def delete(cls, db_name: str) -> None:
        """Delete the registry linked to a given database."""
        if db_name in cls.registries:  # pylint: disable=unsupported-membership-test
            del cls.registries[db_name]  # pylint: disable=unsupported-delete-operation
        # Drop the ormcache stat counters for this db so they do not accumulate
        # across create/drop cycles.
        from odoo.tools.cache import prune_counters

        prune_counters(db_name)

    @classmethod
    @locked
    def delete_all(cls):
        """Delete all the registries."""
        cls.registries.clear()

    # A registry is a per-database singleton, so equality is identity. Override
    # the content-based ``Mapping.__eq__``/``__ne__`` (which would materialise
    # ``dict(self)`` over every model -- O(N) -- and leave the registry
    # unhashable because ``Mapping.__hash__ is None``). Identity semantics make
    # ``registry is/is not other`` and ``!=`` cheap and keep the object usable as
    # a dict/set key. (Cf. ``Environment``, which does the same.)
    __eq__ = object.__eq__
    __ne__ = object.__ne__
    __hash__ = object.__hash__

    # Mapping abstract methods; the mixin provides keys, items, values, get.
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
        # raise (not assert): under python -O a bad kind would slip through to
        # attrgetter() on a nonexistent ``*_children`` attribute deep in the BFS.
        if not all(kind in ("_inherit", "_inherits") for kind in kinds):
            raise ValueError(
                f"descendants: kinds must be '_inherit'/'_inherits', got {kinds!r}"
            )
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

        model_defs = models.MetaModel._module_to_models__.get(module.name, [])
        if not model_defs:
            # nothing to register: leave the caches alone (a module without
            # Python models cannot invalidate any model-derived state, and the
            # cleared caches would be rebuilt from scratch — O(all fields) for
            # the dependency triggers — during this module's data loading)
            return []

        # clear cache to ensure consistency, but do not signal it
        self._caches.clear_all()

        reset_cached_properties(self)
        self.model_graph.clear_caches()

        # Instantiate registered classes (via the MetaModel automatic discovery
        # or via explicit constructor call), and add them to the pool.
        model_names = []
        for model_def in model_defs:
            # models register themselves in self.models
            model_cls = registration.add_to_registry(self, model_def)
            model_names.append(model_cls._name)

        return model_names

    @locked
    def _setup_models__(
        self,
        cr: BaseCursor,
        model_names: Iterable[str] | None = None,
        *,
        skip_if_clean: bool = False,
    ) -> None:
        """Perform the setup of models.
        This must be called after loading modules and before using the ORM.

        When given ``model_names``, it performs an incremental setup: only the
        models impacted by the given ``model_names`` and all the already-marked
        models will be set up. Otherwise, all models are set up.

        ``skip_if_clean`` lets a caller declare that this call is a
        synchronization point only: if every model is already set up (and no
        custom model exists), the call returns without touching the registry.
        Do not pass it when the database definition of manual models/fields may
        have changed since the last setup — ``ir.model.create`` relies on an
        incremental call with an empty ``model_names`` to (re)load custom
        models, and the fast path would skip exactly that reload.
        """
        from .environment import Environment

        # Fast path (opt-in): an incremental call with nothing to set up.
        # Module loading calls this once per module (twice for upgraded ones),
        # and most of those calls find every model already set up.  Proceeding
        # anyway would clear every ormcache, cached property and model-graph
        # cache below, forcing an O(all fields) rebuild of the dependency
        # triggers on the next flush — per module, that dominates `-u` runs.
        # Registries containing custom models keep the conservative path:
        # incremental setups unconditionally reload custom models (their
        # manual-field definitions live in the database and may have changed).
        if (
            skip_if_clean
            and model_names is not None
            and not model_names
            and all(
                model_cls._setup_done__ and not model_cls._custom
                for model_cls in self.models.values()
            )
        ):
            return

        env = Environment(cr, SUPERUSER_ID, {})
        env.invalidate_all()

        # uninstall registry hooks (only on a fully loaded registry, not one
        # still loading)
        if self.ready:
            for model in env.values():
                model._unregister_hook()

        # clear cache to ensure consistency, but do not signal it
        self._caches.clear_all()

        # Open the trigger-graph invalidation window BEFORE tearing anything
        # down: from here until end_invalidation() (just before the eager
        # rebuild at the end), any reader-triggered _field_triggers rebuild —
        # whether it started before this point or starts mid-teardown against
        # half-set-up models — loses the publication race (epoch/barrier check
        # in ModelGraph.set_triggers) instead of clobbering the graph with
        # stale or garbage triggers after our own rebuild.
        self.model_graph.begin_invalidation()

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

                elif model_cls._setup_done__ and field.related and field.manual:
                    # manually-added related field (e.g. added via Studio) that has
                    # no _base_fields__ so it cannot be partially reset; mark the
                    # whole model for full re-setup so that setup_model_classes()
                    # recreates the field pointing to the updated target field
                    model_cls._setup_done__ = False
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

        # Close the invalidation window opened at the top of the teardown: the
        # models are fully set up again, so trigger rebuilds are trustworthy
        # from here on. end_invalidation bumps the epoch once more, so any
        # rebuild that started DURING the teardown (against half-set-up
        # models) stays refused forever; only builds starting after this point
        # — ours below, or Registry.new's eager build on initial load — can
        # publish. Must run on the not-ready path too, else the initial-load
        # eager build in Registry.new would be refused by the barrier.
        self.model_graph.end_invalidation()

        # reinstall registry hooks (only on a fully loaded registry, not one
        # still loading)
        if self.ready:
            for model in env.values():
                model._register_hook()
            # Eagerly rebuild the field-dependency caches under the setup lock
            # (this method is @locked) before releasing it. On a ready registry
            # -- an incremental setup from a custom-field add or reset_changes --
            # other request threads may read _field_triggers concurrently, and
            # cached_property has no internal lock since Py 3.12, so a lazy build
            # would let them double-compute and race the shared model_graph. This
            # mirrors the eager build in Registry.new (which covers initial load,
            # where self.ready is still False and no request threads exist yet).
            # Pop the cached_property first: a refused mid-teardown reader may
            # have re-primed it with the previous snapshot, and the eager
            # access below must recompute, not return that.
            self.__dict__.pop("_field_triggers", None)
            self._field_triggers  # noqa: B018 — eager build for thread-safety
            env.flush_all()

    def post_init(self, func: Callable, *args, **kwargs) -> None:
        """Register a function to call at the end of :meth:`~.init_models`."""
        self._post_init_queue.append(partial(func, *args, **kwargs))

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

    def _clear_cache_group(self, cache_name: str) -> None:
        """Clear every ormcache grouped under the composite ``cache_name``.

        The single place that maps a composite key to its underlying caches and
        clears them; callers layer their own invalidation bookkeeping on top.
        ``check_signaling`` does not use this — it must skip caches it already
        cleared this pass (see there).
        """
        self._caches.clear_group(cache_name)

    @property
    def __caches(self) -> dict[str, LRU]:
        """Legacy bridge: the raw ``{cache_name: LRU}`` mapping.

        Exposed as the name-mangled ``registry._Registry__caches`` that the
        ormcache decorator (:mod:`odoo.tools.cache`) and a few tests read
        directly. The storage itself lives on :class:`_RegistryCaches`
        (``self._caches``); prefer ``registry._caches.lrus`` in new code.
        """
        return self._caches.lrus

    def clear_cache(self, *cache_names: str) -> None:
        """Clear the ``tools.ormcache`` caches in the given ``cache_names`` subset."""
        cache_names = cache_names or ("default",)
        # raise (not assert) — under python -O an invalid name (a typo, or a
        # composite sub-cache like "templates.cached_values" which is not a
        # clearable group) would slip through and produce a less helpful
        # KeyError on the ``_CACHES_BY_KEY[cache_name]`` lookup mid-loop.
        # Validate everything up front so a bad name clears nothing.
        for cache_name in cache_names:
            if cache_name not in _CACHES_BY_KEY:
                raise ValueError(
                    f"clear_cache: invalid cache name {cache_name!r} — only "
                    f"composite group names can be cleared (sub-cache names "
                    f"like 'templates.cached_values' cannot); valid names: "
                    f"{', '.join(sorted(_CACHES_BY_KEY))}"
                )
        for cache_name in cache_names:
            self._clear_cache_group(cache_name)
            self.cache_invalidated.add(cache_name)

        if _logger.isEnabledFor(logging.DEBUG):
            # debug, not info: would need to minimize invalidation first
            # (mainly in some setUpClass and crons)
            caller_info = format_frame(inspect.currentframe().f_back)  # type: ignore[arg-type, union-attr]
            _logger.debug(
                "Invalidating %s model caches from %s",
                ",".join(cache_names),
                caller_info,
            )

    def clear_all_caches(self) -> None:
        """Clear all caches associated to ``tools.ormcache``-decorated methods."""
        for cache_name in _CACHES_BY_KEY:
            self._clear_cache_group(cache_name)
            self.cache_invalidated.add(cache_name)

        caller_info = format_frame(inspect.currentframe().f_back)  # type: ignore[arg-type, union-attr]
        log = _logger.info if self.loaded else _logger.debug
        log("Invalidating all model caches from %s", caller_info)

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
            existing_sig_tables = tuple(sql.existing_tables(cr, _SIGNALING_TABLES))
            # insert-only tables, not sequences: sequences don't replicate
            # https://www.postgresql.org/docs/current/logical-replication-restrictions.html
            for table_name in _SIGNALING_TABLES:
                if table_name not in existing_sig_tables:
                    # IF NOT EXISTS: on a fresh database whose template lacks
                    # the tables (e.g. right after a restore, which templates
                    # from template0), two workers race this — both read
                    # existing_tables above before either commits, and without
                    # the guard the loser's CREATE raises DuplicateTable and
                    # its whole registry build fails.  Both workers then seed;
                    # a double seed is harmless: consumers only ever read
                    # max(id) (get_sequences) and compare it strictly
                    # monotonically against a baseline captured below, so a
                    # baseline of 2 instead of 1 costs at worst one spurious
                    # reload on the worker whose snapshot missed the other's
                    # row.  The existing_tables pre-check still matters: it
                    # keeps every LATER registry build from re-seeding, which
                    # would signal a fake change to all other workers.
                    cr.execute(
                        SQL(
                            "CREATE TABLE IF NOT EXISTS %s (id SERIAL PRIMARY KEY, date TIMESTAMP DEFAULT now())",
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
        signaling_selects = SQL(", ").join(
            [
                SQL("( SELECT max(id) FROM %s)", SQL.identifier(signaling_table))
                for signaling_table in _SIGNALING_TABLES
            ]
        )
        cr.execute(SQL("SELECT %s", signaling_selects))
        row = cr.fetchone()
        # raise (not assert): must hold under python -O.
        if row is None:
            raise RuntimeError("No result when reading signaling sequences")
        registry_sequence, *cache_sequences_values = row
        # strict: the SELECT is built from _SIGNALING_TABLES = registry +
        # _CACHES_BY_KEY, so after splitting off registry_sequence both sides
        # have len(_CACHES_BY_KEY); if the constants ever drift apart this
        # raises immediately instead of silently dropping a cache group.
        cache_sequences = dict(zip(_CACHES_BY_KEY, cache_sequences_values, strict=True))
        return registry_sequence, cache_sequences

    def check_signaling(self, cr: BaseCursor | None = None) -> Registry:
        """Check whether the registry has changed, and performs all necessary
        operations to update the registry. Return an up-to-date registry.
        """
        # Captured BEFORE the with-statement resolves the cursor: the dead-DB
        # cleanup in the OperationalError handler below must know whether WE
        # opened the cursor, and testing the parameter after a rebinding
        # ``as cr`` would never see None again (the historical bug: a mid-query
        # connection death on a self-opened cursor skipped the cleanup, leaving
        # the stale registry cached — exactly the repeated hangs the handler
        # exists to prevent).
        own_cursor = cr is None
        try:
            with (
                nullcontext(cr)
                if cr is not None
                else closing(self.cursor(readonly=True))
            ) as sig_cr:
                db_registry_sequence, db_cache_sequences = self.get_sequences(sig_cr)
                changes = ""
                # Comparisons below are strictly monotonic (`>`), not `!=`: with
                # db_replica_host configured this cursor may read a LAGGING
                # replica, while signal_changes() optimistically bumped the
                # local sequences right after writing the primary. A db value
                # *smaller* than the local one therefore means replication lag,
                # not a change — reloading (or regressing a stored sequence to
                # the stale value) would trigger spurious full reloads / cache
                # clears on every request until the replica catches up.
                #
                # Check if the model registry must be reloaded
                if db_registry_sequence > self.registry_sequence:
                    _logger.info(
                        "Reloading the model registry after database signaling."
                    )
                    old_sequence = self.registry_sequence
                    # Another thread of this process may have finished the
                    # rebuild already: Registry.new() is @locked and publishes
                    # the fresh registry in `registries` before returning. If a
                    # published registry is already at least as new as the db
                    # read, adopt it instead of paying a redundant full rebuild.
                    published = Registry.registries.get(self.db_name)
                    if (
                        published is not None
                        and published is not self
                        and published.ready
                        and published.registry_sequence >= db_registry_sequence
                    ):
                        self = published
                    else:
                        # another worker changed the schema. this worker's idle
                        # pooled connections hold stale auto-prepared statements
                        # (re-execute fails "cached plan must not change result
                        # type") and stale binary-COPY schema caches (which do
                        # NOT self-heal). drain_all() in load_modules() ran only
                        # in the upgrading worker, so drain here to get fresh
                        # connections.
                        from odoo.db import drain_db

                        drain_db(self.db_name)
                        self = Registry.new(self.db_name)
                        # Registry.new() -> setup_signaling() already set
                        # registry_sequence from a fresh DB read, which is at
                        # least as new as the db_registry_sequence read at the
                        # top of this method. Do NOT overwrite it with that
                        # staler value: under a concurrent schema bump landing
                        # during the rebuild it would regress the sequence and
                        # force a redundant reload next request.
                    # Adopt or rebuild, the pool drain (ours above, or the one
                    # run by whoever published the adopted registry) only
                    # recycles IDLE connections: the cursor used for THIS check
                    # is checked out and keeps its stale auto-prepared plans.
                    # Re-executing one raises FeatureNotSupported 0A000 "cached
                    # plan must not change result type" — not OperationalError,
                    # not a retryable sqlstate, so the RPC retry loop turns it
                    # into a 500 (once per statement, on the first request per
                    # worker). Discard them: on a caller-borrowed request
                    # cursor this protects the rest of the request; on our own
                    # cursor it keeps the connection from re-seeding the pool
                    # with stale plans on return (give_back deliberately
                    # preserves prepared statements — odoo/db/lifecycle.py).
                    sig_cr.discard_cached_plans()
                    if _logger.isEnabledFor(logging.DEBUG):
                        changes += (
                            f"[Registry - {old_sequence} -> {self.registry_sequence}]"
                        )
                elif db_registry_sequence < self.registry_sequence:
                    _logger.debug(
                        "Ignoring stale registry signaling read "
                        "(db %s < local %s), likely replica lag",
                        db_registry_sequence,
                        self.registry_sequence,
                    )
                # Check if the model caches must be invalidated.  Runs on
                # whichever registry the branch above produced (kept / adopted
                # / rebuilt), NOT only on the no-reload path: a registry
                # adopted from another thread may itself hold cache sequences
                # older than this db read (its ormcaches went stale AFTER that
                # thread rebuilt it), and skipping the check would serve those
                # stale entries for the whole request. The loop is
                # monotonic-safe (clears/advances only when db > local), so on
                # a freshly rebuilt registry — whose sequences come from an
                # even fresher read in setup_signaling() — it is a no-op.
                invalidated = []
                for (
                    cache_name,
                    cache_sequence,
                ) in self.cache_sequences.items():
                    expected_sequence = db_cache_sequences[cache_name]
                    if expected_sequence > cache_sequence:
                        for cache in _CACHES_BY_KEY[
                            cache_name
                        ]:  # don't call clear_cache to avoid signal loop
                            if cache not in invalidated:
                                invalidated.append(cache)
                                self._caches.lrus[cache].clear()
                        # monotonic: only ever advance the stored sequence;
                        # assigning a smaller (lagging) value would make the
                        # next non-lagging read look like a change and clear
                        # the caches a second time for nothing.
                        self.cache_sequences[cache_name] = expected_sequence
                        if _logger.isEnabledFor(logging.DEBUG):
                            changes += f"[Cache {cache_name} - {cache_sequence} -> {expected_sequence}]"
                    elif expected_sequence < cache_sequence:
                        _logger.debug(
                            "Ignoring stale cache signaling read for %s "
                            "(db %s < local %s), likely replica lag",
                            cache_name,
                            expected_sequence,
                            cache_sequence,
                        )
                if invalidated:
                    _logger.info(
                        "Invalidating caches after database signaling: %s",
                        sorted(invalidated),
                    )
                if changes:
                    _logger.debug("Multiprocess signaling check: %s", changes)
        except db.PoolError:
            # Pool capacity exhausted (all connections in use), NOT a dead DB.
            # Deleting the registry here would turn a transient load spike into a
            # self-inflicted outage: the next request pays a full module reload
            # under the global lock, opening yet more connections. Propagate and
            # let the caller retry once the pool drains.
            raise
        except psycopg.OperationalError:
            if own_cursor:
                # Our own cursor failed with a connection error (not capacity)
                # — at open or mid-query — so the database is likely
                # unreachable (dropped / refused). Remove the stale registry to
                # prevent repeated hangs. A caller-provided cursor is left
                # alone: its failure is the caller's transaction dying, not
                # proof the database is gone.
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
                # optimistic local bump (no read-back): if another process
                # updated the registry concurrently the db value moves further
                # ahead and the next check_signaling() (strictly monotonic,
                # db > local) detects it and triggers a reload; a replica read
                # lagging behind this bump is ignored there, not treated as a
                # change.
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
                    # optimistic local bump (no read-back): if another process
                    # updated the cache concurrently the db value moves further
                    # ahead and the next check_signaling() (strictly monotonic,
                    # db > local) detects it and invalidates; a replica read
                    # lagging behind this bump is ignored there.
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
                self._clear_cache_group(cache_name)
            self.cache_invalidated.clear()

    def cursor(self, /, readonly: bool = False) -> BaseCursor:
        """Return a new cursor for the database. The cursor itself may be used
        as a context manager to commit/rollback and close automatically.

        :param readonly: Attempt to acquire a cursor on a replica database.
            Acquire a read/write cursor on the primary database in case no
            replica exists or that no readonly cursor could be acquired.
        """
        if readonly and self._db_readonly is not None:
            # ``cursor_mode`` is per-REQUEST state: the http layer initializes
            # it (None) on the worker thread at request start and the perf-log
            # filter only ever reads it on threads that carry that state.
            # Threads without the attribute (cron, loader, main) are not
            # serving a request — don't stamp them, or the mark outlives the
            # work that produced it with nothing ever resetting it.
            thread = threading.current_thread()
            in_request = hasattr(thread, "cursor_mode")
            if (
                self._db_readonly_failed_time is None
                or time.monotonic()
                > self._db_readonly_failed_time + _REPLICA_RETRY_TIME
            ):
                try:
                    cr = self._db_readonly.cursor()
                    self._db_readonly_failed_time = None
                    if in_request:
                        # replica succeeded — clear any "ro->rw" cursor_mode
                        # left by an earlier fallback in this thread, else it
                        # keeps reporting the resolved fallback state.
                        thread.cursor_mode = "ro"
                    return cr
                except psycopg.OperationalError, db.PoolError:
                    self._db_readonly_failed_time = time.monotonic()
                    _logger.warning(
                        "Failed to open a readonly cursor, falling back to read-write cursor for %dmin %dsec",
                        *divmod(_REPLICA_RETRY_TIME, 60),
                    )
            if in_request:
                thread.cursor_mode = "ro->rw"
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


# TriggerTree has been moved to odoo.orm.components.model_graph and is
# re-exported via odoo/orm/runtime/__init__.py for backward compatibility.
