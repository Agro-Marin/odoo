from typing import Any, Self

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import ormcache

# ``env.cr.cache`` key for the transaction-local memo of definition ids created
# by the current transaction: ``{(model_name, field_name): definition_id}``.
# ``cr.cache`` is cleared on commit/rollback/savepoint rollback, so a rolled-back
# id can never leak into another transaction -- unlike the process-global
# "stable" ormcache, whose additions are not transaction-aware.
DEFINITION_MEMO_CACHE_KEY = "properties_base_definition_ids"


class PropertiesBaseDefinition(models.Model):
    """Stores the properties definition for a ``properties`` field without a parent record."""

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
        """Return the definition record for a model's properties field, creating it if missing.

        :rtype: properties.base.definition
        """
        return self.browse(
            self._get_definition_id_for_property_field(model_name, field_name)
        )

    def _get_definition_id_for_property_field(
        self, model_name: str, field_name: str
    ) -> int:
        """Return the definition id for a model's properties field, creating it if missing.

        A row created here is memoized only in the transaction-local
        ``env.cr.cache`` (DEFINITION_MEMO_CACHE_KEY); the process-global "stable"
        ormcache is populated exclusively from committed rows found by
        :meth:`_search_definition_id_for_property_field`. A rollback therefore
        cannot leave a dangling id in the registry cache.

        :rtype: int
        """
        # 1. Transaction-local memo: a definition created earlier in this
        # (not yet committed) transaction.
        memo = self.env.cr.cache.get(DEFINITION_MEMO_CACHE_KEY)
        if memo and (definition_id := memo.get((model_name, field_name))):
            return definition_id

        # 2. Registry-wide positive lookup ("stable" ormcache).
        try:
            return self._search_definition_id_for_property_field(model_name, field_name)
        except ValueError:
            pass

        # 3. Lazy create. The UNIQUE constraint on properties_field_id serializes
        # concurrent creators; the id is memoized transaction-locally only, so a
        # rollback cannot poison the process-global cache.
        field_ids = self.env["ir.model.fields"]._get_ids(model_name)
        field_id = field_ids.get(field_name)
        if not field_id:
            field = self.env["ir.model.fields"].sudo()._get(model_name, field_name)
            field_id = field.id

        definition_record = self.sudo().create({"properties_field_id": field_id})
        memo = self.env.cr.cache.setdefault(DEFINITION_MEMO_CACHE_KEY, {})
        memo[model_name, field_name] = definition_record.id
        return definition_record.id

    @ormcache("model_name", "field_name", cache="stable")
    def _search_definition_id_for_property_field(
        self, model_name: str, field_name: str
    ) -> int:
        """Return the definition id for a model's properties field via SELECT only.

        Raises ``ValueError`` on a miss so the miss stays out of the "stable"
        ormcache (which only stores returned values); the cache thus only ever
        holds ids found by a committed SELECT.

        Fork (5b32001d5dd): replaces the upstream ORM ``search()`` (an expensive
        JOIN on ir_model_fields) with a cached ``_get_ids`` field lookup plus a
        direct raw SELECT. The raw SELECT does not flush pending ORM writes, but
        the only ORM writer is _get_definition_id_for_property_field's create(),
        which flushes and memoizes its result transaction-locally.

        :rtype: int
        :raise ValueError: when no definition row exists for the field
        """
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

        msg = f"No properties.base.definition for {model_name}.{field_name}"
        raise ValueError(msg)
