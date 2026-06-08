from odoo import fields, models


class IrExports(models.Model):
    """Named export preset listing the fields to export for a given model."""

    _name = "ir.exports"
    _description = "Exports"
    _order = "name, id"

    name = fields.Char(string="Export Name")
    resource = fields.Char(index=True)
    export_fields = fields.One2many(
        "ir.exports.line", "export_id", string="Fields to Export", copy=True
    )


class IrExportsLine(models.Model):
    """Single field entry of an export preset."""

    _name = "ir.exports.line"
    _description = "Exports Line"
    # Lines render in global id order; insertion order ≈ id order so a preset's
    # columns stay stable in practice. If explicit column ordering becomes a
    # requirement (IEXP-C1), add a `sequence` field and order by it here.
    _order = "id"

    name = fields.Char(string="Field Name")
    export_id = fields.Many2one(
        "ir.exports", string="Export", index=True, ondelete="cascade"
    )
