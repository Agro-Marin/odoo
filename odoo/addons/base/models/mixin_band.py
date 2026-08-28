from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MixinBand(models.AbstractModel):
    """Half-open numeric band ``[min_value, max_value)`` within a scale of sibling bands."""

    _name = "mixin.band"
    _description = "Numeric Band Mixin"

    # Bounds are half-open, [min_value, max_value): the lower bound belongs to
    # the band and the upper bound belongs to the *next* one.
    #
    # Inclusive-both-ends bounds cannot express a contiguous scale. 0-10 and
    # 10-20 are then rejected as overlapping at the shared point 10, so
    # configurations have to leave integer gaps -- and every fractional
    # measurement that lands in a gap classifies into nothing at all. Where the
    # band selects a multiplier applied downstream, "nothing at all" is not a
    # cosmetic outcome.
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
    # _check_band skips the overlap check on an inactive band, so this mixin
    # needs its own active field rather than assuming a consumer supplies
    # one: unlike mixin.attribute/mixin.attribute.value, this mixin does not
    # inherit mixin.catalog. A consumer that provides no active field of its
    # own (directly or through another parent) would otherwise crash with an
    # AttributeError the moment min_value/max_value is written.
    active = fields.Boolean(
        default=True,
    )

    def _is_band(self):
        """Whether this record takes part in a scale.

        True by default. Override where only some records of the model are
        bands -- an attribute value is one only when its attribute is numeric.

        :return: whether the bounds are meaningful on this record
        """
        return True

    def _band_siblings(self):
        """The other active bands sharing this one's scale.

        Defaults to every other active record of the model, which is right for
        a model that *is* one scale. Override to scope it (per attribute, per
        company).

        :return: the sibling bands
        """
        self.ensure_one()
        return self.search([("id", "!=", self.id)])

    @staticmethod
    def _ranges_overlap(band_a, band_b):
        """Return True when two half-open bands share any point.

        ``[min_a, max_a)`` and ``[min_b, max_b)`` intersect only when each
        starts before the other ends. Touching bounds do not overlap, which is
        what lets a scale be contiguous: 1-50 and 50-100 are adjacent, not
        conflicting, and together they cover every value in between.
        """
        max_a = band_a.max_value or float("inf")
        max_b = band_b.max_value or float("inf")
        return band_a.min_value < max_b and band_b.min_value < max_a

    def _covers(self, value):
        """Whether ``value`` falls in this band.

        :param float value: the measurement to test
        :return: whether ``min_value <= value < max_value``
        """
        self.ensure_one()
        upper = self.max_value or float("inf")
        return self.min_value <= value < upper

    @api.constrains("min_value", "max_value", "active")
    def _check_band(self):
        """Bounds must be usable, and a scale must not overlap itself."""
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
            # Strictly greater: with half-open bounds max == min is an empty
            # band that can never match anything.
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
            for other in record._band_siblings():
                if not other._is_band():
                    continue
                if record._ranges_overlap(record, other):
                    raise ValidationError(
                        self.env._(
                            "%(a)s overlaps with %(b)s.",
                            a=record.display_name,
                            b=other.display_name,
                        )
                    )
