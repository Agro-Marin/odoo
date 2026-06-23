"""ORM-level testing utilities.

:class:`InMemoryCursor` emulates a database cursor with no PostgreSQL
connection; paired with a pre-built :class:`Registry` it lets tests construct a
real :class:`Environment` to exercise compute methods, field logic, or business
rules without issuing SQL. :func:`model_test_env` builds a lightweight
:class:`ModelRegistry` from class definitions for fully DB-free testing.

See :class:`~odoo.orm.components.in_memory.InMemoryEnvironment` for the
lighter-weight alternative using plain Python callables instead of
``@api.depends`` compute methods.
"""

import functools
import logging
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from operator import attrgetter
from typing import TYPE_CHECKING

from odoo.db import BaseCursor
from odoo.libs.collections.misc import Collector
from odoo.tools import OrderedSet

from . import registration
from .components.storage import DictBackend
from .models import AbstractModel
from .primitives import SUPERUSER_ID
from .runtime.transaction import Transaction

if TYPE_CHECKING:
    from .models.base import BaseModel
    from .runtime.environment import Environment
    from .runtime.registry import Registry

_logger = logging.getLogger("odoo.orm.model_test_env")


# Minimal 'base' model for testing


class _TestBase(AbstractModel):
    """Minimal ``base`` model for :class:`ModelRegistry`.

    Every model implicitly inherits from ``base``.  This class provides
    just enough for the registration machinery to work without importing
    the full ``odoo.addons.base`` module tree.

    ``_register = False`` prevents :class:`MetaModel.__init__` from
    appending this class to ``_module_to_models__``, so it never
    interferes with real module loading.
    """

    _name = "base"
    _description = "Base"
    _register = False
    _module = None


class InMemoryCursor(BaseCursor):
    """Cursor backed by fixture data — no PostgreSQL required.

    Inherits :class:`~odoo.db.BaseCursor` for the callback containers and the
    ``savepoint()`` / ``flush()`` machinery. :meth:`__init__` pre-builds the
    ``Transaction`` and assigns it to ``self.transaction``, so
    ``Environment.__new__`` skips ``Transaction(Registry(cr.dbname))`` and never
    opens a connection. Its :class:`DictBackend` ``storage`` makes ORM CRUD
    dispatch to the in-memory backend instead of generating SQL.

    :param registry: pre-built model registry (e.g. ``self.env.registry``).
    :param fixtures: optional ``{query_string: rows}`` map; ``execute`` looks up
        ``str(query)`` here, returning ``[]`` for unknown queries.
    """

    def __init__(
        self,
        registry: Registry,
        fixtures: dict[str, list[tuple]] | None = None,
    ) -> None:
        super().__init__()
        self.dbname = registry.db_name
        # In-memory storage for backend-agnostic CRUD
        self.storage = DictBackend()
        # Pre-build Transaction so Environment.__new__ skips Registry(cr.dbname)
        self.transaction = Transaction(registry, storage=self.storage)
        self._fixtures: dict[str, list[tuple]] = fixtures or {}
        self._last_result: list[tuple] = []

    # Query execution — fixture-backed

    def execute(self, query, params=None, log_exceptions: bool = True) -> None:
        """Look up *query* in the fixture dict; default to empty result."""
        self._last_result = self._fixtures.get(str(query), [])

    def fetchall(self) -> list[tuple]:
        """Return all rows from the last executed query."""
        return list(self._last_result)

    def fetchone(self) -> tuple | None:
        """Return the first row from the last executed query, or ``None``."""
        return self._last_result[0] if self._last_result else None

    def fetchmany(self, size: int) -> list[tuple]:
        """Return up to *size* rows from the last executed query."""
        return self._last_result[:size]

    # fetchscalar() is inherited from BaseCursor (self.fetchone()-based) — the
    # local fetchone() above makes the inherited version correct here.

    def dictfetchone(self) -> dict | None:
        """Return ``None`` — no column metadata available without a real cursor."""
        return None

    def dictfetchall(self) -> list[dict]:
        """Return ``[]`` — no column metadata available without a real cursor."""
        return []

    # Time

    def now(self) -> datetime:
        """Return the current wall-clock time as a naive UTC datetime.

        The real cursor fetches ``now()`` from PostgreSQL for transaction
        consistency.  InMemoryCursor uses the local clock instead — suitable
        for tests that check *that* a timestamp is set, not its exact value.
        """
        return datetime.now(UTC).replace(tzinfo=None)

    # Transaction control — no-ops

    @contextmanager
    def pipeline(self):
        """No-op context manager — no real connection to pipeline."""
        yield

    def commit(self) -> None:
        """No-op — InMemoryCursor has no underlying connection to commit."""

    def rollback(self) -> None:
        """No-op — InMemoryCursor has no underlying connection to roll back."""

    def close(self) -> None:
        """No-op — there is no connection to close."""


# ModelRegistry — lightweight registry from class definitions


class ModelRegistry(Mapping):
    """Lightweight model registry built from Python class definitions.

    Satisfies the interface that :class:`Environment` and :class:`Transaction`
    need from :class:`Registry`, without database access or module loading —
    just a ``Mapping[str, type[BaseModel]]`` with set-up field descriptors.

    :param model_defs: model definition classes; ``base`` is auto-injected if
        absent.
    :param db_name: fake database name (default ``":memory:"``).
    """

    def __init__(
        self,
        model_defs: Iterable[type[BaseModel]],
        *,
        db_name: str = ":memory:",
    ) -> None:
        self.db_name = db_name
        self.models: dict[str, type[BaseModel]] = {}

        # Attributes accessed by registration._setup() and _setup_fields().
        # Setting _init_modules=False skips manual (Studio/custom) field
        # loading.  Empty dicts for translated/company_dependent fields
        # skip the database-state patching that prevents data loss during
        # module upgrades — irrelevant for testing.
        self._init_modules = False
        self._database_translated_fields: dict[str, str] = {}
        self._database_company_dependent_fields: dict[str, str] = {}
        self.many2many_relations: Collector = Collector()
        self.field_setup_dependents: Collector = Collector()
        self.many2one_company_dependents: Collector = Collector()

        # Field dependency tracking — same interface as the real
        # Registry.field_depends / field_depends_context properties,
        # which delegate to model_graph._depends / _depends_context.
        self._field_depends: dict = {}
        self._field_depends_context: dict = {}

        # ormcache support — the decorator accesses pool._Registry__caches
        # (name-mangled) to store method results.  defaultdict(dict) gives
        # each cache name an auto-created dict (no LRU eviction needed in
        # tests — datasets are small).
        self._Registry__caches: dict[str, dict] = defaultdict(dict)

        # Registry-loading state — True means "fully loaded, normal operation".
        # Checked by _prepare_create_values to allow/disallow log_access fields.
        self.ready = True

        # Domain optimizer checks which fields have NOT NULL constraints.
        # Populated during _build after field setup.
        self.not_null_fields: set = set()

        # DB-only hooks — no-ops in test registry.  Model field setup code
        # calls these to register foreign keys, constraints, and post-init
        # callbacks.  They're only meaningful for real database registries.
        self.has_trigram = False

        self._build(list(model_defs))

    # Mapping protocol

    def __getitem__(self, model_name: str) -> type[BaseModel]:
        return self.models[model_name]

    def __contains__(self, model_name: object) -> bool:
        return model_name in self.models

    def __iter__(self):
        return iter(self.models)

    def __len__(self):
        return len(self.models)

    # Registry-compatible mutation (used by add_to_registry)
    def __setitem__(self, model_name: str, model: type[BaseModel]) -> None:
        self.models[model_name] = model

    def __delitem__(self, model_name: str) -> None:
        del self.models[model_name]

    # Registry-compatible properties

    @property
    def field_depends(self) -> dict:
        """Field → tuple of dependency field names."""
        return self._field_depends

    @property
    def field_depends_context(self) -> dict:
        """Field → tuple of context key names."""
        return self._field_depends_context

    @functools.cached_property
    def field_computed(self) -> dict:
        """Map each computed field to its co-computed fields.

        Like :attr:`Registry.field_computed`: fields sharing a ``compute``
        method are grouped so the ORM can protect them atomically.
        """
        computed: dict = {}
        for model_cls in self.models.values():
            groups: defaultdict = defaultdict(list)
            for field in model_cls._fields.values():
                if field.compute:
                    computed[field] = group = groups[field.compute]
                    group.append(field)
        return computed

    @functools.cached_property
    def field_inverses(self) -> Collector:
        """Map each relational field to its inverse fields.

        Like :attr:`Registry.field_inverses`: calls ``field.setup_inverses()``
        for every relational field.
        """
        result: Collector = Collector()
        for model_cls in self.models.values():
            for field in model_cls._fields.values():
                if field.relational:
                    try:
                        field.setup_inverses(self, result)
                    except Exception:
                        _logger.debug(
                            "setup_inverses for %s.%s failed",
                            model_cls._name,
                            field.name,
                        )
        return result

    @functools.cached_property
    def _field_triggers(self) -> dict:
        """Empty trigger map — no cascading recomputation in the test registry.

        An empty dict makes the ``_modified_trigger_loop`` fast path always
        fire, so compute methods must be called explicitly in tests.
        """
        return {}

    def is_modifying_relations(self, field) -> bool:
        """Return ``False`` — no trigger graph in the test registry."""
        return False

    def get_trigger_tree(self, fields, select=bool):
        """Return an empty trigger tree — no trigger graph in tests."""
        return {}

    def get_dependent_fields(self, field):
        """Yield nothing — no field dependency graph in tests."""
        return iter(())

    # No-op stubs for DB-only Registry methods

    def post_init(self, func, *args, **kwargs) -> None:
        """No-op — post-init callbacks are for real module loading."""

    def post_constraint(self, cr, func, key) -> None:
        """No-op — constraint callbacks need a real database."""

    def add_foreign_key(self, *args, **kwargs) -> None:
        """No-op — foreign keys need a real database."""

    def reset_changes(self) -> None:
        """No-op — change tracking is for multi-process signaling."""

    def clear_cache(self, *cache_names: str) -> None:
        """Clear ormcache entries.  Models call this after CRUD to invalidate
        cached lookups (e.g. currencies, countries).  In test registries we
        simply clear the relevant dicts in ``_Registry__caches``."""
        for _cache_name in cache_names or ("default",):
            for cache in self._Registry__caches.values():
                if cache:
                    cache.clear()

    def is_an_ordinary_table(self, model) -> bool:
        """Return ``True`` — assume all models have tables in tests."""
        return True

    @staticmethod
    def unaccent(text):
        """Identity function — no PostgreSQL unaccent in tests."""
        return text

    @staticmethod
    def unaccent_python(text):
        """Identity function — no accent removal in tests."""
        return text

    # Registry-compatible methods

    def descendants(
        self,
        model_names: Iterable[str],
        *kinds: str,
    ) -> OrderedSet:
        """Return *model_names* and all models that inherit from them.

        Implements the same BFS traversal as :meth:`Registry.descendants`.
        """
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

    # Internal: build the registry

    def _build(self, model_defs: list[type[BaseModel]]) -> None:
        """Register model definitions and set up field descriptors.

        Auto-discovers all model definitions from the same modules as the
        provided classes (via ``MetaModel._module_to_models__``), so parents,
        mixins, and extensions register in dependency order — callers only name
        the models they want to test.
        """
        from .models.metaclass import MetaModel

        # 1. Determine which modules we need (always include 'base')
        modules = {"base"}
        for cls in model_defs:
            module = getattr(cls, "_module", None)
            if module:
                modules.add(module)

        # 2. Collect all definitions from those modules in import order
        #    (respects dependencies), 'base' first.
        all_defs: list[type[BaseModel]] = []
        seen_ids: set[int] = set()

        for module in sorted(modules, key=lambda m: (m != "base", m)):
            for cls in MetaModel._module_to_models__.get(module, []):
                if id(cls) not in seen_ids:
                    seen_ids.add(id(cls))
                    all_defs.append(cls)

        # 3. Add user-provided classes not already covered (e.g. _register=False
        #    or from unregistered modules)
        for cls in model_defs:
            if id(cls) not in seen_ids:
                seen_ids.add(id(cls))
                all_defs.append(cls)

        # 4. Ensure 'base' is present — fall back to _TestBase if not imported
        has_base = any(getattr(cls, "_name", None) == "base" for cls in all_defs)
        if not has_base:
            all_defs.insert(0, _TestBase)

        # 5. Stable sort: 'base'-named models first (root of all models)
        all_defs.sort(
            key=lambda c: 0 if getattr(c, "_name", "") == "base" else 1,
        )

        # 6. Register each definition class (creates registry model classes)
        for model_def in all_defs:
            registration.add_to_registry(self, model_def)

        # 7. Create a temporary Environment for field setup
        cr = InMemoryCursor(self)
        from .runtime.environment import Environment

        env = Environment(cr, SUPERUSER_ID, {})

        # 8. Prepare → setup → setup_fields (simplified _setup_models__)
        model_classes = list(self.models.values())

        for model_cls in model_classes:
            registration._prepare_setup(model_cls)

        for model_cls in model_classes:
            registration._setup(model_cls, env)

        for model_cls in model_classes:
            self._setup_fields_lenient(model_cls, env)

        # 9. Resolve field dependencies (for cache_key / recomputation)
        for model_cls in self.models.values():
            model = model_cls(env, (), ())
            for field in model._fields.values():
                try:
                    depends, depends_context = field.get_depends(model)
                    self._field_depends[field] = tuple(depends)
                    self._field_depends_context[field] = tuple(depends_context)
                except Exception:
                    self._field_depends[field] = ()
                    self._field_depends_context[field] = ()

        # 10. Populate not_null_fields (for domain optimizer)
        for model_cls in self.models.values():
            if model_cls._auto and not model_cls._abstract:
                for field in model_cls._fields.values():
                    if field.name == "id" or (
                        field.column_type and field.store and field.required
                    ):
                        self.not_null_fields.add(field)

        # 11. Post-setup hooks (no-op on BaseModel, may do work on subclasses)
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
        """Set up field descriptors, tolerating missing comodels.

        Unlike :func:`registration._setup_fields` (which raises on any
        non-manual error), this catches exceptions and marks the field
        ``_setup_done = True``, so a missing comodel only fails if the field
        is later accessed in a test.
        """
        model = model_cls(env, (), ())
        for name, field in model_cls._fields.items():
            try:
                field.setup(model)
            except Exception:
                _logger.debug(
                    "Field %s.%s setup incomplete (missing comodel?); field will raise if accessed in test",
                    model_cls._name,
                    name,
                )
                field._setup_done = True
            else:
                # Track company-dependent Many2one fields (mirrors _setup_fields)
                if field.type == "many2one" and field.company_dependent:
                    model_cls.pool.many2one_company_dependents.add(
                        field.comodel_name,
                        field,
                    )


# model_test_env — convenience context manager


@contextmanager
def model_test_env(
    *model_classes: type[BaseModel],
    registry: ModelRegistry | None = None,
    db_name: str = ":memory:",
):
    """Yield a database-free :class:`Environment` for testing model methods.

    Builds a :class:`ModelRegistry` and a fresh :class:`InMemoryCursor` with a
    :class:`DictBackend`. CRUD dispatches to the in-memory backend; compute
    methods, field access, and ``filtered``/``mapped``/``sorted`` work as in
    production. To reuse a registry across tests, pass ``registry=``.

    :param model_classes: model definition classes (``base`` auto-injected);
        ignored when *registry* is given.
    :param registry: pre-built :class:`ModelRegistry` to reuse; each call still
        gets a fresh cursor/storage, so tests stay isolated.
    :param db_name: fake database name (default ``":memory:"``).
    """
    if registry is None:
        registry = ModelRegistry(model_classes, db_name=db_name)

    # Clear ormcaches: a reused registry may hold results keyed to record IDs
    # from a previous DictBackend.
    for cache in registry._Registry__caches.values():
        cache.clear()

    # Clear cached_property values referencing old Transaction data.
    for attr in ("_field_triggers",):
        with suppress(AttributeError):
            delattr(registry, attr)

    cr = InMemoryCursor(registry)

    # Pre-seed minimal records so env.user / env.company resolve: many methods
    # access env.company (via ormcache keys) → env.user.company_id → DictBackend.
    _seed_fixtures(cr.storage, registry)

    from .runtime.environment import Environment

    env = Environment(cr, SUPERUSER_ID, {})
    yield env


def _seed_fixtures(storage: DictBackend, registry: ModelRegistry) -> None:
    """Insert minimal records into *storage* for ``env.user`` / ``env.company``.

    Satisfies the chain ``env.company → env.user.company_id → res_users id=1 →
    res_company id=1 → partner_id=1``. Without them, any method accessing
    ``env.company`` fails with a missing-record error.
    """

    def _inject(table: str, record_id: int, data: dict) -> None:
        """Insert a record with a specific ID, bypassing auto-increment."""
        data["id"] = record_id
        # put_rows advances the table's sequence past record_id, so later
        # next_id() allocations won't collide.
        storage.put_rows(table, [data])

    # Partner for the company (id=1)
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

    # Company (id=1)
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

    # Superuser (id=1 = SUPERUSER_ID)
    if "res.users" in registry:
        _inject(
            "res_users",
            1,
            {
                "name": "Admin",
                "login": "admin",
                "active": True,
                "company_id": 1,
                "company_ids": (1,),
                "partner_id": 1,
            },
        )
