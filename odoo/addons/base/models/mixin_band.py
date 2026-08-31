from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MixinBand(models.AbstractModel):
    _name = "mixin.band"
    _description = "Numeric Band Mixin"

    min_value = fields.Float(
        default=0.0,
        help="Lower bound of the band, inclusive.",
    )
    max_value = fields.Float(
        default=0.0,
        help="Upper bound of the band, exclusive -- it is the lower bound of "
        "the next band. 0 means no upper limit, which the highest band of a "
        "scale should use so nothing falls off the top.",
    )
    active = fields.Boolean(
        default=True,
    )

    def _is_band(self):
        return True

    def _band_scope_domain(self):
        self.check_singleton()
        return []

    @staticmethod
    def _ranges_overlap(band_a, band_b):
        max_a = band_a.max_value or float("inf")
        max_b = band_b.max_value or float("inf")
        return band_a.min_value < max_b and band_b.min_value < max_a

    def _covers(self, value):
        self.check_singleton()
        upper = self.max_value or float("inf")
        return self.min_value <= value < upper

    @api.constrains("min_value", "max_value", "active")
    def _check_band(self):
        scales = defaultdict(self.browse)
        for record in self:
            if not record._is_band():
                if record.min_value or record.max_value:
                    raise ValidationError(
                        self.env._(
                            "%(name)s: bounds only apply to a band.",
                            name=record.display_name,
                        )
                    )
                continue
            if record.min_value < 0:
                raise ValidationError(
                    self.env._(
                        "%(name)s: the lower bound cannot be negative.",
                        name=record.display_name,
                    )
                )
            if record.max_value and record.max_value <= record.min_value:
                raise ValidationError(
                    self.env._(
                        "%(name)s: the upper bound (%(max)s) must be greater "
                        "than the lower bound (%(min)s), or zero for an "
                        "open-ended band.",
                        name=record.display_name,
                        max=record.max_value,
                        min=record.min_value,
                    )
                )
            if not record.active:
                continue
            scales[repr(record._band_scope_domain())] |= record

        # One query per distinct scale, not one per record. Which bands may
        # conflict is a per-record notion -- two attributes' buckets, or two
        # companies' bands, never overlap each other -- so the hook stays per
        # record while every record answering it alike shares one search.
        # Importing a scale used to cost one query per band in it.
        for records in scales.values():
            candidates = records.search(records[0]._band_scope_domain())
            for record in records:
                for other in candidates:
                    if other == record or not other._is_band():
                        continue
                    if record._ranges_overlap(record, other):
                        raise ValidationError(
                            self.env._(
                                "%(a)s overlaps with %(b)s.",
                                a=record.display_name,
                                b=other.display_name,
                            )
                        )
