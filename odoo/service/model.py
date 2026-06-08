import logging
import threading
import typing
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence, Set
from contextlib import suppress
from functools import partial

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

# ``retrying`` and the PG-concurrency constants live in ``service.transaction``
# (extracted because six of seven callers are HTTP/websocket — naming this
# module ``model`` overstated its scope).  Re-exported here so the legacy
# ``from odoo.service.model import retrying`` import keeps working.
from .transaction import (
    MAX_TRIES_ON_CONCURRENCY_FAILURE,
    PG_CONCURRENCY_ERRORS_TO_RETRY,
    PG_CONCURRENCY_EXCEPTIONS_TO_RETRY,
    retrying,
)

if typing.TYPE_CHECKING:
    from odoo.db import BaseCursor

_logger = logging.getLogger(__name__)


class Params:
    """Representation of parameters to a function call that can be stringified for display/logging.

    Positional args are rendered in their original order (position is semantic).
    Keyword args are sorted by name so successive log lines with the same call
    site compare identically regardless of Python's dict ordering.
    """

    def __init__(self, args: list, kwargs: dict) -> None:
        self.args = args
        self.kwargs = kwargs

    def __str__(self) -> str:
        params = [repr(arg) for arg in self.args]
        params.extend(f"{key}={value!r}" for key, value in sorted(self.kwargs.items()))
        return ", ".join(params)


def get_public_method(model: BaseModel, name: str) -> Callable:
    """Get the public unbound method from a model.

    When the method does not exist or is inaccessible, raise appropriate errors.
    Accessible methods are public (in sense that python defined it:
    not prefixed with "_") and are not decorated with `@api.private`.
    """
    assert isinstance(model, BaseModel)
    e = f"Private methods (such as '{model._name}.{name}') cannot be called remotely."
    if name.startswith("_") or name in _UNSAFE_ATTRIBUTES:
        raise AccessError(e)

    cls = type(model)
    method = getattr(cls, name, None)
    if not callable(method):
        # Use AttributeError (not TypeError per TRY004) because RPC clients
        # treat AttributeError as the canonical "method not found" signal —
        # see ``service.common.dispatch`` and ``service.db.dispatch`` for the
        # uniform error class.  The not-callable case (a public attribute on
        # the model that isn't a method) is rare enough to merge into the
        # same surface.
        raise AttributeError(f"The method '{model._name}.{name}' does not exist")  # noqa: TRY004

    if method == getattr(model, name, None):  # classmethod, staticmethod
        raise AccessError(
            f"The method '{model._name}.{name}' cannot be called remotely."
        )

    # Use __dict__.get instead of getattr to avoid re-checking inherited methods:
    # getattr() returns non-None for every ancestor class (via inheritance), causing
    # O(MRO depth) redundant _api_private checks on the same function object.
    # __dict__.get returns non-None only for classes that directly define the method.
    #
    # SEMANTIC: ``_api_private`` set on ANY ancestor class blocks the method on
    # every subclass, even when the subclass overrides it with a public version.
    # This is intentional — preventing accidental promotion to public is part of
    # the security model — and is pinned by ``test_api_private_blocked_when_defined_in_base_class``
    # in tests/service/test_model.py. To override a private method as public,
    # rename it (give the public method a different name).
    for mro_cls in cls.mro():
        if not (cla_method := mro_cls.__dict__.get(name)):
            continue
        if getattr(cla_method, "_api_private", False):
            raise AccessError(e)

    return method


def call_kw(model: BaseModel, name: str, args: list, kwargs: Mapping) -> typing.Any:
    """Invoke the given method ``name`` on the recordset ``model``.

    Private methods cannot be called, only ones returned by `get_public_method`.
    """
    method = get_public_method(model, name)

    # get the records and context
    if getattr(method, "_api_model", False):
        # @api.model -> no ids
        recs = model
    else:
        # A non-@api.model method (search, write, unlink, …) needs an ids
        # argument as args[0].  Reject the empty-args case explicitly so
        # the failure mode is a clear AccessError instead of an opaque
        # ``IndexError: list index out of range`` from the unpack below.
        if not args:
            raise AccessError(
                f"Method '{model._name}.{name}' requires record ids as its "
                f"first positional argument."
            )
        ids, args = args[0], args[1:]
        recs = model.browse(ids)

    # altering kwargs is a cause of errors, for instance when retrying a request
    # after a serialization error: the retry is done without context!
    kwargs = dict(kwargs)
    context = kwargs.pop("context", None) or {}
    recs = recs.with_context(context)

    # call
    _logger.debug("call %s.%s(%s)", recs, method.__name__, Params(args, kwargs))
    result = method(recs, *args, **kwargs)

    # adapt the result
    if name == "create":
        # special case for method 'create' — ``create`` is @api.model so
        # ``args`` here is the original (un-shifted) args list and ``args[0]``
        # is the vals dict / list of vals dicts.  An empty args reaches here
        # only via a malformed RPC call (``execute_kw`` with no positional
        # args); raising avoids the bare IndexError further down.
        if not args:
            raise AccessError(
                f"Method '{model._name}.create' requires a vals dict or list "
                f"of vals dicts as its first positional argument."
            )
        result = result.id if isinstance(args[0], Mapping) else result.ids
    elif isinstance(result, BaseModel):
        result = result.ids

    return result


def dispatch(dispatch_method: str, params: Sequence) -> typing.Any:
    """XML-RPC entry point for the ``object`` service.

    Accepts ``execute`` and ``execute_kw`` as ``dispatch_method``. The caller
    supplies ``(db, uid, passwd, model, model_method, *args)``; for
    ``execute_kw`` the last two positional args are ``(args_list,
    kwargs_dict)``.

    Performs credential verification (``res.users._check_uid_passwd``) inside
    the opened cursor, then hands off to ``execute_cr``. The registry's
    signaling sequence is advanced on success and reset on failure — this is
    what propagates cache invalidations across workers.

    The two ``method`` names are deliberately distinct: ``dispatch_method``
    is the RPC verb (``execute`` / ``execute_kw``), ``model_method`` is the
    ORM method to invoke on the recordset. The legacy form used ``method``
    and ``method_`` (trailing underscore) for the same distinction, which
    misleads readers into thinking ``method_`` escapes a Python keyword.
    """
    # Validate the RPC verb FIRST so an unknown method raises
    # ``AttributeError`` uniformly with ``odoo.service.common.dispatch`` and
    # ``odoo.service.db.dispatch`` regardless of whether ``params`` is
    # well-formed.  The previous order unpacked ``params`` first, leaking a
    # ``ValueError: not enough values to unpack`` when an invalid method
    # was sent with fewer than five args.
    if dispatch_method not in ("execute", "execute_kw"):
        raise AttributeError(f"Method not found: {dispatch_method}")
    if len(params) < 5:
        # Reject malformed calls with a typed error rather than letting the
        # tuple unpack raise ``ValueError`` — callers see a stable shape:
        # ``TypeError`` for argument-count problems, ``AttributeError`` for
        # unknown verbs, ``AccessDenied`` for credential failures.
        raise TypeError(
            f"{dispatch_method} requires at least 5 positional arguments "
            f"(db, uid, passwd, model, method); got {len(params)}."
        )
    db, uid, passwd, model, model_method, *args = params
    # ``isinstance(uid, bool)`` rejection: ``int(True) == 1`` would silently
    # bind a boolean ``uid`` to user-id 1 (admin).  The credential check on
    # the next line still applies, so this isn't a privilege escalation —
    # but it's an undocumented type contract worth pinning explicitly.
    if isinstance(uid, bool):
        raise TypeError(
            f"uid must be an integer, not bool (got {uid!r})"
        )
    uid = int(uid)
    if not passwd:
        raise AccessDenied
    # access checked once we open a cursor

    threading.current_thread().dbname = db
    threading.current_thread().uid = uid
    registry = Registry(db).check_signaling()
    try:
        if dispatch_method == "execute":
            kw = {}
        else:  # "execute_kw" — guarded by the upfront verb check above
            # accept: (args, kw=None)
            if len(args) == 1:
                args += ({},)
            elif len(args) != 2:
                # Reject (0 args) and (3+ args) with a typed error so
                # malformed RPC calls produce a stable, diagnostic surface
                # rather than ``ValueError: not enough/too many values``.
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
        registry.signal_changes()
    except Exception:
        # Suppress reset_changes failures so the original exception propagates
        # cleanly: ``reset_changes`` opens a fresh cursor (registry.py:1296)
        # which can raise PoolError on a dropped DB or saturated pool, and a
        # bare call here would shadow the user-facing exception (the original
        # would survive only as ``__context__``).  Mirrors the protection
        # already in ``retrying`` (model.py inside ``except Exception:``).
        with suppress(Exception):
            registry.reset_changes()
        raise
    return res


def execute_cr(
    cr: BaseCursor, uid: int, obj: str, method: str, args: list | tuple, kw: dict
) -> typing.Any:
    """Execute ``obj.method(*args, **kw)`` on a prepared cursor.

    Resets the cursor (clears caches from any prior attempt on this
    cursor), rebuilds the environment under the user's uid, and runs the
    call through ``retrying`` so serialization failures retry with
    exponential backoff.

    Also force-evaluates any ``lazy`` values in the result before the
    cursor closes, because a lazy that lives past the cursor's lifetime
    would fail to materialise when finally accessed by the RPC marshaller.
    """
    # clean cache etc if we retry the same transaction
    cr.reset()
    env = api.Environment(cr, uid, {})
    env.transaction.default_env = env  # ensure this is the default env for the call
    recs = env.get(obj)
    if recs is None:
        raise UserError(  # pylint: disable=missing-gettext,E8507
            f"Object {obj} doesn't exist"
        )
    # The fragment must outlive the WSGI call: ``CommonRequestHandler.
    # log_request`` runs *after* the WSGI app returns its response, so any
    # post-call clear here would empty the value before werkzeug logs it.
    # ``Application.__call__`` resets ``rpc_model_method = ""`` at the
    # start of every request, which is the only correct cleanup point —
    # a non-RPC follow-up (static asset, /web GET) on the same worker
    # thread cannot inherit a stale fragment.
    thread = threading.current_thread()
    thread.rpc_model_method = f"{obj}.{method}"
    result = retrying(partial(call_kw, recs, method, args, kw), env)
    # Force evaluation of lazy values before the cursor is closed, as it
    # would error afterwards if the lazy isn't already evaluated (and cached).
    for lazy_val in _traverse_containers(result, lazy):
        lazy_val._value  # noqa: B018 — intentional attribute access to force evaluation
    if result is None:
        _logger.debug("The method %s of the object %s returned `None`.", method, obj)
    return result


def _traverse_containers(val: typing.Any, type_: type | tuple[type, ...]) -> Iterator:
    """Yield atoms filtered by ``type_``, traversing standard containers.

    Recurses into ``Mapping`` (keys and values) and ``Sequence`` / ``Set``
    elements.  ``Set`` covers both ``set`` and ``frozenset`` — without that
    branch a lazy value held inside a ``{...}`` would survive past cursor
    close and blow up when the RPC marshaller finally evaluated it.

    Falls back to a generic ``Iterable`` walk for ``dict_values``,
    generators, and plain ``iter()`` results — none of which are ``Set``
    or ``Sequence`` ABC members despite being legitimate RPC return types.
    The previous version returned ``[]`` from those, leaking lazies.

    For one-shot iterators (generators, ``iter(...)``) this consumes the
    iterator: any later call site that wanted to re-iterate gets nothing.
    The RPC marshaller materializes the result anyway (it has to serialize
    it), so the consumption is never observed in practice.
    """
    if isinstance(val, type_):
        yield val
    elif isinstance(val, (str, bytes, BaseModel)):
        return
    elif isinstance(val, Mapping):
        for k, v in val.items():
            yield from _traverse_containers(k, type_)
            yield from _traverse_containers(v, type_)
    elif isinstance(val, (Sequence, Set, Iterable)):
        for v in val:
            yield from _traverse_containers(v, type_)


__all__ = (
    "MAX_TRIES_ON_CONCURRENCY_FAILURE",  # re-export from .transaction
    "PG_CONCURRENCY_ERRORS_TO_RETRY",  # re-export from .transaction
    "PG_CONCURRENCY_EXCEPTIONS_TO_RETRY",  # re-export from .transaction
    "Params",
    "call_kw",
    "dispatch",
    "execute_cr",
    "get_public_method",
    "retrying",  # re-export from .transaction
)
