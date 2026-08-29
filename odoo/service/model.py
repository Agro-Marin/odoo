import logging
import typing
from collections.abc import (
    Callable,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSequence,
    Sequence,
)
from collections.abc import Set as AbstractSet
from contextlib import suppress
from functools import partial
from weakref import WeakKeyDictionary

import psycopg

from odoo import api
from odoo.exceptions import (
    AccessDenied,
    AccessError,
    UserError,
)
from odoo.libs.worker_thread import current_worker_thread
from odoo.models import BaseModel
from odoo.modules.registry import Registry
from odoo.tools import lazy
from odoo.tools.safe_eval import _UNSAFE_ATTRIBUTES

from ._db_helpers import rpc_db_exposed
from .transaction import (
    PG_CONCURRENCY_ERRORS_TO_RETRY,
    PG_CONCURRENCY_EXCEPTIONS_TO_RETRY,
    retrying,
)

if typing.TYPE_CHECKING:
    from odoo.db import BaseCursor

_logger = logging.getLogger(__name__)


class Params:
    def __init__(self, args: Sequence, kwargs: dict) -> None:
        self.args = args
        self.kwargs = kwargs

    def __str__(self) -> str:
        params = [repr(arg) for arg in self.args]
        params.extend(f"{key}={value!r}" for key, value in sorted(self.kwargs.items()))
        return ", ".join(params)


_PUBLIC_METHOD_CACHE: WeakKeyDictionary[type, dict[str, Callable]] = WeakKeyDictionary()


def get_public_method(model: BaseModel, name: str) -> Callable:
    assert isinstance(model, BaseModel)
    if not isinstance(name, str):
        raise AttributeError(
            f"The method {name!r} does not exist on model '{model._name}'"
        )
    cls = type(model)

    method: Callable | None = getattr(cls, name, None)
    per_class = _PUBLIC_METHOD_CACHE.get(cls)
    if per_class is None:
        per_class = _PUBLIC_METHOD_CACHE[cls] = {}
    else:
        cached = per_class.get(name)
        if cached is not None and cached is method:
            return cached

    if name.startswith("_") or name in _UNSAFE_ATTRIBUTES:
        raise AccessError(  # noqa: E8505  rejection reply to a bad RPC call
            f"Private methods (such as '{model._name}.{name}') "
            f"cannot be called remotely."
        )

    if not callable(method):
        raise AttributeError(f"The method '{model._name}.{name}' does not exist")

    if method == getattr(model, name, None):
        raise AccessError(  # noqa: E8505  rejection reply to a bad RPC call
            f"The method '{model._name}.{name}' cannot be called remotely."
        )

    for mro_cls in cls.__mro__:
        if not (cla_method := mro_cls.__dict__.get(name)):
            continue
        if getattr(cla_method, "_api_private", False):
            raise AccessError(  # noqa: E8505  rejection reply to a bad RPC call
                f"Private methods (such as '{model._name}.{name}') "
                f"cannot be called remotely."
            )

    per_class[name] = method
    return method


def call_kw(model: BaseModel, name: str, args: Sequence, kwargs: Mapping) -> typing.Any:
    method = get_public_method(model, name)
    api_model = getattr(method, "_api_model", False)

    create_vals = None

    if name == "create":
        if not args:
            raise AccessError(  # noqa: E8505  names the caller's own protocol error
                f"Method '{model._name}.create' requires a vals dict or list "
                f"of vals dicts as its first positional argument."
            )
        if not api_model:
            raise AccessError(  # noqa: E8505  addresses whoever wrote the override
                f"Method '{model._name}.create' is not declared with "
                f"@api.model_create_multi (or @api.model). An override that "
                f"drops the decorator makes call_kw treat the vals as record "
                f"ids."
            )
        create_vals = args[0]

    if api_model:
        recs = model
    else:
        if not args:
            raise AccessError(  # noqa: E8505  names the caller's own protocol error
                f"Method '{model._name}.{name}' requires record ids as its "
                f"first positional argument."
            )
        ids, args = args[0], args[1:]
        recs = model.browse(ids)

    kwargs = dict(kwargs)
    context = kwargs.pop("context", None) or {}
    recs = recs.with_context(context)

    _logger.debug("call %s.%s(%s)", recs, method.__name__, Params(args, kwargs))
    result = method(recs, *args, **kwargs)

    if name == "create":
        result = result.id if isinstance(create_vals, Mapping) else result.ids
    elif isinstance(result, BaseModel):
        result = result.ids

    return result


def dispatch(dispatch_method: str, params: Sequence) -> typing.Any:
    if dispatch_method not in ("execute", "execute_kw"):
        raise AttributeError(f"Method not found: {dispatch_method}")
    if len(params) < 5:
        raise TypeError(
            f"{dispatch_method} requires at least 5 positional arguments "
            f"(db, uid, passwd, model, method); got {len(params)}."
        )
    db, uid, passwd, model, model_method, *args = params
    if not isinstance(uid, int) or isinstance(uid, bool):
        raise TypeError(f"uid must be an integer (got {uid!r})")
    if not passwd:
        raise AccessDenied
    if not rpc_db_exposed(db):
        _logger.warning(
            "RPC %s refused: database %r is not exposed by this instance",
            dispatch_method,
            db,
        )
        raise AccessDenied

    thread = current_worker_thread()
    thread.dbname = db
    thread.uid = uid
    try:
        registry = Registry(db).check_signaling()
    except psycopg.errors.InvalidCatalogName as exc:
        _logger.debug("RPC %s: database %r does not exist", dispatch_method, db)
        raise AccessDenied from exc
    try:
        if dispatch_method == "execute":
            kw = {}
        else:
            if len(args) == 1:
                args += ({},)
            elif len(args) != 2:
                raise TypeError(
                    f"execute_kw requires (args, [kw]) after the credentials "
                    f"and model.method; got {len(args)} extra arguments."
                )
            args, kw = args
            if kw is None:
                kw = {}
        with registry.cursor() as cr:
            api.Environment(cr, api.SUPERUSER_ID, {})["res.users"]._check_uid_passwd(
                uid, passwd
            )
            res = execute_cr(cr, uid, model, model_method, args, kw)
    except Exception:
        with suppress(Exception):
            registry.reset_changes()
        raise
    return res


def execute_cr(
    cr: BaseCursor, uid: int, obj: str, method: str, args: list | tuple, kw: dict
) -> typing.Any:
    cr.reset()
    env = api.Environment(cr, uid, {})
    env.transaction.default_env = env
    recs = env.get(obj)
    if recs is None:
        raise UserError(  # noqa: E8505  the RPC named a model that does not exist
            f"Object {obj} doesn't exist"
        )
    thread = current_worker_thread()
    thread.rpc_model_method = f"{obj}.{method}"
    result = retrying(partial(call_kw, recs, method, args, kw), env)
    result = _force_lazy_values(result)
    if result is None:
        _logger.debug("The method %s of the object %s returned `None`.", method, obj)
    return result


def _force_lazy_values(result: typing.Any) -> typing.Any:
    try:
        return _force_lazy_in(result)
    except RecursionError:
        _logger.warning(
            "RPC result is cyclic or nested too deep to force lazies; "
            "leaving it to the marshaller",
            exc_info=True,
        )
        return result


_SCALAR_LEAF_TYPES = frozenset({int, float, bool, str, bytes, type(None)})


def _is_bare_iterator(val: typing.Any) -> bool:
    """`lazy` proxies __iter__/__next__, so isinstance(lazy_obj, Iterator) is True.

    Every place that asks "would walking this consume it?" has to exclude a
    lazy first, or the wrapper it exists to warm gets skipped as if it were a
    generator.
    """
    return not isinstance(val, lazy) and isinstance(val, Iterator)


def _forced_mapping(val: Mapping) -> Mapping:
    if isinstance(val, MutableMapping):
        for key, value in list(val.items()):
            if value.__class__ not in _SCALAR_LEAF_TYPES:
                forced = _force_lazy_in(value)
                if forced is not value:
                    val[key] = forced
        return val
    for value in val.values():
        if value.__class__ not in _SCALAR_LEAF_TYPES and not _is_bare_iterator(value):
            _force_lazy_in(value)
    return val


def _forced_sequence(val: Sequence) -> Sequence:
    if isinstance(val, MutableSequence):
        for index, item in enumerate(val):
            if item.__class__ not in _SCALAR_LEAF_TYPES:
                forced = _force_lazy_in(item)
                if forced is not item:
                    val[index] = forced
        return val
    items = [
        item if item.__class__ in _SCALAR_LEAF_TYPES else _force_lazy_in(item)
        for item in val
    ]
    if any(new is not old for new, old in zip(items, val, strict=True)):
        return tuple(items) if type(val) is tuple else type(val)(items)
    return val


def _warm_in_place(val: Iterable) -> None:
    """Walk something that cannot be rewritten: skip what walking would eat."""
    for item in val:
        if item.__class__ not in _SCALAR_LEAF_TYPES and not _is_bare_iterator(item):
            _force_lazy_in(item)


def _force_lazy_in(val: typing.Any) -> typing.Any:
    """Warm every `lazy` in the result, and materialise every iterator.

    The warming is the point: `lazy._value` runs the deferred call, and it has
    to run here, while the cursor is still open -- the marshaller renders the
    result long after `retrying()` has committed.

    Walking a container means iterating it, which for an *iterator* consumes
    it.  So an iterator is replaced by the list it yielded rather than merely
    traversed; where the container it sits in cannot be rewritten (a read-only
    mapping, a set) it is left untouched instead, which hands the marshaller an
    intact object rather than an exhausted one.

    The return value is the walked object, which is the same object except
    where an iterator had to be substituted.
    """
    if val.__class__ in _SCALAR_LEAF_TYPES:
        return val
    if isinstance(val, lazy):
        _force_lazy_in(val._value)
        return val
    if isinstance(val, (str, bytes, BaseModel)):
        return val
    if isinstance(val, Mapping):
        return _forced_mapping(val)
    if isinstance(val, Iterator):
        return [_force_lazy_in(item) for item in val]
    if isinstance(val, Sequence):
        return _forced_sequence(val)
    if isinstance(val, (AbstractSet, Iterable)):
        _warm_in_place(val)
    return val


__all__ = (
    "PG_CONCURRENCY_ERRORS_TO_RETRY",
    "PG_CONCURRENCY_EXCEPTIONS_TO_RETRY",
    "Params",
    "call_kw",
    "dispatch",
    "execute_cr",
    "get_public_method",
)
