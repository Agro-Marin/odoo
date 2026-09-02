from __future__ import annotations

import annotationlib
import functools
import inspect
from collections.abc import Callable, Sequence
from typing import Any

from odoo.db import is_maintenance_db

from .settings import current

__all__ = ("dispatch_through_table", "get_positional_bounds", "is_db_rpc_exposed")


def is_db_rpc_exposed(db_name: object) -> bool:
    if not isinstance(db_name, str) or not db_name:
        return False
    if is_maintenance_db(db_name):
        return False
    exposed = current().db_name
    return not exposed or db_name in exposed


@functools.cache
def get_positional_bounds(handler: Callable) -> tuple[int, int | None, tuple[str, ...]]:
    required = 0
    maximum = 0
    names: list[str] = []
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
    required, maximum, names = get_positional_bounds(handler)
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


def dispatch_through_table(
    method: str,
    params: Sequence[Any],
    table: dict[str, Callable],
    *,
    credentialed: frozenset[str] = frozenset(),
    check_credential: Callable[[Any], Any] | None = None,
) -> Any:
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
