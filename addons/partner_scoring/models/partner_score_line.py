from collections import defaultdict

from odoo import api, fields, models


class PartnerScoreLine(models.Model):
    _name = "partner.score.line"
    _description = "Partner Score Line"
    _order = "partner_id, dimension, id"

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        required=True,
        ondelete="cascade",
        index=True,
    )
    dimension = fields.Selection(
        selection=[
            ("partner_attr", "Partner Attribute"),
        ],
        required=True,
        help="Scoring dimension this row belongs to.",
    )
    source_key = fields.Char(
        required=True,
        index=True,
        help="Stable identity of the row's source, as record ids -- e.g. "
        "'crop:12' or 'partner_attr:5:19'. This is what the refresh matches on, "
        "so a row survives a rename, a translation and a rescore from a session "
        "in another language.",
    )
    source_ref = fields.Char(
        compute="_compute_source_ref",
        help="Human-readable source of the points, resolved from source_key in "
        "the reader's language: the crop, bucket or attribute value that "
        "produced them.",
    )
    points = fields.Float(
        help="Points contributed by this source.",
    )
    max_points = fields.Float(
        help="Ceiling of the dimension/attribute group this row belongs to "
        "(context for the reader). The normalization denominator comes from "
        "the catalog -- see res.partner._get_score_max_possible.",
    )
    applied = fields.Boolean(
        default=True,
        help="Unchecked when the aggregation mode discarded this "
        "contribution (e.g. not the highest value under 'max').",
    )
    note = fields.Char(
        compute="_compute_note",
    )

    @api.depends("dimension", "source_key")
    @api.depends_context("lang")
    def _compute_source_ref(self):
        partner_model = self.env["res.partner"]
        keys_by_dimension = defaultdict(set)
        for row in self:
            keys_by_dimension[row.dimension].add(row.source_key)
        labels = {}
        for dimension, keys in keys_by_dimension.items():
            labels[dimension] = getattr(partner_model, f"_score_labels_{dimension}")(
                keys
            )
        for row in self:
            row.source_ref = labels[row.dimension].get(row.source_key, row.source_key)

    @api.depends("dimension", "source_key", "applied")
    @api.depends_context("lang")
    def _compute_note(self):
        partner_model = self.env["res.partner"]
        for row in self:
            row.note = partner_model._score_row_note(
                row.dimension, row.source_key, row.applied
            )
