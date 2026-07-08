from typing import Any, Self

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import ormcache

# ``env.cr.cache`` key of the transaction-scoped memo of definition ids
# created by the *current* transaction::
#
#     {(model_name, field_name): definition_id}
#
# Mirrors RATE_HISTORY_CACHE_KEY in res_currency.py: ``cr.cache`` is
# transaction-local — cleared on commit, rollback and savepoint rollback
# (``Transaction.clear``) — so the id of a rolled-back row can never leak
# into another transaction, unlike an entry added to the process-global
# "stable" ormcache (additions there are NOT transaction-aware:
# ``Registry.reset_changes`` reverts invalidations only).
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
        """Return the definition record for a model's properties field.

        :param str model_name: technical name of the model owning the field
        :param str field_name: name of the ``properties`` field
        :return: the matching (or newly created) definition record
        :rtype: properties.base.definition
        """
        return self.browse(
            self._get_definition_id_for_property_field(model_name, field_name)
        )

    def _get_definition_id_for_property_field(
        self, model_name: str, field_name: str
    ) -> int:
        """Return the definition id for a model's properties field, creating it if missing.

        The id of a definition row created here is memoized in ``env.cr.cache``
        (transaction-local, see DEFINITION_MEMO_CACHE_KEY) only; the
        process-global "stable" ormcache is populated exclusively by
        :meth:`_search_definition_id_for_property_field`, i.e. from a row found
        by SELECT.  A rollback therefore cannot leave a dangling id in the
        registry cache: the transaction memo dies with the transaction, and the
        next transaction's SELECT repopulates the stable cache from what was
        actually committed.

        :param str model_name: technical name of the model owning the field
        :param str field_name: name of the ``properties`` field
        :return: the id of the matching (or newly created) definition record
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

        # 3. Lazy create.  Other transactions cannot see the uncommitted row
        # anyway, and the UNIQUE constraint on properties_field_id serializes
        # concurrent creators; the id is only memoized transaction-locally so
        # that a rollback cannot poison the process-global cache.
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
        """Return the definition id for a model's properties field, SELECT only.

        Raises ``ValueError`` when no definition row exists.  Raising on a miss
        keeps the miss out of the "stable" cache (ormcache only stores returned
        values), so the process-global cache only ever holds ids found by
        SELECT; rows created by the current transaction are served from the
        transaction memo of :meth:`_get_definition_id_for_property_field`
        before this method runs, and are thus never memoized process-wide
        while still uncommitted.

        Fork (5b32001d5dd): replaces the upstream ORM ``search()`` with a
        cached field_id lookup plus a direct raw SELECT, avoiding the
        expensive JOIN query: SELECT ... FROM properties_base_definition
        LEFT JOIN ir_model_fields ...  ir_model_fields._get_ids() is itself
        ormcache'd on the "stable" group, so repeat calls stay in-memory.
        The raw SELECT does not flush pending ORM writes, so a not-yet
        flushed definition would be invisible here; in practice the only ORM
        writer is _get_definition_id_for_property_field's create(), which
        flushes through the ORM and memoizes its result transaction-locally.

        :param str model_name: technical name of the model owning the field
        :param str field_name: name of the ``properties`` field
        :return: the id of the matching definition record
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
