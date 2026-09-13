from odoo import fields, models


class IrModuleModuleExclusion(models.Model):
    _name = "ir.module.module.exclusion"
    _inherit = ["mixin.module.link"]
    _description = "Module exclusion"
    _log_access = False

    linked_id = fields.Many2one(string="Excluded Module")

    _module_exclusion_uniq = models.UniqueIndex(
        "(module_id, name) WHERE module_id IS NOT NULL AND name IS NOT NULL",
        "A module cannot declare the same exclusion twice!",
    )
