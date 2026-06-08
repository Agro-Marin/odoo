"""
MetaModel - the metaclass for all Odoo models.
"""

import inspect
import logging
import re
import typing
from collections import defaultdict

from ..fields.misc import Id
from ..fields.temporal import Datetime

if typing.TYPE_CHECKING:
    from ..fields.base import Field
    from ..runtime import Registry
    from .table_objects import TableObject

_logger = logging.getLogger("odoo.models")

# BaseModel.__init__ takes (self, env, ids, prefetch_ids).  inspect.signature
# returns the bound parameters minus self for unbound methods, so we expect
# 4 here (self is included in attrs["__init__"] when read from the class dict).
_BASE_MODEL_INIT_PARAM_COUNT = 4


class MetaModel(type):
    """The metaclass of all model classes.

    Its main purpose is to register the models per module.
    """

    _module_to_models__: defaultdict[str, list[MetaModel]] = defaultdict(list)

    pool: Registry | None
    """Reference to the registry for registry classes, otherwise it is a definition class."""

    _field_definitions: list[Field]
    _table_object_definitions: list[TableObject]
    _name: str
    _register: bool  # need to define on each Model, default: True
    _log_access: bool  # when defined, add update log columns
    _module: str | None
    _abstract: bool
    _auto: bool
    _inherit: list[str] | None

    def __new__(
        meta: type,
        name: str,
        bases: tuple[type, ...],
        attrs: dict[str, typing.Any],
    ) -> MetaModel:
        # this prevents assignment of non-fields on recordsets
        attrs.setdefault("__slots__", ())
        # this collects the fields defined on the class (via Field.__set_name__())
        attrs.setdefault("_field_definitions", [])
        # this collects the table object definitions on the class (via TableObject.__set_name__())
        attrs.setdefault("_table_object_definitions", [])

        if attrs.get("_register", True):
            # determine '_module'
            if "_module" not in attrs:
                module = attrs["__module__"]
                if not module.startswith("odoo.addons."):
                    raise ImportError(
                        f"Invalid import of {module}.{name}, it should start with 'odoo.addons'."
                    )
                attrs["_module"] = module.split(".")[2]

            _inherit = attrs.get("_inherit")
            if _inherit and isinstance(_inherit, str):
                attrs.setdefault("_name", _inherit)
                attrs["_inherit"] = [_inherit]

            if not attrs.get("_name"):
                # add '.' before every uppercase letter preceded by any non-underscore char
                attrs["_name"] = re.sub(r"(?<=[^_])([A-Z])", r".\1", name).lower()
                _logger.warning(
                    "Class %s has no _name, please make it explicit: _name = %r",
                    name,
                    attrs["_name"],
                )

            # raise (not assert) — under python -O a missing _name would slip
            # through and crash much later in registration with an opaque error.
            if not attrs.get("_name"):
                raise ValueError(
                    f"Model class {name!r} must define a '_name' attribute"
                )

        return super().__new__(meta, name, bases, attrs)

    def __init__(
        cls,
        name: str,
        bases: tuple[type, ...],
        attrs: dict[str, typing.Any],
    ) -> None:
        super().__init__(name, bases, attrs)

        if (
            "__init__" in attrs
            and len(inspect.signature(attrs["__init__"]).parameters)
            != _BASE_MODEL_INIT_PARAM_COUNT
        ):
            _logger.warning(
                "The method %s.__init__ doesn't match the new signature in module %s",
                name,
                attrs.get("__module__"),
            )

        if not attrs.get("_register", True):
            return

        # Remember which models to instantiate for this module.
        if cls._module:
            cls._module_to_models__[cls._module].append(cls)

        # ``cls._inherit`` defaults to ``()`` on BaseModel, but a developer
        # explicitly setting ``_inherit = None`` would crash here with an
        # opaque ``TypeError: argument of type 'NoneType'`` at the membership
        # test below.  Coerce to () so the legitimate "no inheritance" intent
        # behaves the same as the default.
        if cls._inherit is None:
            cls._inherit = ()
        if not cls._abstract and cls._name not in cls._inherit:
            # this class defines a model: add magic fields
            def add(name: str, field: Field) -> None:
                setattr(cls, name, field)
                field.__set_name__(cls, name)

            def add_default(name: str, field: Field) -> None:
                if name not in attrs:
                    setattr(cls, name, field)
                    field.__set_name__(cls, name)

            # make sure `id` field is still a `fields.Id`
            if not isinstance(cls.id, Id):
                raise TypeError(f"Field {cls.id} is not an instance of fields.Id")

            if attrs.get("_log_access", cls._auto):
                from ..fields.relational import Many2one

                add_default(
                    "create_uid",
                    Many2one("res.users", string="Created by", readonly=True),
                )
                add_default("create_date", Datetime(string="Created on", readonly=True))
                add_default(
                    "write_uid",
                    Many2one("res.users", string="Last Updated by", readonly=True),
                )
                add_default(
                    "write_date",
                    Datetime(string="Last Updated on", readonly=True),
                )
