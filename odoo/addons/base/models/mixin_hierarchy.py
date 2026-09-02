from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MixinHierarchy(models.AbstractModel):
    _name = "mixin.hierarchy"
    _description = "Hierarchy (a parent/child tree kept on a materialized path)"
    _parent_store = True

    # Overridden where a domain-specific sentence reads better than the generic
    # one; the generic one exists so that fifteen models stop each translating
    # their own wording of the same rule.
    _hierarchy_cycle_message = None

    parent_path = fields.Char(index=True)

    @api.constrains(lambda self: [self._parent_name])
    def _check_parent_id(self):
        if self._has_cycle():
            raise ValidationError(
                self._hierarchy_cycle_message
                or _("A record cannot be its own ancestor.")
            )
