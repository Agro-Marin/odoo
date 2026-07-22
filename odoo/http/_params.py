"""Annotation-driven coercion & validation for opt-in typed routes.

A route marked ``@route(..., typed=True)`` declares each request parameter's type
through the handler's annotations. This module reads those annotations once at
decoration time (:func:`build_param_specs`) and, on every request, coerces the
raw request values — query/form strings for ``type='http'`` routes, JSON scalars
for ``jsonrpc``/``json2`` — to the declared types (:func:`coerce_params`), raising
a clean ``400 Bad Request`` for a missing required parameter or a value that
cannot be coerced.

Only *annotated* parameters are touched: an unannotated parameter (the Odoo
norm) passes through unchanged, so turning on ``typed=True`` never alters how an
existing handler sees its other arguments. Supported annotations are the request
primitives ``int``/``float``/``bool``/``str``, their ``X | None`` form (PEP 604),
and ``list`` / ``list[<primitive>]``; any other annotation is left untouched (the
value passes through as received).

Pure module — only stdlib + werkzeug — so the coercion rules are unit-testable
without an HTTP stack, a registry, or a database.
"""

from __future__ import annotations

import inspect
import math
import types
import typing
from typing import Any, NamedTuple

from werkzeug.exceptions import BadRequest

_PRIMITIVES: frozenset[type] = frozenset({int, float, bool, str})

# HTTP/form boolean spellings. A checkbox sends "on"; querystrings and JSON-over-
# HTTP send "true"/"1"; an absent checkbox often arrives as "" (treated false).
_TRUE_TOKENS: frozenset[str] = frozenset({"true", "1", "on", "yes", "t"})
_FALSE_TOKENS: frozenset[str] = frozenset({"false", "0", "off", "no", "f", ""})


class ParamSpec(NamedTuple):
    """How one keyword parameter is coerced.

    :param target: the primitive to coerce to (``int``/``float``/``bool``/``str``)
        or ``list`` for a sequence parameter.
    :param item: element primitive for ``list[...]`` params, else ``None``.
    :param allow_none: whether the annotation was ``X | None`` / ``Optional[X]``.
    :param required: whether the parameter has no default (must be supplied).
    """

    target: type
    item: type | None
    allow_none: bool
    required: bool


def _resolve(annotation: Any) -> tuple[type | None, type | None, bool]:
    """Reduce an annotation to ``(target, item, allow_none)``.

    Returns ``(None, None, allow_none)`` for any annotation this module does not
    coerce, so the caller leaves such parameters untouched.
    """
    allow_none = False
    if isinstance(annotation, types.UnionType):  # PEP 604 ``X | None``
        args = typing.get_args(annotation)
        allow_none = type(None) in args
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) != 1:
            return None, None, allow_none  # union of several real types: unsupported
        annotation = non_none[0]

    origin = typing.get_origin(annotation)
    if annotation is list:
        return list, None, allow_none
    if origin is list:
        item_args = typing.get_args(annotation)
        item = item_args[0] if item_args else None
        if item not in _PRIMITIVES:
            item = None  # list[<non-primitive>] -> elements pass through
        return list, item, allow_none
    if annotation in _PRIMITIVES:
        return annotation, None, allow_none
    return None, None, allow_none


def build_param_specs(endpoint: typing.Callable) -> dict[str, ParamSpec]:
    """Map each annotated keyword parameter of ``endpoint`` to a :class:`ParamSpec`.

    Mirrors :func:`odoo.http.routing._route_param_filter`'s notion of "accepted
    by keyword" (POSITIONAL_OR_KEYWORD / KEYWORD_ONLY), skips the bound ``self``,
    and skips parameters that are unannotated or annotated with an unsupported
    type. Computed once, at decoration time.
    """
    specs: dict[str, ParamSpec] = {}
    params = list(inspect.signature(endpoint).parameters.values())
    for param in params[1:]:  # skip the bound controller ``self`` (params[0])
        if param.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue
        if param.annotation is inspect.Parameter.empty:
            continue  # unannotated -> pass through unchanged
        target, item, allow_none = _resolve(param.annotation)
        if target is None:
            continue  # unsupported annotation -> pass through unchanged
        specs[param.name] = ParamSpec(
            target=target,
            item=item,
            allow_none=allow_none,
            required=param.default is inspect.Parameter.empty,
        )
    return specs


def _to_bool(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
    if isinstance(value, int):  # JSON 0/1 (bool already handled above)
        return bool(value)
    raise BadRequest(f"parameter {name!r} must be a boolean")


def _coerce_scalar(name: str, value: Any, target: type) -> Any:
    if target is str:
        if isinstance(value, str):
            return value
        # Whitelist what may be stringified: only JSON scalars (int/float/bool)
        # convert to a meaningful string. Anything else — a dict/list, raw
        # ``bytes``, or a werkzeug ``FileStorage`` posted under a str-typed field
        # — would silently arrive as its Python ``repr`` (e.g.
        # ``"<FileStorage: 'x.png' ...>"``), never what the caller meant, so
        # reject it. ``bool`` is an ``int`` subclass, covered here.
        if isinstance(value, (int, float)):
            return str(value)
        raise BadRequest(f"parameter {name!r} must be a string")
    if target is bool:
        return _to_bool(name, value)
    if target is int:
        # bool is an int subclass; a JSON ``true`` for an int param is a type
        # error, not silently 1.
        if isinstance(value, bool):
            raise BadRequest(f"parameter {name!r} must be an integer")
        # ``int(3.7)`` truncates: a fractional JSON number for an int param is
        # a caller bug, not a value to round silently. Integral floats (JS
        # clients serialize 3 as 3.0) are accepted.
        if isinstance(value, float) and not value.is_integer():
            raise BadRequest(f"parameter {name!r} must be an integer")
        try:
            return int(value)
        except TypeError, ValueError:
            raise BadRequest(f"parameter {name!r} must be an integer") from None
    if target is float:
        if isinstance(value, bool):
            raise BadRequest(f"parameter {name!r} must be a number")
        try:
            result = float(value)
        except TypeError, ValueError:
            raise BadRequest(f"parameter {name!r} must be a number") from None
        # ``float("nan")`` / ``float("inf")`` parse from a query string but are
        # never a meaningful request value: NaN poisons comparisons downstream
        # and neither round-trips through JSON. Fail closed.
        if not math.isfinite(result):
            raise BadRequest(f"parameter {name!r} must be a finite number")
        return result
    return value  # unreachable: build_param_specs only stores primitives


def _coerce_value(name: str, value: Any, spec: ParamSpec) -> Any:
    if value is None:
        if spec.allow_none:
            return None
        raise BadRequest(f"parameter {name!r} must not be null")
    if spec.target is list:
        items = value if isinstance(value, (list, tuple)) else [value]
        if spec.item is None:
            return list(items)
        return [_coerce_scalar(name, item, spec.item) for item in items]
    return _coerce_scalar(name, value, spec.target)


def coerce_params(
    params: dict[str, Any], specs: dict[str, ParamSpec]
) -> dict[str, Any]:
    """Return ``params`` with each annotated entry coerced to its declared type.

    Unannotated entries are passed through unchanged. A required parameter absent
    from ``params``, or a value that cannot be coerced, raises ``BadRequest``
    (→ HTTP 400). The input dict is not mutated.
    """
    if not specs:
        return params
    coerced = dict(params)
    for name, spec in specs.items():
        if name not in params:
            if spec.required:
                raise BadRequest(f"missing required parameter {name!r}")
            continue
        coerced[name] = _coerce_value(name, params[name], spec)
    return coerced
