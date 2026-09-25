from odoo import fields, models


class MixinHierarchy(models.AbstractModel):
    _name = "mixin.hierarchy"
    _description = "Hierarchy (a parent/child tree kept on a materialized path)"
    _parent_store = True

    _hierarchy_cycle_message = None

    parent_path = fields.Char(index=True)
