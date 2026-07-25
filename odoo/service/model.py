import logging
import threading
import typing
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence, Set
from contextlib import suppress
from functools import partial
from weakref import WeakKeyDictionary

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

# ``retrying`` is the project-wide SQL-retry primitive (``service.transaction``);
# ``execute_cr`` runs every RPC call through it.  The PG_CONCURRENCY_* aliases
# are re-exported here because addons catch them via ``odoo.service.model``.
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


# Per-class memo of *successfully resolved* RPC methods.  ``get_public_method``
# is a pure function of ``(type(model), name)`` — the private-name/``_UNSAFE``
# check, the classmethod/staticmethod detection and the ``_api_private`` ancestor
# walk all read the class, never the recordset instance or its data — so its
# result can be cached on the class.  Keyed through a ``WeakKeyDictionary`` on the
# transient registry model class: a registry reload builds fresh classes and
# drops the old ones, so their entries are collected automatically (no manual
# invalidation, no leak across reloads).
#
# ONLY successful resolutions are cached, and deliberately so: the expensive step
# is the ``O(MRO-depth)`` ``_api_private`` walk (~100 classes deep for
# ``res.partner``), which is reached only by a real, public, callable instance
# method — exactly the cache-worthy case.  Caching the *rejection* paths instead
# would let an unauthenticated caller probe unbounded distinct fake method names
# and grow this dict without limit (a memory DoS); a rejected name simply re-runs
# the cheap early guards, same cost as before.
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
    cls = type(model)

    # The memo is trusted only while it still IS what the class resolves to.
    # It exists to skip the O(MRO-depth) ``_api_private`` walk below, not to
    # answer with a method the class no longer has: rebinding a model method on
    # a live class (``self.patch`` in a test, ``odoo.tools.patch``, any runtime
    # monkey-patch) used to leave the previous function cached here forever,
    # since nothing invalidates this dict and ``patch.stop()`` restores only the
    # class attribute.  ``addons/rpc``'s defaultdict-marshalling test patches
    # ``res.users.context_get``, and every later ``execute_kw`` for that method
    # -- in other test classes, for the rest of the process -- kept getting the
    # patched lambda back.
    #
    # Matching by identity is what makes it safe to answer before the guards
    # below: ONLY validated resolutions are ever stored (rejections deliberately
    # are not, see ``_PUBLIC_METHOD_CACHE``), and the entry is keyed by class and
    # name, so a hit means these exact checks already passed for this exact
    # function object.  ``getattr`` on a type is a C-level lookup served by
    # CPython's type attribute cache; the MRO walk is what is worth skipping,
    # and an identity hit still skips all of it.
    method = getattr(cls, name, None)
    per_class = _PUBLIC_METHOD_CACHE.get(cls)
    if per_class is None:
        per_class = _PUBLIC_METHOD_CACHE[cls] = {}
    elif method is not None and per_class.get(name) is method:
        return method

    # Built where raised, never on the hot path above: an f-string per RPC call
    # costs more than the lookup it would precede.
    if name.startswith("_") or name in _UNSAFE_ATTRIBUTES:
        raise AccessError(
            f"Private methods (such as '{model._name}.{name}') "
            f"cannot be called remotely."
        )

    if not callable(method):
        # AttributeError (not TypeError, per TRY004): RPC clients treat it as
        # the canonical "method not found" signal, uniform with
        # ``service.common.dispatch`` / ``service.db.dispatch``.
        raise AttributeError(f"The method '{model._name}.{name}' does not exist")

    if method == getattr(model, name, None):  # classmethod, staticmethod
        raise AccessError(
            f"The method '{model._name}.{name}' cannot be called remotely."
        )

    # ``__dict__.get`` (not getattr) so each class is checked only if it directly
    # defines the method — getattr would re-check every ancestor via inheritance,
    # O(MRO depth) redundant ``_api_private`` checks.
    #
    # SEMANTIC: ``_api_private`` on ANY ancestor blocks the method on every
    # subclass, even one that overrides it as public — intentional (prevents
    # accidental promotion to public), pinned by
    # ``test_api_private_blocked_when_defined_in_base_class``.  To expose it,
    # rename the public method.  ``cls.__mro__`` (cached) not ``cls.mro()``,
    # since this runs on every RPC call.
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
    """
    method = get_public_method(model, name)

    # get the records and context
    if getattr(method, "_api_model", False):
        # @api.model -> no ids
        recs = model
    else:
        # A non-@api.model method (search, write, unlink, …) needs ids as
        # args[0].  Reject empty args explicitly for a clear AccessError instead
        # of an opaque IndexError from the unpack below.
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
        # ``create`` is @api.model, so ``args`` is un-shifted and ``args[0]`` is
        # the vals dict / list of vals dicts.  Empty args means a malformed RPC
        # call; raise instead of the bare IndexError below.
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
    # Validate the verb before unpacking ``params`` so an unknown method raises
    # ``AttributeError`` (uniform with common/db dispatch) rather than a
    # ``ValueError`` from the unpack on a short call.
    if dispatch_method not in ("execute", "execute_kw"):
        raise AttributeError(f"Method not found: {dispatch_method}")
    if len(params) < 5:
        # Typed error for a stable surface: TypeError for argument-count,
        # AttributeError for unknown verbs, AccessDenied for credentials.
        raise TypeError(
            f"{dispatch_method} requires at least 5 positional arguments "
            f"(db, uid, passwd, model, method); got {len(params)}."
        )
    db, uid, passwd, model, model_method, *args = params
    # Require an exact int for ``uid``.  ``bool`` is an int subclass
    # (``int(True) == 1`` → admin), and a float would silently truncate
    # (``int(1.9) == 1``); the credential check still applies (not an
    # escalation), but a truncating/aliasing uid has no legitimate use.
    if not isinstance(uid, int) or isinstance(uid, bool):
        raise TypeError(f"uid must be an integer (got {uid!r})")
    if not passwd:
        raise AccessDenied
    # access checked once we open a cursor

    thread = threading.current_thread()
    thread.dbname = db
    thread.uid = uid
    registry = Registry(db).check_signaling()
    try:
        if dispatch_method == "execute":
            kw = {}
        else:  # "execute_kw" — guarded by the upfront verb check above
            # accept: (args, kw=None)
            if len(args) == 1:
                args += ({},)
            elif len(args) != 2:
                # Typed error for (0) or (3+) args instead of a ``ValueError:
                # not enough/too many values`` from the unpack.
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
        # No ``signal_changes()`` here: ``retrying`` (inside ``execute_cr``)
        # already commits and signals on success.  The failure path below still
        # needs ``reset_changes`` — that's where ``retrying`` re-raised.
    except Exception:
        # Suppress reset_changes failures so the original exception propagates:
        # ``reset_changes`` opens a fresh cursor that can raise PoolError on a
        # dropped DB / saturated pool, shadowing the user-facing error.
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
    # log_request`` runs after the app returns, so clearing it here would empty
    # it before werkzeug logs it.  ``Application.__call__`` resets it at the
    # start of every request — the only correct cleanup point.
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
    # ``lazy`` is excluded explicitly: it proxies ``__iter__``/``__next__`` to
    # the value it wraps, so it satisfies the ``Iterator`` ABC structurally
    # whatever that value turns out to be — including a plain int, where
    # ``list()`` raises "'int' object is not iterable".  A lazy is a proxy, not
    # a one-shot iterator; ``_force_lazy_in`` forces it and recurses into the
    # forced value, so it needs no materialization here.  Mirrors that
    # function's ordering, where the ``lazy`` test likewise precedes the
    # container tests.
    if not isinstance(result, lazy) and isinstance(result, Iterator):
        result = list(result)
    try:
        _force_lazy_in(result)
    except RecursionError:
        # The walk recurses per container level, so a result that is cyclic or
        # nested past the interpreter recursion limit blows the stack here.
        # ``_force_lazy_in`` exists only to keep a ``lazy`` from outliving the
        # cursor; such a pathological result is already unmarshallable (json:
        # "Circular reference detected"; xmlrpc: a recursion/type error), so let
        # the marshaller surface its own, clearer error rather than a confusing
        # ``RecursionError`` from deep in this traversal.  Kept a zero-cost
        # ``try`` on the RPC hot path (CPython raises this only on the rare
        # pathological input) instead of a cycle-tracking ``seen`` set, which
        # measured ~14% slower on every result.
        _logger.warning(
            "RPC result is cyclic or nested too deep to force lazies; "
            "leaving it to the marshaller",
            exc_info=True,
        )
    return result


# Exact scalar leaf types: never a ``lazy`` and never a container.  A large
# ``search_read`` result is overwhelmingly these, and an exact-class test here
# short-circuits the much slower ABC ``isinstance`` chain below for the common
# atom.  Membership is by identity, so an ``int`` subclass still falls through.
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
        # Recurse into the forced value: a lazy can wrap a container or another
        # lazy, whose inner lazies would otherwise survive past the cursor.
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
