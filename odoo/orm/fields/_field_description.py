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
    def get_description(
        self, env: Environment, attributes: Collection[str] | None = None
    ) -> ValuesType:
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
        if self.is_column:
            return True
        if self.inherited_field and self.inherited_field._description_sortable(env):
            return True

        model = env[self.model_name]
        try:
            query = model._as_query(ordered=False)
            term = model._order_field_to_sql(
                model._table, self.name, SQL.EMPTY, SQL.EMPTY, query
            )
        except ValueError, AccessError, NotImplementedError:
            return False
        return bool(term)

    def _description_groupable(self, env: Environment) -> bool:
        if self.is_column:
            return True
        if self.inherited_field and self.inherited_field._description_groupable(env):
            return True

        model = env[self.model_name]
        groupby = self.name if not self.is_temporal else f"{self.name}:month"
        try:
            query = model._as_query(ordered=False)
            model._read_group_groupby(model._table, groupby, query)
            return True
        except ValueError, AccessError, NotImplementedError:
            return False

    def _description_aggregator(self, env: Environment) -> str | None:
        if not self.aggregator or self.is_column:
            return self.aggregator
        if self.inherited_field and self.inherited_field._description_aggregator(env):
            return self.inherited_field.aggregator

        model = env[self.model_name]
        try:
            query = model._as_query(ordered=False)
            model._read_group_select(f"{self.name}:{self.aggregator}", query)
            return self.aggregator
        except ValueError, AccessError, NotImplementedError:
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
        return env._(self.falsy_value_label) if self.falsy_value_label else None

    def is_editable(self) -> bool:
        return not self.readonly
