import typing

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.db import BaseCursor
    from odoo.orm.components.model_graph import ModelGraph
    from odoo.orm.fields import Field
    from odoo.orm.models import BaseModel


class _RegistryStubs:
    __slots__ = ()

    if typing.TYPE_CHECKING:
        model_graph: ModelGraph
        models: dict[str, type[BaseModel]]
        not_null_fields: set[Field]
        _foreign_keys: dict[tuple[str, str], tuple[str, str, str, BaseModel, str]]
        _constraint_queue: dict[typing.Any, Callable[[BaseCursor], None]]
        has_unaccent: bool
        has_trigram: bool
        unaccent: typing.Any
        _is_install: bool
