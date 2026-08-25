import inspect
import logging
import threading
import time
import types
import typing
from collections.abc import Collection, Iterable, Mapping
from contextlib import ExitStack, closing, nullcontext

import psycopg

from odoo import db
from odoo.db import schema as sql
from odoo.db.breaker import CircuitBreaker
from odoo.db.lag import LAG_SQL, ReplicaLagGate
from odoo.libs import gc
from odoo.libs.func import locked, reset_cached_properties
from odoo.libs.lru import LRU
from odoo.libs.worker_thread import current_worker_thread
from odoo.tools import SQL, config
from odoo.tools.constants import CACHES_BY_KEY, REGISTRY_CACHES
from odoo.tools.misc import format_frame

from .. import registration
from ..primitives import SUPERUSER_ID
from ._init_phase import InitModelsPhase
from ._registry_capabilities import (
    _RegistryCapabilitiesMixin,
    forget_all_unaccent_tables,
    forget_unaccent_table,
)
from ._registry_fields import _RegistryFieldsMixin
from ._registry_init_phase import _RegistryInitPhaseMixin
from ._registry_models import _RegistryModelsMixin
from ._registry_schema import _RegistrySchemaMixin

if typing.TYPE_CHECKING:
    from odoo.db import BaseCursor, Connection, Cursor
    from odoo.models import BaseModel
    from odoo.modules import module_graph


_logger = logging.getLogger("odoo.registry")
_schema = logging.getLogger("odoo.schema")


_REPLICA_RETRY_TIME = 20 * 60


def signaling_table_name(cache_name: str) -> str:
    """Name of the signalling table for a cache group.

    One rule, one place. It was spelled out separately in the constant below, in
    `signal_changes`, and a third time outside this package in
    `ir_autovacuum._gc_orm_signaling`, which had to re-derive the whole list
    because the constant was private.
    """
    return f"orm_signaling_{cache_name}"


#: Every signalling table, in the order the cache groups declare them.
SIGNALING_TABLES = tuple(
    signaling_table_name(cache_name) for cache_name in ["registry", *CACHES_BY_KEY]
)

#: Kept for the private name this module used before the derivation was exported.
_SIGNALING_TABLES = SIGNALING_TABLES

_ASSERTION_REPORTS: dict[str, typing.Any] = {}


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
            for cache_name, cache_size in REGISTRY_CACHES.items()
        }

    def clear_group(self, cache_name: str) -> None:
        for cache in CACHES_BY_KEY[cache_name]:
            self.lrus[cache].clear()

    def clear_all(self) -> None:
        for lru in self.lrus.values():
            lru.clear()


class Registry(
    _RegistryFieldsMixin,
    _RegistrySchemaMixin,
    _RegistryModelsMixin,
    _RegistryInitPhaseMixin,
    _RegistryCapabilitiesMixin,
    Mapping[str, type["BaseModel"]],
):
    _lock: threading.RLock | DummyRLock = threading.RLock()

    registries = LRU[str, "Registry"](42)

    idle_timeout: float = 0
    """Seconds a registry may go unused before :meth:`_drop_idle` collects it.

    Zero (the default) disables collection entirely. Set from
    ``registry_idle_timeout`` at startup -- see ``odoo.service.lifecycle``.
    """

    last_used: float
    """``time.monotonic()`` of the most recent lookup, maintained by
    :meth:`__new__` on *both* of its return paths."""

    def __new__(cls, db_name: str):
        if not db_name:
            raise ValueError("Missing database name")
        reg = cls.registries.get(db_name)
        if reg is not None and reg.ready:
            # Stamp here too, not only in the locked branch below. A *ready*
            # registry only ever leaves through this fast path -- the locked
            # branch is reached solely when the registry is absent or still
            # loading -- so stamping only there would leave `last_used` frozen
            # at load time for every healthy registry, and `_drop_idle` would
            # collect the busiest database on the server. Cheap enough to do
            # unlocked: the write is a single float store, and a lost update
            # under a race only ever costs one more collection pass.
            reg.last_used = time.monotonic()
            return reg
        with cls._lock:
            try:
                registry = cls.registries[db_name]
                registry.last_used = time.monotonic()
                return registry
            except KeyError:
                return cls.new(db_name)

    _init: bool
    ready: bool
    loaded: bool

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
        run_tests: bool = True,
    ) -> Registry:
        if db.is_maintenance_db(db_name):
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
                if sql.table_exists(cr, "ir_module_module"):
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
                    run_tests=run_tests,
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
        registry.last_used = time.monotonic()
        cls._drop_idle()
        return registry

    def init(self, db_name: str) -> None:
        self._init = True
        self.loaded = False
        self.ready = False
        # A registry must never be born already idle: loading one can take
        # seconds, and `_drop_idle` runs at the end of every load.
        self.last_used = time.monotonic()

        self._init_models_container()
        self._init_phase_state()
        self._init_field_state()
        self._init_schema_state()

        self._database_translated_fields: dict[str, str] = {}
        self._database_company_dependent_fields: set[str] = set()
        self._assertion_report = _get_assertion_report(db_name)
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

        self.registry_sequence: int = -1
        self.cache_sequences: dict[str, int] = {}

        self._invalidation_flags = threading.local()

        with closing(self.cursor()) as cr:
            self._probe_capabilities(cr, db_name)

    @classmethod
    @locked
    def delete(cls, db_name: str) -> None:
        if db_name in cls.registries:
            del cls.registries[db_name]
        from odoo.tools.cache import prune_counters

        prune_counters(db_name)

    @classmethod
    @locked
    def _drop_idle(cls) -> None:
        """Drop every registry unused for longer than :attr:`idle_timeout`.

        ``registries`` is bounded by a *count*, so on a server with many
        databases the number of resident registries follows traffic rather than
        memory: a worker can be recycled at its virtual-memory soft limit while
        the LRU still has room. This bounds it by recency instead.

        Dropping only detaches a registry from ``registries``. A request already
        holding one keeps working -- which is what makes this safe to run from a
        serving process -- and the next lookup rebuilds it.

        Registries that are still loading are skipped: ``new()`` publishes into
        ``registries`` *before* ``load_modules`` runs, so a concurrent build is
        visible here and must not be collected out from under itself.
        """
        if cls.idle_timeout <= 0:
            return
        now = time.monotonic()
        for db_name, registry in cls.registries.items():
            if not registry.ready:
                continue
            idle_for = now - registry.last_used
            if idle_for > cls.idle_timeout:
                _logger.info(
                    "Dropping registry for %s, idle for %.0fs", db_name, idle_for
                )
                cls.delete(db_name)

    @classmethod
    @locked
    def forget(cls, db_name: str) -> None:
        cls.delete(db_name)
        forget_unaccent_table(db_name)
        _ASSERTION_REPORTS.pop(db_name, None)

    @classmethod
    @locked
    def delete_all(cls):
        cls.registries.clear()
        forget_all_unaccent_tables()
        _ASSERTION_REPORTS.clear()

    __eq__ = object.__eq__
    __ne__ = object.__ne__
    __hash__ = object.__hash__

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

    def init_models(
        self,
        cr: Cursor,
        model_names: Iterable[str],
        context: dict[str, typing.Any],
        install: bool = True,
    ):
        model_names = list(model_names)
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
            self._init_phase = InitModelsPhase(install=install)

            for model in models:
                model._auto_init()
                model.init()

            env["ir.model"]._reflect_models(model_names)
            env["ir.model.fields"]._reflect_fields(model_names)
            env["ir.model.fields.selection"]._reflect_selections(model_names)
            env["ir.model.constraint"]._reflect_constraints(model_names)
            env["ir.model.inherit"]._reflect_inherits(model_names)
            env["ir.model.relation"]._reflect_relations(
                self.init_phase.relation_reflections
            )

            self._ordinary_tables = {}

            post_init_queue = self.init_phase.post_init_queue
            while post_init_queue:
                post_init_queue.popleft()()

            self.check_indexes(cr, model_names)
            self.check_foreign_keys(cr)

            env.flush_all()

            self.check_tables_exist(cr)

        finally:
            self._init_phase = None

    def _clear_cache_group(self, cache_name: str) -> None:
        self._caches.clear_group(cache_name)

    @property
    def ormcache_lrus(self) -> dict[str, LRU]:
        return self._caches.lrus

    def _log_invalidation(self, cache_names: Collection[str], level: int) -> None:
        if not _logger.isEnabledFor(level):
            return
        _logger.log(
            level,
            "Invalidating %s model caches from %s",
            ",".join(cache_names),
            format_frame(inspect.currentframe().f_back.f_back),
        )

    def clear_cache(self, *cache_names: str) -> None:
        cache_names = cache_names or ("default",)
        for cache_name in cache_names:
            if cache_name not in CACHES_BY_KEY:
                raise ValueError(
                    f"clear_cache: invalid cache name {cache_name!r} — only "
                    f"composite group names can be cleared (sub-cache names "
                    f"like 'templates.cached_values' cannot); valid names: "
                    f"{', '.join(sorted(CACHES_BY_KEY))}"
                )
        for cache_name in cache_names:
            self._clear_cache_group(cache_name)
            self.cache_invalidated.add(cache_name)

        self._log_invalidation(cache_names, logging.DEBUG)

    def clear_all_caches(self) -> None:
        for cache_name in CACHES_BY_KEY:
            self._clear_cache_group(cache_name)
            self.cache_invalidated.add(cache_name)

        self._log_invalidation(("all",), logging.INFO if self.loaded else logging.DEBUG)

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
                SQL(
                    "( SELECT coalesce(max(id), 0) FROM %s)",
                    SQL.identifier(signaling_table),
                )
                for signaling_table in _SIGNALING_TABLES
            ]
        )
        cr.execute(SQL("SELECT %s", signaling_selects))
        row = cr.fetchone()
        if row is None:
            raise RuntimeError("No result when reading signaling sequences")
        registry_sequence, *cache_sequences_values = row
        cache_sequences = dict(zip(CACHES_BY_KEY, cache_sequences_values, strict=True))
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
                        for cache in CACHES_BY_KEY[cache_name]:
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

    @staticmethod
    def _signalled_id(cr: BaseCursor, previous: int) -> int:
        row = cr.fetchone()
        if row and isinstance(row[0], int):
            return row[0]
        return previous + 1

    def signal_changes(self) -> None:
        if not self.ready:
            _logger.warning(
                "Calling signal_changes when registry is not ready is not supported"
            )
            return

        if self.registry_invalidated:
            _logger.info("Registry changed, signaling through the database")
            with self.cursor() as cr:
                cr.execute(
                    "INSERT INTO orm_signaling_registry DEFAULT VALUES RETURNING id"
                )
                self.registry_sequence = self._signalled_id(cr, self.registry_sequence)

        if self.cache_invalidated:
            _logger.info(
                "Caches invalidated, signaling through the database: %s",
                sorted(self.cache_invalidated),
            )
            with self.cursor() as cr:
                for cache_name in self.cache_invalidated:
                    cr.execute(
                        SQL(
                            "INSERT INTO %s DEFAULT VALUES RETURNING id",
                            SQL.identifier(signaling_table_name(cache_name)),
                        )
                    )
                    self.cache_sequences[cache_name] = self._signalled_id(
                        cr, self.cache_sequences[cache_name]
                    )

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
