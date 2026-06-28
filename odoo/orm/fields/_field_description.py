"""Client-facing field metadata: get_description and its _description_* parts.

Extracted from the Field god-class; mixed into Field (base.py).
"""

import typing
from collections.abc import (
    Collection,
)

from odoo.exceptions import AccessError
from odoo.tools import (
    SQL,
)

if typing.TYPE_CHECKING:
    from .._typing import BaseModel, ValuesType
    from ..runtime import Environment

    M = typing.TypeVar("M", bound=BaseModel)


from ._field_stubs import _FieldStubs


class _FieldDescriptionMixin(_FieldStubs):
    """Client-facing field metadata: get_description and its _description_* parts."""

    def get_description(
        self, env: Environment, attributes: Collection[str] | None = None
    ) -> ValuesType:
        """Return a dictionary that describes the field ``self``."""
        desc = {}
        for attr, prop in self.description_attrs:
            if attributes is not None and attr not in attributes:
                continue
            value = getattr(self, prop)
            if callable(value):
                value = value(env)
            if value is not None:
                desc[attr] = value

        return desc

    def _description_depends(self, env: Environment) -> Collection[str]:
        return env.registry.field_depends[self]

    @property
    def _description_searchable(self) -> bool:
        return bool(self.store or self.search)

    def _description_sortable(self, env: Environment) -> bool:
        if self.is_column:  # shortcut
            return True
        if self.inherited_field and self.inherited_field._description_sortable(env):
            # avoid recomputing for inherited field
            return True

        model = env[self.model_name]
        query = model._as_query(ordered=False)
        try:
            model._order_field_to_sql(
                model._table, self.name, SQL.EMPTY, SQL.EMPTY, query
            )
            return True
        except (ValueError, AccessError):
            return False

    def _description_groupable(self, env: Environment) -> bool:
        if self.is_column:  # shortcut
            return True
        if self.inherited_field and self.inherited_field._description_groupable(env):
            # avoid recomputing for inherited field
            return True

        model = env[self.model_name]
        query = model._as_query(ordered=False)
        groupby = (
            self.name if self.type not in ("date", "datetime") else f"{self.name}:month"
        )
        try:
            model._read_group_groupby(model._table, groupby, query)
            return True
        except (ValueError, AccessError):
            return False

    def _description_aggregator(self, env: Environment) -> str | None:
        if not self.aggregator or self.is_column:  # shortcut
            return self.aggregator
        if self.inherited_field and self.inherited_field._description_aggregator(env):
            # avoid recomputing for inherited field
            return self.inherited_field.aggregator

        model = env[self.model_name]
        query = model._as_query(ordered=False)
        try:
            model._read_group_select(f"{self.name}:{self.aggregator}", query)
            return self.aggregator
        except (ValueError, AccessError):
            return None

    def _description_string(self, env: Environment) -> str:
        if self.string and env.lang:
            model_name = self.base_field.model_name
            field_string = env["ir.model.fields"].get_field_string(model_name)
            return field_string.get(self.name) or self.string
        return self.string

    def _description_help(self, env: Environment) -> str | None:
        if self.help and env.lang:
            model_name = self.base_field.model_name
            field_help = env["ir.model.fields"].get_field_help(model_name)
            return field_help.get(self.name) or self.help
        return self.help

    def _description_falsy_value_label(self, env) -> str | None:
        return (
            env._(self.falsy_value_label) if self.falsy_value_label else None  # pylint: disable=gettext-variable,E8502
        )

    def is_editable(self) -> bool:
        """Return whether the field can be editable in a view."""
        return not self.readonly
