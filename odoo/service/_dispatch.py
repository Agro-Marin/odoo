"""One argument-validation policy for the table-driven RPC dispatchers.

``common`` and ``db`` both expose a ``{method: handler}`` table behind the single
door in ``odoo/http/helpers.py`` (``dispatch_rpc`` -> ``_get_rpc_dispatcher``),
and each had grown its own answer to "what happens when the caller sends the
wrong number of arguments":

* ``common`` had no answer.  It splatted, so an arity mistake surfaced as a bare
  ``TypeError`` from CPython -- and ``/xmlrpc/2/common`` is ``auth="none"``, so
  an unauthenticated caller was handed the internal handler's name and signature.
  Measured over the wire against a real server: ``login("db", "admin")`` came
  back as ``Fault: TypeError: exp_login() missing 1 required positional
  argument: 'password'``.
* ``db`` validated the master-password argument and then splatted the rest.

The messages this raises name the RPC method, never the ``exp_*`` function
behind it.

``model`` is deliberately NOT built on this.  It is not a handler table: its
params are a fixed positional envelope (db, uid, passwd, model, method, *args)
whose credential sits third, and its checks are protocol checks rather than
per-method arity.  Routing it through here would disguise a different protocol
as the same one.
"""

from __future__ import annotations

import annotationlib
import functools
import inspect
from collections.abc import Callable, Sequence
from typing import Any

__all__ = ("dispatch_table", "positional_bounds")


@functools.cache
def positional_bounds(handler: Callable) -> tuple[int, int | None, tuple[str, ...]]:
    """``(required, maximum, names)`` positional parameters of ``handler``.

    ``maximum`` is ``None`` when the handler takes ``*args``, i.e. unbounded.
    """
    required = 0
    maximum = 0
    names: list[str] = []
    # FORWARDREF: only the parameter kinds and defaults are read here, never the
    # annotations, and under PEP 649 evaluating a handler annotated with a
    # TYPE_CHECKING-only name would raise NameError.
    signature = inspect.signature(
        handler, annotation_format=annotationlib.Format.FORWARDREF
    )
    for param in signature.parameters.values():
        if param.kind is param.VAR_POSITIONAL:
            return required, None, tuple(names)
        if param.kind not in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
            continue
        names.append(param.name)
        maximum += 1
        if param.default is param.empty:
            required += 1
    return required, maximum, tuple(names)


def _check_arity(method: str, handler: Callable, count: int) -> None:
    required, maximum, names = positional_bounds(handler)
    if count < required:
        expected = ", ".join(names[:required])
        raise TypeError(
            f"RPC method {method!r} requires {required} positional "
            f"argument(s) ({expected}); got {count}."
        )
    if maximum is not None and count > maximum:
        raise TypeError(
            f"RPC method {method!r} takes at most {maximum} positional "
            f"argument(s); got {count}."
        )


def dispatch_table(
    method: str,
    params: Sequence[Any],
    table: dict[str, Callable],
    *,
    credentialed: frozenset[str] = frozenset(),
    check_credential: Callable[[Any], Any] | None = None,
) -> Any:
    """Look up ``method``, strip and verify its credential, check arity, call.

    ``credentialed`` names the methods whose first positional argument is a
    credential consumed by ``check_credential`` rather than passed on.
    """
    handler = table.get(method)
    if handler is None:
        raise AttributeError(f"Method not found: {method}")
    args = list(params)
    if method in credentialed:
        if not args:
            raise TypeError(
                f"{method} requires a master password as its first positional "
                f"argument; got 0 arguments."
            )
        if check_credential is None:
            raise RuntimeError(
                f"{method!r} is listed as credentialed but the dispatch table "
                f"passed no check_credential; refusing to call it unverified"
            )
        credential, *args = args
        check_credential(credential)
    _check_arity(method, handler, len(args))
    return handler(*args)
