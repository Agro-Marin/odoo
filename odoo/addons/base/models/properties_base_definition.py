from typing import Any, Self

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import ormcache


class PropertiesBaseDefinition(models.Model):
    """Models storing the properties definition of the record without parent."""

    _name = "properties.base.definition"
    _description = "Properties Base Definition"

    properties_field_id = fields.Many2one(
        "ir.model.fields",
        required=True,
        ondelete="cascade",
    )
    properties_definition = fields.PropertiesDefinition("Properties Definition")

    _unique_properties_field_id = models.Constraint(
        "UNIQUE(properties_field_id)",
        "Only one definition per properties field",
    )

    @api.depends("properties_field_id")
    def _compute_display_name(self) -> None:
        """Set the display name from the linked properties field's model description."""
        for definition in self:
            if not definition.properties_field_id.model:
                definition.display_name = False
                continue

            definition.display_name = _(
                "%s Properties",
                self.env[definition.properties_field_id.model]._description,
            )

    @api.constrains("properties_field_id")
    def _check_properties_field_id(self) -> None:
        """Ensure each definition is linked to a field of type ``properties``."""
        if invalid_fields := self.mapped("properties_field_id").filtered(
            lambda f: f.ttype != "properties"
        ):
            raise ValidationError(
                _(
                    "The definition needs to be linked to a properties field. Those fields are not: %s.",
                    ", ".join(invalid_fields.mapped("name")),
                )
            )

    def write(self, vals: dict[str, Any]) -> bool:
        """Forbid reassigning the backing field; delegate the rest to ``super``."""
        if "properties_field_id" in vals:
            raise AccessError(_("You can not change the field of a base definition"))
        return super().write(vals)

    def _get_definition_for_property_field(
        self, model_name: str, field_name: str
    ) -> Self:
        """Return the definition record for a model's properties field.

        :param str model_name: technical name of the model owning the field
        :param str field_name: name of the ``properties`` field
        :return: the matching (or newly created) definition record
        :rtype: properties.base.definition
        """
        return self.browse(
            self._get_definition_id_for_property_field(model_name, field_name)
        )

    @ormcache("model_name", "field_name", cache="stable")
    def _get_definition_id_for_property_field(
        self, model_name: str, field_name: str
    ) -> int:
        """Return the definition id for a model's properties field, creating it if missing.

        :param str model_name: technical name of the model owning the field
        :param str field_name: name of the ``properties`` field
        :return: the id of the matching (or newly created) definition record
        :rtype: int
        """
        # Fork (5b32001d5dd): replaces the upstream ORM ``search()`` with a
        # cached field_id lookup plus a direct raw SELECT, avoiding the
        # expensive JOIN query: SELECT ... FROM properties_base_definition
        # LEFT JOIN ir_model_fields ...  ir_model_fields._get_ids() is itself
        # ormcache'd on the "stable" group, so repeat calls stay in-memory.
        #
        # Two windows differ from the replaced search() and are intentionally
        # left as-is (no current caller hits them):
        #   1. The raw SELECT does not flush pending ORM writes, so a not-yet
        #      flushed definition would be invisible here. In practice the only
        #      writer is create() below, which flushes through the ORM, and
        #      field create/unlink runs _setup_models__ which clears registry
        #      caches before any read.
        #   2. A definition created on a cache miss is memoized in the "stable"
        #      cache and could in theory outlive a transaction rollback, serving
        #      a dangling id. The same _setup_models__ cache clear on any field
        #      create/unlink closes this window for every real code path.
        field_ids = self.env["ir.model.fields"]._get_ids(model_name)
        field_id = field_ids.get(field_name)

        if field_id:
            # Direct lookup by field_id - no JOIN required
            cr = self.env.cr
            cr.execute(
                "SELECT id FROM properties_base_definition WHERE properties_field_id = %s LIMIT 1",
                [field_id],
            )
            row = cr.fetchone()
            if row:
                return row[0]

        # Create new definition if not found
        if not field_id:
            field = self.env["ir.model.fields"].sudo()._get(model_name, field_name)
            field_id = field.id

        definition_record = self.sudo().create({"properties_field_id": field_id})
        return definition_record.id
