import logging
import threading
import typing
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence, Set
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
    """Function-call parameters, stringifiable for display/logging.

    Positional args keep their order; keyword args are sorted by name so log
    lines from the same call site compare identically.
    """

    def __init__(self, args: list, kwargs: dict) -> None:
        self.args = args
        self.kwargs = kwargs

    def __str__(self) -> str:
        params = [repr(arg) for arg in self.args]
        params.extend(f"{key}={value!r}" for key, value in sorted(self.kwargs.items()))
        return ", ".join(params)


_PUBLIC_METHOD_CACHE: WeakKeyDictionary[type, dict[str, Callable]] = WeakKeyDictionary()


def get_public_method(model: BaseModel, name: str) -> Callable:
    """Get the public unbound method from a model.

    When the method does not exist or is inaccessible, raise appropriate errors.
    Accessible methods are public (not prefixed with ``_``) and are not
    decorated with ``@api.private``.

    Successful resolutions are memoized per model class (see
    ``_PUBLIC_METHOD_CACHE``); this runs on every RPC call, so the cache avoids
    re-walking the model's full MRO for each ``execute_kw``.
    """
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
    """Invoke the given method ``name`` on the recordset ``model``.

    Private methods cannot be called, only ones returned by `get_public_method`.

    The ``create`` arity check runs BEFORE the call.  It used to sit next to the
    ``result.id``/``result.ids`` narrowing that needs ``args[0]``, i.e. after the
    method had already run — where it was unreachable, since ``create`` is
    ``@api.model`` and so receives ``args`` untouched: an argument-less RPC
    ``create`` raised ``TypeError: create() missing 1 required positional
    argument: 'vals_list'`` from the ORM (verified) and never reached the guard.
    Checked up front, the caller gets the intended ``AccessError``.
    """
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
    """RPC entry point for the ``object`` service.

    ``dispatch_method`` is the RPC verb (``execute`` / ``execute_kw``);
    ``model_method`` is the ORM method to invoke.  The caller supplies
    ``(db, uid, passwd, model, model_method, *args)``; for ``execute_kw`` the
    last two positional args are ``(args_list, kwargs_dict)``.

    Verifies credentials (``res.users._check_uid_passwd``) inside the opened
    cursor, then hands off to ``execute_cr``.  The registry's signaling sequence
    advances on success and resets on failure — this propagates cache
    invalidations across workers.
    """
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

    thread = threading.current_thread()
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
    """Execute ``obj.method(*args, **kw)`` on a prepared cursor.

    Resets the cursor (clearing caches from any prior attempt), rebuilds the
    environment under ``uid``, and runs the call through ``retrying``.  Also
    force-evaluates any ``lazy`` values in the result before the cursor closes,
    since a lazy outliving the cursor fails to materialise for the marshaller.
    """
    cr.reset()
    env = api.Environment(cr, uid, {})
    env.transaction.default_env = env
    recs = env.get(obj)
    if recs is None:
        raise UserError(f"Object {obj} doesn't exist")
    thread = threading.current_thread()
    thread.rpc_model_method = f"{obj}.{method}"
    result = retrying(partial(call_kw, recs, method, args, kw), env)
    result = _force_lazy_values(result)
    if result is None:
        _logger.debug("The method %s of the object %s returned `None`.", method, obj)
    return result


def _force_lazy_values(result: typing.Any) -> typing.Any:
    """Force any ``lazy`` values in ``result`` before the cursor closes.

    A one-shot iterator (generator, ``map``/``filter``/``zip``, ``iter(...)``)
    is materialized to a ``list`` first — traversing it to find lazies would
    otherwise exhaust it, handing the marshaller an empty iterator.  Re-iterable
    containers are returned unchanged.

    This applies to the TOP-LEVEL result only.  A one-shot iterator NESTED inside
    a container is still exhausted by ``_force_lazy_in``'s walk (``[gen]`` comes
    back as ``[[]]``), and deliberately so: neither marshaller can serialise one
    anyway — JSON raises "Object of type generator is not JSON serializable" and
    xmlrpc "cannot marshal <class 'generator'> objects" — so such a result is
    already an error either way, and rewriting nested containers to repair it
    would cost a copy on every RPC result to change nothing observable.
    """
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
    """Recursively evaluate every ``lazy`` reachable from ``val``, in place.

    Walks the container shapes an RPC result can take — ``Mapping`` (values
    only, see below), ``Sequence`` / ``Set``, and a generic ``Iterable``
    fallback for ``dict_values`` views, generators, and ``iter()`` results.
    ``Set`` is listed explicitly because a lazy inside a ``{...}`` is reached by
    no other branch before the ``Iterable`` fallback.

    Runs on EVERY RPC result, so the scalar-leaf fast path stays first (skips
    the slower ABC ``isinstance`` chain for the common int/str/None atom) and is
    ALSO inlined at each container-iteration site below: a homogeneous scalar
    payload — the bulk of any real result, since ``search_read`` rows are dicts
    of str/int/bool/None — then costs one ``frozenset`` membership test per cell
    instead of a recursive call per cell (measured ~2x faster on a thousand-row
    read).  A non-leaf cell (nested container, ``lazy``, recordset, ``Markup``)
    still recurses, where the ``str``/``bytes``/``BaseModel`` guard catches the
    str subclasses that would otherwise recurse character-by-character forever.

    Dict KEYS are deliberately NOT walked: a ``lazy`` key cannot survive
    marshalling (JSON and XML-RPC both require string keys, and forcing a lazy
    leaves it a lazy object, not a str), so a dict carrying one fails to
    serialise whether or not the key was forced — walking keys would only run a
    doomed lazy's side effect for a result already bound to error.
    """
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
    elif isinstance(val, (Sequence, Set, Iterable)):
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
