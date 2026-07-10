from collections.abc import Iterable
from typing import Any, Self

from odoo import api, fields, models
from odoo.api import ValuesType
from odoo.fields import Domain
from odoo.tools import SQL


class PropertiesBaseDefinitionMixin(models.AbstractModel):
    """Mixin that adds properties without parent on a model."""

    _name = "properties.base.definition.mixin"
    _description = "Properties Base Definition Mixin"

    properties = fields.Properties(
        string="Properties",
        definition="properties_base_definition_id.properties_definition",
        copy=True,
    )
    properties_base_definition_id = fields.Many2one(
        "properties.base.definition",
        compute="_compute_properties_base_definition_id",
        search="_search_properties_base_definition_id",
    )

    def _compute_properties_base_definition_id(self) -> None:
        """Resolve the shared definition record for this model's ``properties`` field."""
        self.properties_base_definition_id = (
            self.env["properties.base.definition"]
            .sudo()
            ._get_definition_for_property_field(self._name, "properties")
        )

    def _search_properties_base_definition_id(
        self, operator: str, value: Any
    ) -> Domain:
        """Resolve a search on the (non-stored) definition field to a constant domain.

        :param str operator: only ``in`` is supported (inherited limitation)
        :param value: ids the definition is matched against
        :return: ``Domain.TRUE`` or ``Domain.FALSE``
        :rtype: Domain
        """
        # Upstream limitation: properties are only searched with the normalized
        # ``in`` operator; reject anything else rather than mishandle it.
        if operator != "in":
            raise NotImplementedError(
                f"Unsupported operator {operator!r} for properties_base_definition_id"
            )

        properties_base_definition_id = (
            self.env["properties.base.definition"]
            .sudo()
            ._get_definition_id_for_property_field(self._name, "properties")
        )

        if not isinstance(value, Iterable):
            value = (value,)
        return Domain.TRUE if properties_base_definition_id in value else Domain.FALSE

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Pre-fill the definition link on every record so default property values apply."""
        parent = (
            self.env["properties.base.definition"]
            .sudo()
            ._get_definition_id_for_property_field(self._name, "properties")
        )
        for vals in vals_list:
            # Needed to add the default properties values
            vals["properties_base_definition_id"] = parent
        return super().create(vals_list)

    def _field_to_sql(self, alias: str, fname: str, query: Any = None) -> SQL:
        """Render the non-stored definition field as a constant for export/read.

        ``query`` is typed ``Any`` to match the untyped ``BaseModel._field_to_sql``
        signature it overrides.
        """
        if fname == "properties_base_definition_id":
            # Allow the export to work
            parent = (
                self.env["properties.base.definition"]
                .sudo()
                ._get_definition_id_for_property_field(self._name, "properties")
            )
            return SQL("%s", parent)

        return super()._field_to_sql(alias, fname, query)
