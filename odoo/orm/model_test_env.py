import logging
import threading
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from operator import attrgetter
from typing import TYPE_CHECKING

from odoo.db import BaseCursor, FunctionStatus
from odoo.libs.collections import Collector
from odoo.tools import OrderedSet

from . import decorators as api
from . import registration
from .components.model_graph import ModelGraph
from .components.storage import DictBackend
from .fields import Boolean, Char, Many2one
from .models import AbstractModel, Model
from .primitives import SUPERUSER_ID
from .runtime._registry_fields import _RegistryFieldsMixin
from .runtime.registry import CACHES_BY_KEY
from .runtime.transaction import Transaction

if TYPE_CHECKING:
    from .models.base import BaseModel
    from .runtime.environment import Environment
    from .runtime.registry import Registry

_logger = logging.getLogger("odoo.orm.model_test_env")


class InMemorySqlNotSupported(NotImplementedError):
    pass


class InMemoryRecordRulesNotSupported(NotImplementedError):
    pass


class _TestBase(AbstractModel):
    _name = "base"
    _description = "Base"
    _register = False
    _module = None


class _TestIrDefault(AbstractModel):
    _name = "ir.default"
    _description = "Ir Default (test stub)"
    _register = False
    _module = None

    def _get_model_defaults(self, model_name, condition=False):
        return {}


class _TestResUsers(Model):
    _name = "res.users"
    _description = "Users (test stub)"
    _register = False
    _module = None
    _log_access = False

    name = Char()
    login = Char()
    active = Boolean(default=True)
    company_id = Many2one("res.company")

    def _get_company_ids(self):
        return self.company_id.ids

    @api.model
    def context_get(self):
        return {"lang": "en_US", "tz": False, "uid": self.env.uid}


class _TestResCompany(Model):
    _name = "res.company"
    _description = "Companies (test stub)"
    _register = False
    _module = None
    _log_access = False

    name = Char()
    active = Boolean(default=True)


class InMemoryCursor(BaseCursor):
    def __init__(
        self,
        registry: Registry,
        fixtures: dict[str, list[tuple]] | None = None,
    ) -> None:
        super().__init__()
        self.dbname = registry.db_name
        self.storage = DictBackend()
        self.transaction = Transaction(registry, storage=self.storage)
        self._fixtures: dict[str, list[tuple]] = fixtures or {}
        self._last_result: list[tuple] = []

    def execute(
        self,
        query,
        params=None,
        log_exceptions: bool = True,
        prepare: bool | None = None,
    ) -> None:
        key = str(query)
        if key in self._fixtures:
            self._last_result = self._fixtures[key]
            return
        raise InMemorySqlNotSupported(
            "InMemoryCursor (DB-free model_test_env) cannot execute raw SQL:\n"
            f"    {key}\n"
            "ORM CRUD is handled in memory, but this query (e.g. read_group or a "
            "custom cr.execute) needs PostgreSQL. Register its result via "
            "model_test_env(..., fixtures={str(query): rows}) or use a DB-backed "
            "TransactionCase."
        )

    @property
    def rowcount(self) -> int:
        return len(self._last_result)

    def fetchall(self) -> list[tuple]:
        return list(self._last_result)

    def fetchone(self) -> tuple | None:
        return self._last_result[0] if self._last_result else None

    def fetchmany(self, size: int = 0) -> list[tuple]:
        return self._last_result[:size]

    _DICT_API_UNSUPPORTED = (
        "InMemoryCursor (DB-free model_test_env) cannot serve the dict cursor "
        "API (dictfetchone/dictfetchall): fixtures are tuple rows with no column "
        "names. Consume the registered fixture via fetchone/fetchall, or move the "
        "test to a DB-backed TransactionCase."
    )

    def dictfetchone(self) -> dict | None:
        if not self._last_result:
            return None
        raise InMemorySqlNotSupported(self._DICT_API_UNSUPPORTED)

    def dictfetchall(self) -> list[dict]:
        if not self._last_result:
            return []
        raise InMemorySqlNotSupported(self._DICT_API_UNSUPPORTED)

    def now(self) -> datetime:
        if self._now is None:
            self._now = datetime.now(UTC).replace(tzinfo=None)
        return self._now

    def savepoint(self, flush: bool = True):
        raise InMemorySqlNotSupported(
            "InMemoryCursor (DB-free model_test_env) does not support "
            "savepoints: DictBackend writes are applied immediately and no "
            "snapshot exists to roll back to (same limitation as rollback()). "
            "Use a DB-backed TransactionCase to test savepoint behaviour."
        )

    @contextmanager
    def pipeline(self):
        yield

    def commit(self) -> None:
        if self._savepoint_depth:
            raise RuntimeError(
                "Cannot commit inside a savepoint! "
                "This would corrupt the savepoint's rollback state."
            )
        self.flush()
        self.commit_count += 1
        self.clear()
        self._now = None
        self.prerollback.clear()
        self.postrollback.clear()
        self.postcommit.run()

    def rollback(self) -> None:
        raise InMemorySqlNotSupported(
            "InMemoryCursor (DB-free model_test_env) cannot roll back: storage "
            "writes are applied immediately and no snapshot exists to restore. "
            "A silent no-op would diverge from production ROLLBACK (which "
            "discards the transaction's writes); use a DB-backed "
            "TransactionCase to test rollback behaviour."
        )

    def close(self) -> None:
        pass


class ModelRegistry(_RegistryFieldsMixin, Mapping):
    _lock: threading.RLock = threading.RLock()

    def __init__(
        self,
        model_defs: Iterable[type[BaseModel]],
        *,
        db_name: str = ":memory:",
    ) -> None:
        self.db_name = db_name
        self.models: dict[str, type[BaseModel]] = {}

        self.model_graph = ModelGraph()

        self._init_modules = False
        self._database_translated_fields: dict[str, str] = {}
        self._database_company_dependent_fields: dict[str, str] = {}
        self.many2many_relations: defaultdict[
            tuple[str, str, str], OrderedSet[tuple[str, str]]
        ] = defaultdict(OrderedSet)
        self.field_setup_dependents: Collector = Collector()
        self.many2one_company_dependents: Collector = Collector()

        self.ormcache_lrus: dict[str, dict] = defaultdict(dict)

        self.ready = True

        self.not_null_fields: set = set()

        self.degraded_fields: dict = {}

        self.has_trigram = False

        self.has_unaccent = FunctionStatus.MISSING

        self._build(list(model_defs))

    def __getitem__(self, model_name: str) -> type[BaseModel]:
        try:
            return self.models[model_name]
        except KeyError:
            if model_name == "ir.rule":
                raise InMemoryRecordRulesNotSupported(
                    "ModelRegistry (DB-free model_test_env) has no 'ir.rule' "
                    "model: record rules are NOT enforced in this tier — "
                    "search() dispatches to the in-memory backend before the "
                    "ir.rule security domain (DictBackend declares "
                    "supports_record_rules = False). A security-adjacent "
                    "assertion would go green here while production filters "
                    "records. Use a DB-backed TransactionCase to test record-"
                    "rule behaviour, or pass your own ir.rule model class to "
                    "model_test_env(...) if you intend to stub it."
                ) from None
            raise

    def __contains__(self, model_name: object) -> bool:
        return model_name in self.models

    def __iter__(self):
        return iter(self.models)

    def __len__(self):
        return len(self.models)

    def __setitem__(self, model_name: str, model: type[BaseModel]) -> None:
        self.models[model_name] = model

    def __delitem__(self, model_name: str) -> None:
        del self.models[model_name]

    def post_init(self, func, *args, **kwargs) -> None:
        pass

    def post_constraint(self, cr, func, key) -> None:
        pass

    def add_foreign_key(self, *args, **kwargs) -> None:
        pass

    def reset_changes(self) -> None:
        pass

    def clear_cache(self, *cache_names: str) -> None:
        for cache_name in cache_names or ("default",):
            if "." in cache_name:
                raise ValueError(
                    f"clear_cache: invalid cache name {cache_name!r} (no dots allowed)"
                )
            for container in CACHES_BY_KEY.get(cache_name, (cache_name,)):
                self.ormcache_lrus[container].clear()

    def is_an_ordinary_table(self, model) -> bool:
        return True

    @staticmethod
    def unaccent(text):
        return text

    @staticmethod
    def unaccent_python(text):
        return text

    def descendants(
        self,
        model_names: Iterable[str],
        *kinds: str,
    ) -> OrderedSet:
        funcs = [attrgetter(kind + "_children") for kind in kinds]
        result: OrderedSet[str] = OrderedSet()
        queue = deque(model_names)
        while queue:
            name = queue.popleft()
            model = self.models.get(name)
            if model is None or model._name in result:
                continue
            result.add(model._name)
            for func in funcs:
                queue.extend(func(model))
        return result

    def _build(self, model_defs: list[type[BaseModel]]) -> None:
        from .models.metaclass import MetaModel

        modules = {"base"}
        for cls in model_defs:
            module = getattr(cls, "_module", None)
            if module:
                modules.add(module)

        all_defs: list[type[BaseModel]] = []
        seen_ids: set[int] = set()

        for module in sorted(modules, key=lambda m: (m != "base", m)):
            for cls in MetaModel._module_to_models__.get(module, []):
                if id(cls) not in seen_ids:
                    seen_ids.add(id(cls))
                    all_defs.append(cls)

        for cls in model_defs:
            if id(cls) not in seen_ids:
                seen_ids.add(id(cls))
                all_defs.append(cls)

        has_base = any(getattr(cls, "_name", None) == "base" for cls in all_defs)
        if not has_base:
            all_defs.insert(0, _TestBase)

        has_ir_default = any(
            getattr(cls, "_name", None) == "ir.default" for cls in all_defs
        )
        if not has_ir_default:
            all_defs.append(_TestIrDefault)

        has_res_users = any(
            getattr(cls, "_name", None) == "res.users" for cls in all_defs
        )
        if not has_res_users:
            all_defs.append(_TestResUsers)

        has_res_company = any(
            getattr(cls, "_name", None) == "res.company" for cls in all_defs
        )
        if not has_res_company:
            all_defs.append(_TestResCompany)

        all_defs.sort(
            key=lambda c: 0 if getattr(c, "_name", "") == "base" else 1,
        )

        for model_def in all_defs:
            registration.add_to_registry(self, model_def)

        cr = InMemoryCursor(self)
        from .runtime.environment import Environment

        env = Environment(cr, SUPERUSER_ID, {})

        model_classes = list(self.models.values())

        for model_cls in model_classes:
            registration._prepare_setup(model_cls)

        for model_cls in model_classes:
            registration._setup(model_cls, env)

        for model_cls in model_classes:
            self._setup_fields_lenient(model_cls, env)

        for model_cls in self.models.values():
            model = model_cls(env, (), ())
            for field in model._fields.values():
                try:
                    depends, depends_context = field.get_depends(model)
                    self.field_depends[field] = tuple(depends)
                    self.field_depends_context[field] = tuple(depends_context)
                except KeyError as exc:
                    self.field_depends[field] = ()
                    self.field_depends_context[field] = ()
                    self.degraded_fields[field] = f"get_depends: missing {exc}"

        if self.degraded_fields:
            _logger.warning(
                "model_test_env: %d field(s) degraded (missing comodel in the "
                "model set); their triggers/deps are inert. Inspect via "
                "registry.degraded_fields. Degraded: %s",
                len(self.degraded_fields),
                ", ".join(
                    sorted(f"{f.model_name}.{f.name}" for f in self.degraded_fields)
                ),
            )

        for model_cls in self.models.values():
            if model_cls._auto and not model_cls._abstract:
                for field in model_cls._fields.values():
                    if field.name == "id" or (
                        field.column_type and field.store and field.required
                    ):
                        self.not_null_fields.add(field)

        for model_cls in model_classes:
            try:
                model_cls(env, (), ())._post_model_setup__()
            except Exception:
                _logger.debug(
                    "Post-setup hook for %s failed (expected in test registry)",
                    model_cls._name,
                    exc_info=True,
                )

    @staticmethod
    def _setup_fields_lenient(
        model_cls: type[BaseModel],
        env: Environment,
    ) -> None:
        model = model_cls(env, (), ())
        for name, field in model_cls._fields.items():
            try:
                field.setup(model)
            except Exception as exc:
                comodel = getattr(field, "comodel_name", None)
                missing_comodel = bool(comodel) and comodel not in model_cls.pool
                if not missing_comodel and not isinstance(exc, KeyError):
                    raise
                _logger.debug(
                    "Field %s.%s setup incomplete (missing comodel?); field will raise if accessed in test",
                    model_cls._name,
                    name,
                )
                field._setup_done = True
                model_cls.pool.degraded_fields[field] = (
                    f"setup: {type(exc).__name__}: {exc}"
                )
            else:
                if field.is_many2one and field.company_dependent:
                    model_cls.pool.many2one_company_dependents.add(
                        field.comodel_name,
                        field,
                    )


@contextmanager
def model_test_env(
    *model_classes: type[BaseModel],
    registry: ModelRegistry | None = None,
    db_name: str = ":memory:",
    fixtures: dict[str, list[tuple]] | None = None,
):
    if registry is None:
        registry = ModelRegistry(model_classes, db_name=db_name)

    for cache in registry.ormcache_lrus.values():
        cache.clear()

    for attr in ("_field_triggers",):
        with suppress(AttributeError):
            delattr(registry, attr)

    cr = InMemoryCursor(registry, fixtures=fixtures)

    _seed_fixtures(cr.storage, registry)

    from .runtime.environment import Environment

    yield Environment(cr, SUPERUSER_ID, {})


def _seed_fixtures(storage: DictBackend, registry: ModelRegistry) -> None:

    def _inject(table: str, record_id: int, data: dict) -> None:
        data["id"] = record_id
        storage.put_rows(table, [data])

    if "res.partner" in registry:
        _inject(
            "res_partner",
            1,
            {
                "name": "Test Company",
                "active": True,
                "is_company": True,
                "type": "contact",
            },
        )

    if "res.company" in registry:
        _inject(
            "res_company",
            1,
            {
                "name": "Test Company",
                "active": True,
                "partner_id": 1,
                "parent_path": "1/",
            },
        )

    if "res.users" in registry:
        _inject(
            "res_users",
            1,
            {
                "name": "Admin",
                "login": "admin",
                "active": True,
                "company_id": 1,
                "partner_id": 1,
            },
        )
        field = registry["res.users"]._fields.get("company_ids")
        if field is not None and field.is_many2many and field.store and field.relation:
            storage.insert_rows(
                field.relation, [field.column1, field.column2], [(1, 1)]
            )
