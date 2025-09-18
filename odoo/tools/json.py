# ruff: noqa: F401
from datetime import date, datetime

from odoo.libs.func import lazy
from odoo.libs.json import (
    fast_clone,
    scriptsafe,
)
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
    loads as fast_loads,
)

from .misc import ReadonlyDict


def json_default(obj: object) -> object:
    """JSON serialiser for Odoo-specific types.

    Handles datetime, date, lazy values, ReadonlyDict, bytes, Domain, and
    any other object by falling back to ``str()``.
    """
    from odoo import fields

    if isinstance(obj, datetime):
        return fields.Datetime.to_string(obj)
    if isinstance(obj, date):
        return fields.Date.to_string(obj)
    if isinstance(obj, lazy):
        return obj._value
    if isinstance(obj, ReadonlyDict):
        return dict(obj)
    if isinstance(obj, bytes):
        return obj.decode()
    if isinstance(obj, fields.Domain):
        return list(obj)
    return str(obj)


def orjson_default(obj: object) -> object:
    """Like ``json_default`` but for orjson's non-recursive ``default``
    parameter — ``lazy`` values must be unwrapped to a primitive inline.
    """
    from odoo import fields

    if isinstance(obj, lazy):
        val = obj._value
        if isinstance(val, ReadonlyDict):
            return dict(val)
        if isinstance(val, datetime):
            return fields.Datetime.to_string(val)
        if isinstance(val, date):
            return fields.Date.to_string(val)
        return val
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
    return str(obj)
