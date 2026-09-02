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
from odoo.db.replica import ReplicaRouter, is_readonly_cursor_enabled
from odoo.libs import gc
from odoo.libs.func import locked, reset_cached_properties
from odoo.libs.lru import LRU
from odoo.libs.worker_thread import current_worker_thread
from odoo.tools import OrderedSet, config
from odoo.tools.constants import CACHES_BY_KEY

from .. import registration
from ..primitives import SUPERUSER_ID
from ._registry_capabilities import (
    _RegistryCapabilitiesMixin,
    forget_all_unaccent_tables,
    forget_unaccent_table,
)
from ._registry_fields import _RegistryFieldsMixin
from ._registry_init_phase import _RegistryInitPhaseMixin
from ._registry_models import _RegistryModelsMixin
from ._registry_schema import _RegistrySchemaMixin
from ._registry_signaling import _RegistrySignalingMixin

if typing.TYPE_CHECKING:
    from odoo.db import BaseCursor, Cursor
    from odoo.models import BaseModel
    from odoo.modules import module_graph


_logger = logging.getLogger("odoo.registry")
_schema = logging.getLogger("odoo.schema")


_ASSERTION_REPORTS: dict[str, typing.Any] = {}


def _get_assertion_report(db_name: str) -> typing.Any:
    if not config["test_enable"]:
        return None
    from odoo.tests.result import OdooTestResult

    report = _ASSERTION_REPORTS.get(db_name)
    if report is None:
        report = _ASSERTION_REPORTS[db_name] = OdooTestResult()
    return report


class Registry(
    _RegistryFieldsMixin,
    _RegistrySchemaMixin,
    _RegistryModelsMixin,
    _RegistryInitPhaseMixin,
    _RegistryCapabilitiesMixin,
    _RegistrySignalingMixin,
    Mapping[str, type["BaseModel"]],
):
    _lock: threading.RLock | DummyRLock = threading.RLock()

    registries = LRU[str, "Registry"](42)

    idle_timeout: float = 0

    last_used: float

    _replica: ReplicaRouter

    def __new__(cls, db_name: str):
        if not db_name:
            raise ValueError("Missing database name")
        reg = cls.registries.get(db_name)
        if reg is not None and reg.ready:
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
    def _new_finalize(cls, db_name: str, update_module: bool, t0: float) -> Registry:
        registry = cls.registries[db_name]

        registry._init = False
        registry.ready = True
        registry.registry_invalidated = bool(update_module)

        registry._get_field_triggers()

        if update_module:
            from odoo.db import drain_all

            drain_all()
        registry.signal_changes()

        _logger.info("Registry loaded in %.3fs", time.time() - t0)
        registry.last_used = time.monotonic()
        cls._evict_idle_registries()
        return registry

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
        models_to_check: OrderedSet[str] | None = None,
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
        registry.new = registry.init = registry.registries = None  # type: ignore[method-assign, assignment]
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

        return cls._new_finalize(db_name, update_module, t0)

    def init(self, db_name: str) -> None:
        self._init = True
        self.loaded = False
        self.ready = False
        self.last_used = time.monotonic()

        self._init_models_container()
        self._init_phase_state()
        self._init_field_state()
        self._init_schema_state()
        self._init_signaling_state()

        self._database_translated_fields: dict[str, str] = {}
        self._database_company_dependent_fields: set[str] = set()
        self._assertion_report = _get_assertion_report(db_name)

        self._reinit_modules: set[str] = set()

        self.loaded_modules: set[str] = set()
        self.updated_modules: list[str] = []
        self.loaded_xmlids: set[str] = set()
        self._xmlid_recorder: set[str] | None = None
        self._load_language_done: bool = False

        self.db_name = db_name
        self._replica = ReplicaRouter(
            db.db_connect(db_name, readonly=False),
            db.db_connect(db_name, readonly=True)
            if is_readonly_cursor_enabled()
            else None,
            max_lag=config["db_replica_max_lag"] or 0.0,
        )

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
    def _evict_idle_registries(cls) -> None:
        if cls.idle_timeout <= 0:
            return
        now = time.monotonic()
        for db_name, registry in cls.registries.items():
            if not registry.ready:
                continue
            idle_for = now - registry.last_used
            if idle_for > cls.idle_timeout:
                _logger.info(
                    "Evicting idle registry for %s, idle for %.0fs", db_name, idle_for
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
    def remove_all(cls):
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
            model_cls = registration.add_model_to_registry(
                self, typing.cast("type[BaseModel]", model_def)
            )
            model_names.append(model_cls._name)

        return model_names

    def _setup_reset_all_models(self) -> None:
        self.many2many_relations.clear()
        self.field_setup_dependents.clear()

        for model_cls in self.models.values():
            model_cls._setup_done__ = False

        self.model_graph.reset_field_metadata()

    def _setup_reset_named_models(
        self, model_names: Iterable[str], models_field_depends_done: set
    ) -> None:
        model_names_to_setup = self.descendants(model_names, "_inherit", "_inherits")
        for fields in self.many2many_relations.values():
            for pair in list(fields):
                if pair[0] in model_names_to_setup:
                    fields.discard(pair)

        for model_name in model_names_to_setup:
            self[model_name]._setup_done__ = False

        todo: list = []
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
            todo.extend(self.field_setup_dependents.pop(field, ()))  # noqa: B909  todo is a worklist: appending newly discovered dependents here is how they get processed later in this same loop

    def _setup_refresh_field_depends(self, env, models_field_depends_done: set) -> None:
        for model_cls in self.models.values():
            if model_cls in models_field_depends_done:
                continue
            model = model_cls(env, (), ())
            for field in model._fields.values():
                depends, depends_context = field.get_depends(model)
                self.field_depends[field] = tuple(depends)
                self.field_depends_context[field] = tuple(depends_context)

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

            models_field_depends_done: set[type] = set()

            if model_names is None:
                self._setup_reset_all_models()
            else:
                self._setup_reset_named_models(model_names, models_field_depends_done)

            self.many2one_company_dependents.clear()

            registration.setup_model_classes(env)

            self._setup_refresh_field_depends(env, models_field_depends_done)

            reset_cached_properties(self)

        finally:
            self.model_graph.end_invalidation()

        if self.ready:
            for model in env.values():
                model._register_hook()
            self.__dict__.pop("_field_triggers", None)
            self._get_field_triggers()
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

        with self.init_models_window(install) as phase:
            for model in models:
                model._auto_init()
                model.init()

            env["ir.model"]._reflect_models(model_names)
            env["ir.model.fields"]._reflect_fields(model_names)
            env["ir.model.fields.selection"]._reflect_selections(model_names)
            env["ir.model.constraint"]._reflect_constraints(model_names)
            env["ir.model.inherit"]._reflect_inherits(model_names)
            env["ir.model.relation"]._reflect_relations(phase.relation_reflections)

            self._ordinary_tables = {}

            self.drain_post_init()

            self.check_indexes(cr, model_names)
            self.check_foreign_keys(cr)

            env.flush_all()

            self.check_tables_exist(cr)

    def clear_all_caches(self) -> None:
        self._invalidate_cache_groups(CACHES_BY_KEY)
        self._log_invalidation(("all",), logging.INFO if self.loaded else logging.DEBUG)

    def setup_signaling(self) -> None:
        with self.cursor() as cr:
            self._create_missing_signaling_tables(cr)
            self._load_sequences(cr)

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
                    old_sequence = self.registry_sequence
                    self = self._reload_after_signaling(db_registry_sequence)
                    sig_cr.invalidate_cached_plans()
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
                changes += self._sync_cache_sequences(db_cache_sequences)
                if changes:
                    _logger.debug("Multiprocess signaling check: %s", changes)
        except db.PoolError:
            raise
        except psycopg.OperationalError:
            if own_cursor:
                type(self).delete(self.db_name)
            raise
        return self

    def _reload_after_signaling(self, db_registry_sequence: int) -> Registry:
        _logger.info("Reloading the model registry after database signaling.")
        published = Registry.registries.get(self.db_name)
        if (
            published is not None
            and published is not self
            and published.ready
            and published.registry_sequence >= db_registry_sequence
        ):
            return published
        from odoo.db import drain_db

        drain_db(self.db_name)
        return Registry.new(self.db_name)

    def signal_changes(self) -> None:
        if not self.ready:
            _logger.warning(
                "Calling signal_changes when registry is not ready is not supported"
            )
            return

        if self.registry_invalidated:
            with self.cursor() as cr:
                self._signal_registry_change(cr)

        if self.cache_invalidated:
            with self.cursor() as cr:
                self._signal_cache_changes(cr)

        self.registry_invalidated = False
        self.cache_invalidated.clear()

    def reset_changes(self) -> None:
        if self.registry_invalidated:
            with closing(self.cursor()) as cr:
                self._setup_models__(cr)
                self.registry_invalidated = False
        self._reset_cache_changes()

    def cursor(self, /, readonly: bool = False) -> BaseCursor:
        cr, mode = self._replica.cursor(readonly)
        if mode != "rw":
            thread = current_worker_thread()
            if hasattr(thread, "cursor_mode"):
                thread.cursor_mode = mode
        return cr


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
