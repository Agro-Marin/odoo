import functools
import logging
import time
import typing
from collections import defaultdict
from collections.abc import Collection, Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from weakref import ref as weakref_ref

from odoo_rust import rows_to_dicts as _rows_to_dicts
from psycopg import ProgrammingError

from odoo.db import BaseCursor
from odoo.exceptions import AccessError, UserError
from odoo.libs.datetime import timezone as get_timezone
from odoo.libs.datetime import utc
from odoo.tools import (
    SQL,
    OrderedSet,
    clean_context,
    frozendict,
    reset_cached_properties,
)
from odoo.tools.misc import ReadonlyDict
from odoo.tools.translate import (
    LazyGettext,
    get_translated_module,
    get_translation,
)

from ..primitives import SUPERUSER_ID
from .registry import Registry
from .transaction import Transaction

if typing.TYPE_CHECKING:
    from datetime import tzinfo

    from .._typing import BaseModel, Field
    from ..components.core import OrmCore
    from ..primitives import IdType
    from .backend import StorageBackend

    M = typing.TypeVar("M", bound=BaseModel)

_logger = logging.getLogger("odoo.api")
_orm_cache = logging.getLogger("odoo.orm.cache")


class Environment(Mapping[str, "BaseModel"]):
    cr: BaseCursor
    uid: int
    context: frozendict
    su: bool
    transaction: Transaction

    def __new__(cls, cr: BaseCursor, uid: int, context: dict, su: bool = False):
        if not isinstance(cr, BaseCursor):
            raise TypeError(
                f"Environment(cr=...) expected BaseCursor, got {type(cr).__name__}"
            )
        if isinstance(uid, bool):
            raise TypeError(
                f"Environment(uid=...) expected int, None or a request "
                f"placeholder, got bool ({uid!r})"
            )
        if uid == SUPERUSER_ID:
            su = True

        transaction = cr.transaction
        if transaction is None:
            transaction = cr.transaction = Transaction(Registry(cr.dbname))

        _last_ref = transaction._last_env
        _last = _last_ref() if _last_ref is not None else None
        if (
            _last is not None
            and _last.cr is cr
            and _last.uid == uid
            and _last.su == su
            and (_last.context is context or _last.context == context)
        ):
            return _last
        frozen_context = (
            context if isinstance(context, frozendict) else frozendict(context)
        )
        envs = transaction.envs
        env = envs.lookup(envs.key(uid, su, frozen_context))
        if env is not None and env.cr is cr:
            transaction._last_env = weakref_ref(env)
            return env

        self = object.__new__(cls)
        self.cr, self.uid, self.su = cr, uid, su
        self.context = frozen_context
        self.transaction = transaction

        envs.add(self)
        transaction._last_env = weakref_ref(self)
        if transaction.default_env is None and uid and isinstance(uid, int):
            transaction.default_env = self
        return self

    def __setattr__(self, name: str, value: typing.Any) -> None:
        if name in vars(self):
            raise AttributeError(
                f"Attribute {name!r} is read-only, call `env()` instead"
            )
        return super().__setattr__(name, value)

    def __contains__(self, model_name) -> bool:
        return model_name in self.registry

    def __getitem__(self, model_name: str) -> BaseModel:
        rs = object.__new__(self.registry[model_name])
        rs.env = self
        rs._ids = ()
        rs._prefetch_ids = ()
        return rs

    def __iter__(self):
        return iter(self.registry)

    def __len__(self):
        return len(self.registry)

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other

    def __hash__(self):
        return object.__hash__(self)

    def __call__(
        self,
        cr: BaseCursor | None = None,
        user: IdType | BaseModel | None = None,
        context: dict | None = None,
        su: bool | None = None,
    ) -> Environment:
        cr = self.cr if cr is None else cr
        uid = self.uid if user is None else int(user)
        if context is None:
            context = (
                clean_context(self.context) if su and not self.su else self.context
            )
        su = (user is None and self.su) if su is None else su
        return Environment(cr, uid, context, su)

    @typing.overload
    def ref(
        self, xml_id: str, raise_if_not_found: typing.Literal[True] = True
    ) -> BaseModel: ...

    @typing.overload
    def ref(
        self, xml_id: str, raise_if_not_found: typing.Literal[False]
    ) -> BaseModel | None: ...

    def ref(self, xml_id: str, raise_if_not_found: bool = True) -> BaseModel | None:
        res_model, res_id = self["ir.model.data"]._xmlid_to_res_model_res_id(
            xml_id, raise_if_not_found=raise_if_not_found
        )

        if res_model and res_id:
            record = self[res_model].browse(res_id)
            ref_cache = self.transaction._ref_cache
            cache_key = (res_model, res_id)
            if ref_cache.get(cache_key) or record.exists():
                ref_cache[cache_key] = True
                return record
            if raise_if_not_found:
                raise ValueError(
                    f"No record found for unique ID {xml_id}. It may have been deleted."
                )
        return None

    def is_superuser(self) -> bool:
        return self.su

    def is_admin(self) -> bool:
        return self.su or self.user._is_admin()

    def is_system(self) -> bool:
        return self.su or self.user._is_system()

    @functools.cached_property
    def registry(self) -> Registry:
        return self.transaction.registry

    @functools.cached_property
    def cache(self):
        return self.transaction.cache

    @functools.cached_property
    def _core(self) -> OrmCore:
        return self.transaction.core

    @property
    def backend(self) -> StorageBackend:
        return self.transaction.backend

    @functools.cached_property
    def user(self) -> BaseModel:
        return self(su=True)["res.users"].browse(self.uid)

    @functools.cached_property
    def _ir_defaults(self) -> BaseModel:
        return self["ir.default"].with_user(SUPERUSER_ID).with_company(self.company)

    @functools.cached_property
    def company(self) -> BaseModel:
        company_ids = self.context.get("allowed_company_ids", [])
        if company_ids:
            if not self.su:
                user_company_ids = self.user._get_company_ids()
                if set(company_ids) - set(user_company_ids):
                    raise AccessError(
                        self._("Access to unauthorized or invalid companies.")
                    )
            return self["res.company"].browse(company_ids[0])
        return self.user.company_id.with_env(self)

    @functools.cached_property
    def companies(self) -> BaseModel:
        company_ids = self.context.get("allowed_company_ids", [])
        if company_ids:
            if not self.su and set(company_ids) - set(self.user._get_company_ids()):
                raise AccessError(
                    self._("Access to unauthorized or invalid companies.")
                )
            return self["res.company"].browse(company_ids)
        return self["res.company"].browse(self.user._get_company_ids())

    @functools.cached_property
    def tz(self) -> tzinfo:
        tz_name = self.context.get("tz") or self.user.tz
        if tz_name:
            try:
                return get_timezone(tz_name)
            except Exception:
                _logger.debug("Invalid timezone %r", tz_name, exc_info=True)
        return utc

    @functools.cached_property
    def lang(self) -> str | None:
        lang = self.context.get("lang")
        if lang and lang != "en_US" and not self["res.lang"]._get_data(code=lang):
            raise UserError(f"Invalid language code: {lang}")
        return lang or None

    @functools.cached_property
    def _lang(self) -> str:
        context = self.context
        lang = self.lang or "en_US"
        if context.get("edit_translations") or context.get("check_translations"):
            lang = "_" + lang
        return lang

    def _(self, source: str | LazyGettext, *args, **kwargs) -> str:
        lang = self.lang or "en_US"
        if isinstance(source, str):
            if args and kwargs:
                raise TypeError("Use args or kwargs, not both")
            format_args = args or kwargs
        elif isinstance(source, LazyGettext):
            if args or kwargs:
                raise TypeError("All args should come from the lazy text")
            return source._translate(lang)
        else:
            raise TypeError(f"Cannot translate {source!r}")
        if lang == "en_US":
            return get_translation("base", "en_US", source, format_args)
        try:
            module = get_translated_module(2)
            return get_translation(module, lang, source, format_args)
        except Exception:
            _logger.debug(
                'translation went wrong for "%r", skipped',
                source,
                exc_info=True,
            )
        return source

    def clear(self) -> None:
        reset_cached_properties(self)
        self.transaction.clear()

    def invalidate_all(self, flush: bool = True) -> None:
        if flush:
            self.flush_all()
        self.transaction.invalidate_field_data()

    def flush_all(self) -> None:
        _debug = _orm_cache.isEnabledFor(logging.DEBUG)
        if _debug:
            _t0 = time.perf_counter()

        def recompute_fn(field):
            self[field.model_name]._recompute_field(field)

        def flush_fn(model_names):
            with self.cr.pipeline():
                for model_name in model_names:
                    self[model_name].flush_model()

        result = self.transaction.unit_of_work.run_flush_loop(recompute_fn, flush_fn)

        if not result.converged:
            remaining = result.stalled_fields
            if self.context.get("tolerant_recompute"):
                _logger.error(
                    "flush_all() did not converge after %d iterations. "
                    "Stalled fields: %s (tolerant mode, continuing)",
                    result.iterations,
                    remaining,
                )
            else:
                raise RuntimeError(
                    f"flush_all() did not converge after "
                    f"{result.iterations} iterations.  "
                    f"Stalled fields: {remaining}\n\n"
                    f"This indicates a circular compute or flush dependency.  "
                    f"Use context key 'tolerant_recompute' to suppress."
                )

        if _debug:
            _t_end = time.perf_counter()
            _orm_cache.debug(
                "[%.3f ms] flush_all: %d iterations",
                (_t_end - _t0) * 1000,
                result.iterations,
            )

    def is_protected(self, field: Field, record: BaseModel) -> bool:
        return self._core.is_protected(field, record.id)

    def protected(self, field: Field) -> BaseModel:
        return self[field.model_name].browse(self._core.protected_ids(field))

    @typing.overload
    def protecting(
        self, what: Collection[Field], records: BaseModel
    ) -> typing.ContextManager[None]: ...

    @typing.overload
    def protecting(
        self, what: Collection[tuple[Collection[Field], BaseModel]]
    ) -> typing.ContextManager[None]: ...

    @contextmanager
    def protecting(self, what, records=None) -> Iterator[None]:
        if not what:
            yield
            return
        core = self._core
        try:
            core.push_protection()
            if records is not None:
                ids = frozenset(records._ids)
                for field in what:
                    core.protect(field, ids)
            else:
                ids_by_field = defaultdict(list)
                for fields, what_records in what:
                    for field in fields:
                        ids_by_field[field].extend(what_records._ids)
                for field, rec_ids in ids_by_field.items():
                    core.protect(field, frozenset(rec_ids))
            yield
        finally:
            core.pop_protection()

    def fields_to_compute(self) -> Collection[Field]:
        return self._core.pending_fields()

    def records_to_compute(self, field: Field) -> BaseModel:
        return self[field.model_name].browse(self._core.pending_ids(field))

    def is_to_compute(self, field: Field, record: BaseModel) -> bool:
        return self._core.is_pending(field, record.id)

    def not_to_compute(self, field: Field, records: BaseModel) -> BaseModel:
        pending = self._core.pending_ids(field)
        return records.browse(id_ for id_ in records._ids if id_ not in pending)

    def add_to_compute(self, field: Field, records: BaseModel) -> None:
        if not records:
            return
        assert field.store and field.compute, (
            "Cannot add to recompute no-store or no-computed field"
        )
        self._core.schedule(field, records._ids)

    def remove_to_compute(self, field: Field, records: BaseModel) -> None:
        if not records:
            return
        self._core.mark_done(field, records._ids)

    def cache_key(self, field: Field) -> typing.Any:

        def get(key, get_context=self.context.get):
            if key == "company":
                return self.company.id
            elif key == "uid":
                return self.uid if field.compute_sudo else (self.uid, self.su)
            elif key == "lang":
                return get_context("lang") or "en_US"
            elif key == "active_test":
                return get_context(
                    "active_test", field.context.get("active_test", True)
                )
            elif key.startswith("bin_size"):
                return bool(get_context(key))
            else:
                val = get_context(key)
                if type(val) is list:
                    val = tuple(val)
                try:
                    hash(val)
                except TypeError:
                    raise TypeError(
                        "Can only create cache keys from hashable values, "
                        f"got non-hashable value {val!r} at context key {key!r} "
                        f"(dependency of field {field})"
                    ) from None
                else:
                    return val

        return tuple(get(key) for key in self._field_depends_context[field])

    @functools.cached_property
    def _field_cache_memo(
        self,
    ) -> dict[Field, MutableMapping[IdType, typing.Any]]:
        return {}

    @functools.cached_property
    def _context_defaults(self) -> Mapping[str, typing.Any]:
        return ReadonlyDict(
            {
                key[8:]: value
                for key, value in self.context.items()
                if key.startswith("default_")
            }
        )

    @functools.cached_property
    def _field_depends_context(self):
        return self.registry.field_depends_context

    def flush_query(self, query: SQL) -> None:
        fields_to_flush = tuple(query.to_flush)
        if not fields_to_flush:
            return

        first = fields_to_flush[0]
        if len(fields_to_flush) == 1:
            self[first.model_name].flush_model([first.name])
            return
        first_model = first.model_name
        if all(f.model_name == first_model for f in fields_to_flush):
            self[first_model].flush_model([f.name for f in fields_to_flush])
            return

        fnames_to_flush = defaultdict[str, OrderedSet[str]](OrderedSet)
        for field in fields_to_flush:
            fnames_to_flush[field.model_name].add(field.name)
        for model_name, field_names in fnames_to_flush.items():
            self[model_name].flush_model(field_names)

    def execute_query(self, query: SQL) -> list[tuple]:
        if not isinstance(query, SQL):
            raise TypeError(f"execute_query expected SQL, got {type(query).__name__}")
        self.flush_query(query)
        self.cr.execute(query)
        try:
            return self.cr.fetchall()
        except ProgrammingError as exc:
            if exc.sqlstate is not None:
                raise
            return []

    def execute_query_dict(self, query: SQL) -> list[dict]:
        rows = self.execute_query(query)
        if not rows:
            return []
        description = self.cr.description
        if description is None:
            raise RuntimeError(
                "No cr.description, the executed query does not return a table."
            )
        cols = tuple(col.name for col in description)
        return _rows_to_dicts(cols, rows)
