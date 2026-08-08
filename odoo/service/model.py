import logging
import typing
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
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
    def __init__(self, args: list, kwargs: dict) -> None:
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

    method = getattr(cls, name, None)
    per_class = _PUBLIC_METHOD_CACHE.get(cls)
    if per_class is None:
        per_class = _PUBLIC_METHOD_CACHE[cls] = {}
    elif method is not None and per_class.get(name) is method:
        return method

    if name.startswith("_") or name in _UNSAFE_ATTRIBUTES:
        raise AccessError(
            f"Private methods (such as '{model._name}.{name}') "
            f"cannot be called remotely."
        )

    if not callable(method):
        raise AttributeError(f"The method '{model._name}.{name}' does not exist")

    if method == getattr(model, name, None):
        raise AccessError(
            f"The method '{model._name}.{name}' cannot be called remotely."
        )

    for mro_cls in cls.__mro__:
        if not (cla_method := mro_cls.__dict__.get(name)):
            continue
        if getattr(cla_method, "_api_private", False):
            raise AccessError(
                f"Private methods (such as '{model._name}.{name}') "
                f"cannot be called remotely."
            )

    per_class[name] = method
    return method


def call_kw(model: BaseModel, name: str, args: list, kwargs: Mapping) -> typing.Any:
    method = get_public_method(model, name)

    if name == "create" and not args:
        raise AccessError(
            f"Method '{model._name}.create' requires a vals dict or list "
            f"of vals dicts as its first positional argument."
        )

    if getattr(method, "_api_model", False):
        recs = model
    else:
        if not args:
            raise AccessError(
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
        result = result.id if isinstance(args[0], Mapping) else result.ids
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
        raise UserError(f"Object {obj} doesn't exist")
    thread = current_worker_thread()
    thread.rpc_model_method = f"{obj}.{method}"
    result = retrying(partial(call_kw, recs, method, args, kw), env)
    result = _force_lazy_values(result)
    if result is None:
        _logger.debug("The method %s of the object %s returned `None`.", method, obj)
    return result


def _force_lazy_values(result: typing.Any) -> typing.Any:
    if not isinstance(result, lazy) and isinstance(result, Iterator):
        result = list(result)
    try:
        _force_lazy_in(result)
    except RecursionError:
        _logger.warning(
            "RPC result is cyclic or nested too deep to force lazies; "
            "leaving it to the marshaller",
            exc_info=True,
        )
    return result


_SCALAR_LEAF_TYPES = frozenset({int, float, bool, str, bytes, type(None)})


def _force_lazy_in(val: typing.Any) -> None:
    if val.__class__ in _SCALAR_LEAF_TYPES:
        return
    if isinstance(val, lazy):
        _force_lazy_in(val._value)
        return
    if isinstance(val, (str, bytes, BaseModel)):
        return
    if isinstance(val, Mapping):
        for value in val.values():
            if value.__class__ not in _SCALAR_LEAF_TYPES:
                _force_lazy_in(value)
    elif isinstance(val, (Sequence, AbstractSet, Iterable)):
        for item in val:
            if item.__class__ not in _SCALAR_LEAF_TYPES:
                _force_lazy_in(item)


__all__ = (
    "PG_CONCURRENCY_ERRORS_TO_RETRY",
    "PG_CONCURRENCY_EXCEPTIONS_TO_RETRY",
    "Params",
    "call_kw",
    "dispatch",
    "execute_cr",
    "get_public_method",
)
