"""ORM-level testing utilities.

:class:`InMemoryCursor` emulates a database cursor with no PostgreSQL
connection; paired with a pre-built :class:`Registry` it lets tests construct a
real :class:`Environment` to exercise compute methods, field logic, or business
rules without issuing SQL. :func:`model_test_env` builds a lightweight
:class:`ModelRegistry` from class definitions for fully DB-free testing.

For the components engine in isolation (``FieldCache`` / ``ComputeEngine`` /
``ModelGraph`` / ``UnitOfWork``), see the Tier-1 unit tests under
``odoo/orm/components/tests/``.
"""

import logging
import threading
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from operator import attrgetter
from typing import TYPE_CHECKING

from odoo.db import BaseCursor
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
from .runtime.registry import _CACHES_BY_KEY
from .runtime.transaction import Transaction

if TYPE_CHECKING:
    from .models.base import BaseModel
    from .runtime.environment import Environment
    from .runtime.registry import Registry

_logger = logging.getLogger("odoo.orm.model_test_env")


class InMemorySqlNotSupported(NotImplementedError):
    """Raised when a DB-free test hits raw SQL the in-memory tier cannot run.

    The point of failing loud (instead of returning an empty result) is to stop
    a model test from going *green while production would be red* — the central
    risk of a DB-free tier.  See :meth:`InMemoryCursor.execute`.
    """


class InMemoryRecordRulesNotSupported(NotImplementedError):
    """Raised on ``env["ir.rule"]`` access in a DB-free harness env."""


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


class _TestIrDefault(AbstractModel):
    """Minimal ``ir.default`` provider for :class:`ModelRegistry`.

    ``BaseModel.default_get`` unconditionally calls
    ``self.env["ir.default"]._get_model_defaults(model_name)`` (see
    ``models/mixins/create.py``), so *every* ``create()`` needs an
    ``ir.default`` model in the registry.  The real one lives in
    ``odoo.addons.base`` and would drag the whole framework in, defeating the
    DB-free purpose, so the harness injects this stub returning "no admin
    defaults" — exactly what an empty test database would yield.
    """

    _name = "ir.default"
    _description = "Ir Default (test stub)"
    _register = False
    _module = None

    def _get_model_defaults(self, model_name, condition=False):
        return {}


class _TestResUsers(Model):
    """Minimal ``res.users`` for :class:`ModelRegistry`.

    Every non-``_log_access = False`` model carries ``create_uid``/``write_uid``
    Many2one fields to ``res.users``; without a model behind them any write
    after ``invalidate_all()`` crashed in ``Many2one._update_inverses``
    (``KeyError: 'res.users'`` — the fields were merely *degraded*, i.e.
    triggers inert, but the descriptor machinery still resolves the comodel).
    ``_seed_fixtures`` already inserts the superuser row this stub exposes.
    Injected only when the caller does not provide a ``res.users`` model.
    """

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
        """Companies this user may act for.

        ``Environment.company`` / ``companies`` call this to authorize an
        ``allowed_company_ids`` context on a non-superuser environment, so
        without it the harness could only exercise superuser environments.
        The real ``res.users`` unions ``company_ids``; the stub has no such
        field and reports the main company alone.
        """
        return self.company_id.ids

    @api.model
    def context_get(self):
        """User context used by the translation machinery.

        ``odoo.tools.translate`` falls back to this when it cannot infer a
        language from the frame, which every ``_()`` call reached from model
        code eventually does.  Without it a DB-free test could not exercise any
        code path that builds a translated ``UserError``/``ValidationError``.
        """
        return {"lang": "en_US", "tz": False, "uid": self.env.uid}


class _TestResCompany(Model):
    """Minimal ``res.company`` backing :attr:`_TestResUsers.company_id`.

    Injected alongside the ``res.users`` stub so ``env.company`` (and with it
    ``company_dependent`` fields) works DB-free; ``_seed_fixtures`` already
    inserts the id=1 row this stub exposes. Injected only when the caller does
    not provide a ``res.company`` model.
    """

    _name = "res.company"
    _description = "Companies (test stub)"
    _register = False
    _module = None
    _log_access = False

    name = Char()
    active = Boolean(default=True)


class InMemoryCursor(BaseCursor):
    """Cursor backed by fixture data — no PostgreSQL required.

    Inherits :class:`~odoo.db.BaseCursor` for the callback containers and the
    ``flush()`` machinery (savepoints are *not* supported — like
    :meth:`rollback`, :meth:`savepoint` fails loud because :class:`DictBackend`
    keeps no snapshot to restore). :meth:`__init__` pre-builds the
    ``Transaction`` and assigns it to ``self.transaction``, so
    ``Environment.__new__`` skips ``Transaction(Registry(cr.dbname))`` and never
    opens a connection. Its :class:`DictBackend` ``storage`` makes ORM CRUD —
    row-level create/write/read/search/unlink *and* the Many2many
    relation-table reads/links/unlinks — dispatch to the in-memory backend
    instead of generating SQL, so none of it reaches this cursor.

    :param registry: pre-built model registry (e.g. ``self.env.registry``).
    :param fixtures: optional ``{query_string: rows}`` map; ``execute`` looks up
        ``str(query)`` here.  A query that is *not* registered raises
        :class:`InMemorySqlNotSupported` — the DB-free tier handles ORM CRUD in
        memory but cannot run raw SQL (e.g. ``read_group``, custom
        ``cr.execute``), and silently returning ``[]`` would give a false green.
    """

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
        """Return a registered fixture for *query*, or fail loud.

        The signature must mirror :meth:`BaseCursor.execute`, including
        ``prepare``: callers legitimately pass it (``_add_manual_models`` opts
        its ``ir_model`` SELECT out of the prepared-statement cache), and an
        override that drops the argument turns such a call into a
        ``TypeError`` here while working fine against PostgreSQL. There is no
        psycopg statement cache behind a fixture, so the value is accepted and
        ignored.

        ORM CRUD — create/write/read/search/unlink, including the Many2many
        relation-table operations — is served by the in-memory backend and
        never reaches this cursor, so any query arriving here is raw SQL a
        model method emitted itself (``read_group``, a custom ``cr.execute``,
        ...).  That SQL cannot run without PostgreSQL; returning an empty result
        silently would hand the test a *false green* — the one failure mode a
        fast tier must not introduce.  Register the expected rows via
        ``fixtures={str(query): rows}`` or move the test to a DB-backed
        ``TransactionCase``.
        """
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

    def fetchall(self) -> list[tuple]:
        """Return all rows from the last executed query."""
        return list(self._last_result)

    def fetchone(self) -> tuple | None:
        """Return the first row from the last executed query, or ``None``."""
        return self._last_result[0] if self._last_result else None

    def fetchmany(self, size: int) -> list[tuple]:
        """Return up to *size* rows from the last executed query."""
        return self._last_result[:size]

    _DICT_API_UNSUPPORTED = (
        "InMemoryCursor (DB-free model_test_env) cannot serve the dict cursor "
        "API (dictfetchone/dictfetchall): fixtures are tuple rows with no column "
        "names. Consume the registered fixture via fetchone/fetchall, or move the "
        "test to a DB-backed TransactionCase."
    )

    def dictfetchone(self) -> dict | None:
        """Return ``None`` for an empty result; fail loud if rows are present.

        Without a real cursor there is no column metadata to build a dict, so a
        populated result raises rather than silently returning ``None``.
        """
        if not self._last_result:
            return None
        raise InMemorySqlNotSupported(self._DICT_API_UNSUPPORTED)

    def dictfetchall(self) -> list[dict]:
        """Return ``[]`` for an empty result; fail loud if rows are present.

        See :meth:`dictfetchone`: a populated result cannot be returned as dicts
        and must not be silently swallowed as ``[]``.
        """
        if not self._last_result:
            return []
        raise InMemorySqlNotSupported(self._DICT_API_UNSUPPORTED)

    def now(self) -> datetime:
        """Return the transaction's timestamp as a naive UTC datetime.

        The real cursor fetches ``now()`` from PostgreSQL and caches it until
        commit/rollback (see :meth:`odoo.db.BaseCursor.now`), so every call in
        one transaction returns the *same* instant — e.g. all records created
        in a transaction share one ``create_date``.  InMemoryCursor uses the
        local clock as the source but mirrors that transaction stability by
        caching in the same ``_now`` slot; :meth:`commit` resets it, exactly
        like production.  (A fresh ``datetime.now()`` per call would let two
        creates in one transaction disagree — behaviour production never
        exhibits, a false-*red* the fast tier must not introduce.)
        """
        if self._now is None:
            self._now = datetime.now(UTC).replace(tzinfo=None)
        return self._now

    def savepoint(self, flush: bool = True):
        """Fail loud — the in-memory tier cannot implement savepoints.

        A savepoint's whole point is rolling back to its start, and
        :class:`DictBackend` keeps no snapshot to restore (same limitation as
        :meth:`rollback`).  The inherited ``BaseCursor.savepoint`` would issue
        real ``SAVEPOINT`` SQL, so it used to die in :meth:`execute` with the
        generic raw-SQL error and its register-a-fixture advice — nonsense for
        transaction control.  Raise an intentional, explanatory error instead.
        """
        raise InMemorySqlNotSupported(
            "InMemoryCursor (DB-free model_test_env) does not support "
            "savepoints: DictBackend writes are applied immediately and no "
            "snapshot exists to roll back to (same limitation as rollback()). "
            "Use a DB-backed TransactionCase to test savepoint behaviour."
        )

    @contextmanager
    def pipeline(self):
        """No-op context manager — no real connection to pipeline."""
        yield

    def commit(self) -> None:
        """Commit the in-memory transaction: flush, clear, run postcommit hooks.

        Mirrors :meth:`odoo.db.Cursor.commit` minus the SQL ``COMMIT`` (storage
        writes are immediate, so there is nothing to make durable).  A silent
        no-op here would be a false-green vector: postcommit hooks registered by
        the code under test would simply never fire.
        """
        if self._savepoint_depth:
            raise RuntimeError(
                "Cannot commit inside a savepoint! "
                "This would corrupt the savepoint's rollback state."
            )
        self.flush()
        # Mirrors Cursor.commit: bumped before the post-commit hooks run, so a
        # hook that raises is classified as "committed, hook failed" here too
        # (see retrying()).  Storage writes are already durable at this point.
        self.commit_count += 1
        self.clear()
        self._now = None
        self.prerollback.clear()
        self.postrollback.clear()
        self.postcommit.run()

    def rollback(self) -> None:
        """Fail loud — the in-memory tier cannot restore a pre-transaction state.

        :class:`DictBackend` writes are applied immediately and it keeps no
        snapshot to roll back to (its storage shape is private to the storage
        contract).  Silently doing nothing — while production discards the
        transaction's writes and runs the prerollback hooks — would hand a test
        exercising rollback behaviour a false green, so this raises instead.
        Test rollback semantics against a DB-backed ``TransactionCase``.
        """
        raise InMemorySqlNotSupported(
            "InMemoryCursor (DB-free model_test_env) cannot roll back: storage "
            "writes are applied immediately and no snapshot exists to restore. "
            "A silent no-op would diverge from production ROLLBACK (which "
            "discards the transaction's writes); use a DB-backed "
            "TransactionCase to test rollback behaviour."
        )

    def close(self) -> None:
        """No-op — there is no connection to close."""


class ModelRegistry(_RegistryFieldsMixin, Mapping):
    """Lightweight model registry built from Python class definitions.

    Satisfies the interface that :class:`Environment` and :class:`Transaction`
    need from :class:`Registry`, without database access or module loading —
    just a ``Mapping[str, type[BaseModel]]`` with set-up field descriptors.

    The field-dependency graph (``field_depends``, ``field_inverses``,
    ``field_computed``, ``_field_triggers``, trigger-tree queries) is inherited
    from the **real** :class:`_RegistryFieldsMixin` — the same code the
    production :class:`Registry` uses — so cascading recompute, inverse
    propagation and trigger resolution are exercised exactly as in production,
    not via a parallel reimplementation that could silently drift.

    :param model_defs: model definition classes; ``base`` is auto-injected if
        absent.
    :param db_name: fake database name (default ``":memory:"``).
    """

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
        """No-op — post-init callbacks are for real module loading."""

    def post_constraint(self, cr, func, key) -> None:
        """No-op — constraint callbacks need a real database."""

    def add_foreign_key(self, *args, **kwargs) -> None:
        """No-op — foreign keys need a real database."""

    def reset_changes(self) -> None:
        """No-op — change tracking is for multi-process signaling."""

    def clear_cache(self, *cache_names: str) -> None:
        """Clear the ormcache dicts for the given composite cache names.

        Mirrors :meth:`Registry.clear_cache` scaled to the harness: each name
        expands to its group of cache containers via ``_CACHES_BY_KEY`` (so
        e.g. ``"default"`` also clears ``"templates.cached_values"``), and
        dotted names are rejected exactly like production.  One divergence: a
        name outside the production map clears the container of that name —
        the harness caches are open-ended (``defaultdict``), so a test-model
        ``@ormcache(cache="custom")`` stays clearable.
        """
        for cache_name in cache_names or ("default",):
            if "." in cache_name:
                raise ValueError(
                    f"clear_cache: invalid cache name {cache_name!r} (no dots allowed)"
                )
            for container in _CACHES_BY_KEY.get(cache_name, (cache_name,)):
                self.ormcache_lrus[container].clear()

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

    def _build(self, model_defs: list[type[BaseModel]]) -> None:
        """Register model definitions and set up field descriptors.

        Auto-discovers all model definitions from the same modules as the
        provided classes (via ``MetaModel._module_to_models__``), so parents,
        mixins, and extensions register in dependency order — callers only name
        the models they want to test.
        """
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
                if field.type == "many2one" and field.company_dependent:
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
    """Yield a database-free :class:`Environment` for testing model methods.

    Builds a :class:`ModelRegistry` and a fresh :class:`InMemoryCursor` with a
    :class:`DictBackend`. CRUD dispatches to the in-memory backend; compute
    methods, field access, and ``filtered``/``mapped``/``sorted`` work as in
    production. The registry builds the real dependency graph, so **stored
    computed fields are recomputed automatically on create/write** — including
    transitive and cross-model (One2many/Many2one) cascades — without invoking
    compute methods by hand. To reuse a registry across tests, pass ``registry=``.

    :param model_classes: model definition classes (``base`` auto-injected);
        ignored when *registry* is given.
    :param registry: pre-built :class:`ModelRegistry` to reuse; each call still
        gets a fresh cursor/storage, so tests stay isolated.
    :param db_name: fake database name (default ``":memory:"``).
    :param fixtures: optional ``{str(query): rows}`` results for the raw SQL a
        model method runs (e.g. ``read_group``).  Unregistered raw SQL raises
        :class:`InMemorySqlNotSupported` rather than silently returning ``[]``.
    """
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
        if (
            field is not None
            and field.type == "many2many"
            and field.store
            and field.relation
        ):
            storage.insert_rows(
                field.relation, [field.column1, field.column2], [(1, 1)]
            )
