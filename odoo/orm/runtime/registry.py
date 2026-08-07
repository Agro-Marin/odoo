import inspect
import logging
import threading
import time
import types
import typing
from collections import defaultdict, deque
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import ExitStack, closing, nullcontext
from functools import partial
from operator import attrgetter

import psycopg
from psycopg import sql as psycopg_sql

from odoo import db
from odoo.db import schema as sql
from odoo.db.breaker import CircuitBreaker
from odoo.db.lag import LAG_SQL, ReplicaLagGate
from odoo.libs import gc
from odoo.libs.func import locked, reset_cached_properties
from odoo.libs.lru import LRU
from odoo.libs.worker_thread import current_worker_thread
from odoo.tools import SQL, OrderedSet, config
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
    "assets.links": 8192,
    "stable": 1024,
    "templates": 1024,
    "routing": 1024,
    "routing.rewrites": 8192,
    "templates.cached_values": 2048,
    "groups": 64,
}

_CACHES_BY_KEY = {
    "default": ("default", "templates.cached_values"),
    "assets": ("assets", "assets.links", "templates.cached_values"),
    "stable": ("stable", "default", "templates.cached_values"),
    "templates": ("templates", "templates.cached_values"),
    "routing": ("routing", "routing.rewrites", "templates.cached_values"),
    "groups": (
        "groups",
        "templates",
        "templates.cached_values",
    ),
}

_REPLICA_RETRY_TIME = 20 * 60
"""Ceiling on the replica breaker's backoff.

Was a flat window: one failure sent every readonly request to the primary for
the full 20 minutes, with nothing re-checking, so a transient blip cost 20
minutes of primary load and recovery was waited out rather than detected.  It is
now the *maximum* a doubling backoff reaches, so the worst case is unchanged
while a blip recovers in about a second.
"""

_SIGNALING_TABLES = tuple(
    f"orm_signaling_{cache_name}" for cache_name in ["registry", *_CACHES_BY_KEY]
)

_ASSERTION_REPORTS: dict[str, typing.Any] = {}
"""``{db_name: OdooTestResult}`` — the test report belongs to a database, not to
a :class:`Registry` instance.

``odoo.service.lifecycle.preload_registries`` derives the ``odoo-bin
--test-enable`` exit code from ``registry._assertion_report.wasSuccessful()`` on
whichever registry is published in :attr:`Registry.registries`.  Per-instance,
any test that reloads the registry (``Registry.new``, as
``base/tests/test_uninstall.py`` does) published an empty report and discarded
every failure recorded before it, so the run logged its failures and still
exited 0.  Verified by A/B on identical databases: exit 0 per-instance, exit 1
per-database, same one failing test."""


def _get_assertion_report(db_name: str) -> typing.Any:
    if not config["test_enable"]:
        return None
    from odoo.tests.result import OdooTestResult

    report = _ASSERTION_REPORTS.get(db_name)
    if report is None:
        report = _ASSERTION_REPORTS[db_name] = OdooTestResult()
    return report


class _RegistryCaches:
    __slots__ = ("lrus",)

    def __init__(self) -> None:
        self.lrus: dict[str, LRU] = {
            cache_name: LRU(cache_size)
            for cache_name, cache_size in _REGISTRY_CACHES.items()
        }

    def clear_group(self, cache_name: str) -> None:
        for cache in _CACHES_BY_KEY[cache_name]:
            self.lrus[cache].clear()

    def clear_all(self) -> None:
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


_UNACCENT_PROBE_RANGES = ((0x80, 0x3000), (0xFB00, 0xFB50), (0xFF00, 0xFF70))


class _UnaccentTables:
    by_db: dict[str, dict[int, str]] = {}


def _get_unaccent_table(cr: BaseCursor, db_name: str) -> dict[int, str]:
    table = _UnaccentTables.by_db.get(db_name)
    if table is None:
        chars = [chr(c) for lo, hi in _UNACCENT_PROBE_RANGES for c in range(lo, hi)]
        cr.execute(
            "SELECT c AS source, unaccent(c) AS folded FROM unnest(%s::text[]) AS c",
            (chars,),
        )
        table = {
            ord(row["source"]): row["folded"]
            for row in cr.dictfetchall()
            if row["folded"] != row["source"]
        }
        _UnaccentTables.by_db[db_name] = table
    return table


def _identity(x: typing.Any) -> typing.Any:
    return x


def _unaccent_python(x: str, table: dict[int, str]) -> str:
    return x.translate(table)


class Registry(
    _RegistryFieldsMixin,
    _RegistrySchemaMixin,
    Mapping[str, type["BaseModel"]],
):
    _lock: threading.RLock | DummyRLock = threading.RLock()

    registries = LRU[str, "Registry"](42)
    """A mapping from database names to registries."""

    def __new__(cls, db_name: str):
        if not db_name:
            raise ValueError("Missing database name")
        reg = cls.registries.get(db_name)
        if reg is not None and reg.ready:
            return reg
        with cls._lock:
            try:
                return cls.registries[db_name]
            except KeyError:
                return cls.new(db_name)

    _init: bool
    ready: bool
    loaded: bool
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
        from odoo.service._db_helpers import SYSTEM_DBS

        if db_name in SYSTEM_DBS or db_name == config["db_template"]:
            raise ValueError(
                f"Refusing to build a registry over system or template "
                f"database {db_name!r}"
            )
        t0 = time.time()
        lru_size = config.get("registry_lru_size")
        if lru_size and cls.registries.count != lru_size:
            cls.registries.count = lru_size
        registry: Registry = object.__new__(cls)
        registry.init(db_name)
        registry.new = registry.init = registry.registries = None
        first_registry = not cls.registries

        cls.delete(db_name)
        cls.registries[db_name] = registry
        try:
            registry.setup_signaling()
            with registry.cursor() as cr:
                from odoo.modules import db as modules_db

                if modules_db.is_initialized(cr):
                    cr.execute(
                        "DELETE FROM ir_config_parameter WHERE key='base.partially_updated_database'"
                    )
                    if cr.rowcount:
                        update_module = True
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
            cls.delete(db_name)
            raise

        del registry._reinit_modules

        registry = cls.registries[db_name]

        registry._init = False
        registry.ready = True
        registry.registry_invalidated = bool(update_module)

        registry._ensure_field_triggers()

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

        self.models: dict[str, type[BaseModel]] = {}
        self._database_translated_fields: dict[str, str] = {}
        self._database_company_dependent_fields: set[str] = set()
        self._assertion_report = _get_assertion_report(db_name)
        self._ordinary_tables: dict[str, bool] = {}
        self._constraint_queue: dict[typing.Any, Callable[[BaseCursor], None]] = {}
        self._caches = _RegistryCaches()

        self._reinit_modules: set[str] = set()

        self._init_modules: set[str] = set()
        self.updated_modules: list[str] = []
        self.loaded_xmlids: set[str] = set()

        self.db_name = db_name
        self._db: Connection = db.db_connect(db_name, readonly=False)
        self._db_readonly: Connection | None = None
        self._replica_breaker = CircuitBreaker(max_cooldown=_REPLICA_RETRY_TIME)
        self._replica_lag = ReplicaLagGate(config["db_replica_max_lag"] or 0.0)
        if (
            config["db_replica_host"]
            or config["test_enable"]
            or "replica" in config["dev_mode"]
        ):
            self._db_readonly = db.db_connect(db_name, readonly=True)

        self.many2many_relations: defaultdict[
            tuple[str, str, str], OrderedSet[tuple[str, str]]
        ] = defaultdict(OrderedSet)

        self.field_setup_dependents: Collector[Field, Field] = Collector()

        self.many2one_company_dependents: Collector[str, Field] = Collector()

        self.not_null_fields: set[Field] = set()

        self.model_graph = ModelGraph()

        self.registry_sequence: int = -1
        self.cache_sequences: dict[str, int] = {}

        self._invalidation_flags = threading.local()

        from odoo.modules import db as modules_db

        with closing(self.cursor()) as cr:
            self.has_unaccent = modules_db.has_unaccent(cr)
            self.has_trigram = modules_db.has_trigram(cr)
            table = _get_unaccent_table(cr, self.db_name) if self.has_unaccent else None

        self.unaccent = _unaccent if self.has_unaccent else _identity
        self.unaccent_python = (
            partial(_unaccent_python, table=table) if table is not None else _identity
        )

    @classmethod
    @locked
    def delete(cls, db_name: str) -> None:
        if db_name in cls.registries:
            del cls.registries[db_name]
        from odoo.tools.cache import prune_counters

        prune_counters(db_name)

    @classmethod
    @locked
    def delete_all(cls):
        cls.registries.clear()

    __eq__ = object.__eq__
    __ne__ = object.__ne__
    __hash__ = object.__hash__

    def __len__(self) -> int:
        return len(self.models)

    def __iter__(self) -> Iterator[str]:
        return iter(self.models)

    def __getitem__(self, model_name: str) -> type[BaseModel]:
        return self.models[model_name]

    def __setitem__(self, model_name: str, model: type[BaseModel]) -> None:
        self.models[model_name] = model

    def __delitem__(self, model_name: str) -> None:
        del self.models[model_name]
        for Model in self.models.values():
            Model._inherit_children.discard(model_name)

    def descendants(
        self,
        model_names: Iterable[str],
        *kinds: typing.Literal["_inherit", "_inherits"],
    ) -> OrderedSet[str]:
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
        from .. import models

        model_defs = models.MetaModel._module_to_models__.get(module.name, [])
        if not model_defs:
            return []

        self._caches.clear_all()

        reset_cached_properties(self)
        self.model_graph.clear_caches()

        model_names = []
        for model_def in model_defs:
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
        from .environment import Environment

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

        if self.ready:
            for model in env.values():
                model._unregister_hook()

        self._caches.clear_all()

        self.model_graph.begin_invalidation()
        try:
            reset_cached_properties(self)
            self.model_graph.clear_caches()
            self.registry_invalidated = True

            models_field_depends_done = set()

            if model_names is None:
                self.many2many_relations.clear()
                self.field_setup_dependents.clear()

                for model_cls in self.models.values():
                    model_cls._setup_done__ = False

                self.model_graph.reset_field_metadata()

            else:
                model_names_to_setup = self.descendants(
                    model_names, "_inherit", "_inherits"
                )
                for fields in self.many2many_relations.values():
                    for pair in list(fields):
                        if pair[0] in model_names_to_setup:
                            fields.discard(pair)

                for model_name in model_names_to_setup:
                    self[model_name]._setup_done__ = False

                todo = []
                for model_cls in self.models.values():
                    if model_cls._custom:
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
                        name = field.name
                        base_fields = field._base_fields__

                        field.__dict__.clear()
                        field.__init__(_base_fields__=base_fields)
                        field._toplevel = True
                        field.__set_name__(model_cls, name)
                        field._setup_done = False

                        models_field_depends_done.discard(model_cls)

                    elif model_cls._setup_done__ and field.related and field.manual:
                        model_cls._setup_done__ = False
                        models_field_depends_done.discard(model_cls)

                    self.field_depends.pop(field, None)
                    self.field_depends_context.pop(field, None)

                    done.add(field)
                    # `todo` is a deliberate worklist: list iteration re-reads
                    # len() each step, so dependents queued here are picked up by
                    # this same loop, and `done` stops a field being processed twice.
                    todo.extend(self.field_setup_dependents.pop(field, ()))  # noqa: B909  see comment above

            self.many2one_company_dependents.clear()

            registration.setup_model_classes(env)

            for model_cls in self.models.values():
                if model_cls in models_field_depends_done:
                    continue
                model = model_cls(env, (), ())
                for field in model._fields.values():
                    depends, depends_context = field.get_depends(model)
                    self.field_depends[field] = tuple(depends)
                    self.field_depends_context[field] = tuple(depends_context)

            reset_cached_properties(self)

        finally:
            self.model_graph.end_invalidation()

        if self.ready:
            for model in env.values():
                model._register_hook()
            self.__dict__.pop("_field_triggers", None)
            self._ensure_field_triggers()
            env.flush_all()

    def post_init(self, func: Callable, *args, **kwargs) -> None:
        self._post_init_queue.append(partial(func, *args, **kwargs))

    def init_models(
        self,
        cr: Cursor,
        model_names: Iterable[str],
        context: dict[str, typing.Any],
        install: bool = True,
    ):
        if not model_names:
            return

        if "module" in context:
            _logger.info(
                "module %s: creating or updating database tables",
                context["module"],
            )
        elif context.get("models_to_check"):
            _logger.info("verifying fields for every extended model")

        from .environment import Environment

        env = Environment(cr, SUPERUSER_ID, context)
        models = [env[model_name] for model_name in model_names]

        try:
            self._post_init_queue: deque[Callable] = deque()
            self._foreign_keys: dict[
                tuple[str, str], tuple[str, str, str, BaseModel, str]
            ] = {}
            self._relation_reflections: OrderedSet[tuple[str, str, str]] = OrderedSet()
            self._is_install: bool = install

            for model in models:
                model._auto_init()
                model.init()

            env["ir.model"]._reflect_models(model_names)
            env["ir.model.fields"]._reflect_fields(model_names)
            env["ir.model.fields.selection"]._reflect_selections(model_names)
            env["ir.model.constraint"]._reflect_constraints(model_names)
            env["ir.model.inherit"]._reflect_inherits(model_names)
            env["ir.model.relation"]._reflect_relations(self._relation_reflections)

            self._ordinary_tables = {}

            while self._post_init_queue:
                func = self._post_init_queue.popleft()
                func()

            self.check_indexes(cr, model_names)
            self.check_foreign_keys(cr)

            env.flush_all()

            self.check_tables_exist(cr)

        finally:
            del self._post_init_queue
            del self._foreign_keys
            del self._relation_reflections
            del self._is_install

    def _clear_cache_group(self, cache_name: str) -> None:
        self._caches.clear_group(cache_name)

    @property
    def ormcache_lrus(self) -> dict[str, LRU]:
        return self._caches.lrus

    def clear_cache(self, *cache_names: str) -> None:
        cache_names = cache_names or ("default",)
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
            caller_info = format_frame(inspect.currentframe().f_back)
            _logger.debug(
                "Invalidating %s model caches from %s",
                ",".join(cache_names),
                caller_info,
            )

    def clear_all_caches(self) -> None:
        for cache_name in _CACHES_BY_KEY:
            self._clear_cache_group(cache_name)
            self.cache_invalidated.add(cache_name)

        caller_info = format_frame(inspect.currentframe().f_back)
        log = _logger.info if self.loaded else _logger.debug
        log("Invalidating all model caches from %s", caller_info)

    @property
    def registry_invalidated(self) -> bool:
        return getattr(self._invalidation_flags, "registry", False)

    @registry_invalidated.setter
    def registry_invalidated(self, value: bool) -> None:
        self._invalidation_flags.registry = value

    @property
    def cache_invalidated(self) -> set[str]:
        try:
            return self._invalidation_flags.cache
        except AttributeError:
            names = self._invalidation_flags.cache = set()
            return names

    def setup_signaling(self) -> None:
        with self.cursor() as cr:
            existing_sig_tables = tuple(sql.existing_tables(cr, _SIGNALING_TABLES))
            for table_name in _SIGNALING_TABLES:
                if table_name not in existing_sig_tables:
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
        if row is None:
            raise RuntimeError("No result when reading signaling sequences")
        registry_sequence, *cache_sequences_values = row
        cache_sequences = dict(zip(_CACHES_BY_KEY, cache_sequences_values, strict=True))
        return registry_sequence, cache_sequences

    def check_signaling(self, cr: BaseCursor | None = None) -> Registry:
        own_cursor = cr is None
        try:
            with (
                nullcontext(cr)
                if cr is not None
                else closing(self.cursor(readonly=True))
            ) as sig_cr:
                db_registry_sequence, db_cache_sequences = self.get_sequences(sig_cr)
                changes = ""
                if db_registry_sequence > self.registry_sequence:
                    _logger.info(
                        "Reloading the model registry after database signaling."
                    )
                    old_sequence = self.registry_sequence
                    published = Registry.registries.get(self.db_name)
                    if (
                        published is not None
                        and published is not self
                        and published.ready
                        and published.registry_sequence >= db_registry_sequence
                    ):
                        self = published
                    else:
                        from odoo.db import drain_db

                        drain_db(self.db_name)
                        self = Registry.new(self.db_name)
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
                invalidated = []
                for (
                    cache_name,
                    cache_sequence,
                ) in self.cache_sequences.items():
                    expected_sequence = db_cache_sequences[cache_name]
                    if expected_sequence > cache_sequence:
                        for cache in _CACHES_BY_KEY[cache_name]:
                            if cache not in invalidated:
                                invalidated.append(cache)
                                self._caches.lrus[cache].clear()
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
            raise
        except psycopg.OperationalError:
            if own_cursor:
                type(self).delete(self.db_name)
            raise
        return self

    def signal_changes(self) -> None:
        if not self.ready:
            _logger.warning(
                "Calling signal_changes when registry is not ready is not supported"
            )
            return

        if self.registry_invalidated:
            _logger.info("Registry changed, signaling through the database")
            with self.cursor() as cr:
                cr.execute("INSERT INTO orm_signaling_registry DEFAULT VALUES")
                self.registry_sequence += 1

        if self.cache_invalidated:
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
                    self.cache_sequences[cache_name] += 1

        self.registry_invalidated = False
        self.cache_invalidated.clear()

    def reset_changes(self) -> None:
        if self.registry_invalidated:
            with closing(self.cursor()) as cr:
                self._setup_models__(cr)
                self.registry_invalidated = False
        if self.cache_invalidated:
            for cache_name in self.cache_invalidated:
                self._clear_cache_group(cache_name)
            self.cache_invalidated.clear()

    def _sample_replica_lag(self, cr: BaseCursor) -> None:
        try:
            cr.execute(LAG_SQL)
            measured = cr.fetchone()[0]
        except Exception:
            _logger.debug("Could not measure replica lag", exc_info=True)
            measured = None
        was_allowed = self._replica_lag.allows()
        self._replica_lag.record(measured)
        if was_allowed and not self._replica_lag.allows():
            _logger.warning(
                "Replica %.1fs behind (db_replica_max_lag=%.1fs); serving "
                "readonly requests from the primary until it catches up",
                self._replica_lag.last_lag,
                self._replica_lag.max_lag,
            )
        elif not was_allowed and self._replica_lag.allows():
            _logger.info(
                "Replica caught up (%.1fs behind); resuming readonly cursors",
                self._replica_lag.last_lag,
            )

    def cursor(self, /, readonly: bool = False) -> BaseCursor:
        if readonly and self._db_readonly is not None:
            thread = current_worker_thread()
            in_request = hasattr(thread, "cursor_mode")
            lag = self._replica_lag
            sample_due = lag.due_for_sample()
            if (lag.allows() or sample_due) and self._replica_breaker.allow():
                try:
                    cr = self._db_readonly.cursor()
                except psycopg.OperationalError, db.PoolError:
                    self._replica_breaker.record_failure()
                    _logger.warning(
                        "Failed to open a readonly cursor, falling back to the "
                        "read-write cursor and retrying the replica in %.0fs "
                        "(failure %d)",
                        self._replica_breaker.cooldown_remaining,
                        self._replica_breaker.failures,
                    )
                else:
                    if not self._replica_breaker.closed:
                        _logger.info(
                            "Replica reachable again, resuming readonly cursors"
                        )
                    self._replica_breaker.record_success()
                    if sample_due:
                        self._sample_replica_lag(cr)
                    if lag.allows():
                        if in_request:
                            thread.cursor_mode = "ro"
                        return cr
                    cr.close()
            if in_request:
                thread.cursor_mode = "ro->rw"
        return self._db.cursor()


class DummyRLock:
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
        traceback: types.TracebackType | None,
    ) -> None:
        self.release()
