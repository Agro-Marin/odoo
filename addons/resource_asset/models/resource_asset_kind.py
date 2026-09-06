from odoo import fields, models


class ResourceAssetKind(models.Model):
    _name = "resource.asset.kind"
    _description = "Asset Kind"
    _inherit = ["mixin.catalog"]
    _order = "sequence, name, id"

    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    scheduled = fields.Boolean(
        help="Assets of this kind run on a shift and take their company's working hours; otherwise they are available around the clock.",
    )
    identifier_type_ids = fields.Many2many(
        "resource.asset.identifier.type",
        "resource_asset_kind_identifier_type_rel",
        "kind_id",
        "type_id",
        string="Required Identifiers",
    )
    asset_ids = fields.One2many("resource.asset", "kind_id")
    asset_count = fields.Count("asset_ids")

    _code_uniq = models.Constraint(
        "UNIQUE(code)", "Each asset kind code must be unique."
    )
