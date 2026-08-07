"""The ``properties`` field's model-side surface.

Six methods that together implement one feature — reading a Properties
definition, cleaning it, validating it, and converting it to cache/column form.
They lived in ``BaseModel``'s class body, which is how a whole feature ends up
invisible inside the composition root; ``get_property_definition`` also called
``self.browse``, one of the ``self``-edges that kept ``base.py`` inside the
nine-unit mixin cycle (see ``tooling/architecture/mixin_coupling_check.py``).

Moved verbatim. They stay ordinary recordset methods reached as
``self.get_property_definition(...)``; only the declaring class changes, which
attribute lookup crosses through the MRO for free.
"""

import typing

from odoo.tools import SQL

from ... import decorators as api
from ...parsing import parse_field_expr
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from ...fields.base import Field


class _PropertiesMixin(_ModelStubs):
    """Model-side helpers for ``properties`` fields."""

    __slots__ = ()

    @api.model
    def get_property_definition(self, full_name: str) -> dict:
        """Return the definition of the given property.

        :param full_name: Name of the field / property
            (e.g. "property.integer")
        """
        self.browse().check_access("read")
        field_name, property_name = parse_field_expr(full_name)
        field = self._fields.get(field_name)
        if not field:
            raise ValueError(f"Invalid field {field_name!r} on model {self._name!r}")
        if field.type != "properties":
            raise ValueError(
                f"Field {field_name!r} on model {self._name!r} is not a "
                f"properties field"
            )
        from ...fields.properties import check_property_field_value_name

        check_property_field_value_name(property_name)

        target_model = self.env[self._fields[field.definition_record].comodel_name]
        field_definition = target_model._fields[field.definition_record_field]
        result = self.env.execute_query_dict(
            SQL(
                """ SELECT definition
                  FROM %(table)s, jsonb_array_elements(%(field)s) definition
                 WHERE %(field)s IS NOT NULL AND definition->>'name' = %(name)s
                 LIMIT 1 """,
                table=SQL.identifier(target_model._table),
                field=SQL.identifier(
                    field.definition_record_field, to_flush=field_definition
                ),
                name=property_name,
            )
        )
        return result[0]["definition"] if result else {}

    def _clean_properties(self) -> None:
        """Remove all properties of ``self`` that are no longer in the related definition"""
        for fname, field in self._fields.items():
            if field.type != "properties":
                continue
            for record in self:
                old_value = record[fname]._values
                if not old_value:
                    continue

                definitions = field._get_properties_definition(record)
                all_names = {definition["name"] for definition in definitions}
                new_values = {
                    name: value
                    for name, value in old_value.items()
                    if name in all_names
                }
                if len(new_values) != len(old_value):
                    record[fname] = new_values

    def _validate_properties_definition(
        self, properties_definition: typing.Any, field: Field
    ) -> None:
        """Allow to validate additional properties attributes."""

    def _additional_allowed_keys_properties_definition(self) -> tuple[str, ...]:
        """Allow to add more allowed key for properties."""
        return ()

    def _convert_to_cache_properties_definition(self, value: typing.Any) -> typing.Any:
        """Allow to patch `convert_to_cache` of the properties definition."""
        return value

    def _convert_to_column_properties_definition(self, value: typing.Any) -> typing.Any:
        """Allow to patch `convert_to_column` of the properties definition."""
        return value
