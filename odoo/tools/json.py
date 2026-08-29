import dataclasses
from datetime import date, datetime

from odoo.libs.collections import ReadonlyDict
from odoo.libs.func import lazy
from odoo.libs.json import (
    ScriptSafeJSON as JSON,
)
from odoo.libs.json import (
    dumps as fast_dumps,
)
from odoo.libs.json import (
    dumps_bytes as fast_dumps_bytes,
)
from odoo.libs.json import (
    fast_clone,
    scriptsafe,
)
from odoo.libs.json import (
    loads as fast_loads,
)

# Every name this module re-exports or defines, per the rule
# tests/framework/test_public_surfaces.py::TestToolsSubmoduleSurfaces pins:
# a tools shim publishes what it defines plus what it takes from another
# odoo module.  Third-party imports are incidental and stay out.
__all__ = [
    "JSON",
    "ReadonlyDict",
    "fast_clone",
    "fast_dumps",
    "fast_dumps_bytes",
    "fast_loads",
    "json_default",
    "lazy",
    "orjson_default",
    "scriptsafe",
]


def _convert(obj: object) -> object:
    """The one conversion table both defaults answer to.

    `json_default` and `orjson_default` used to carry a copy each, and they had
    drifted: only orjson's knew about dataclasses, so the same object came out
    `{"x": 1}` through one encoder and `"P(x=1)"` through the other.  One table,
    two drivers -- what differs between them is recursion, not policy.
    """
    from odoo import fields

    if isinstance(obj, datetime):
        return fields.Datetime.to_string(obj)
    if isinstance(obj, date):
        return fields.Date.to_string(obj)
    if isinstance(obj, ReadonlyDict):
        return dict(obj)
    if isinstance(obj, bytes):
        return obj.decode()
    if isinstance(obj, fields.Domain):
        return list(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return str(obj)


def json_default(obj: object) -> object:
    """`default=` for the stdlib json encoder.

    It re-enters `default` for anything the conversion returns that it still
    cannot serialise, so unwrapping a `lazy` one level is enough.
    """
    if isinstance(obj, lazy):
        return obj._value
    return _convert(obj)


def orjson_default(obj: object) -> object:
    """`default=` for orjson, which calls it once per object and does not re-enter.

    A `lazy` therefore has to be unwrapped *and* converted here, in one pass.
    """
    if isinstance(obj, lazy):
        value = obj._value
        return value if _is_native(value) else _convert(value)
    return _convert(obj)


def _is_native(value: object) -> bool:
    """True when orjson can serialise `value` without asking us again."""
    return value is None or isinstance(value, (str, int, float, bool, list, dict))
