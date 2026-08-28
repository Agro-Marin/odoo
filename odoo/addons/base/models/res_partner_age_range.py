import datetime
from itertools import starmap

from odoo import api, fields, models
from odoo.fields import Domain

# Bounds decide which cohort covers a birth year; archiving takes a cohort out
# of the scale entirely. A name change decides nothing, and must not sweep.
_CLASSIFYING_FIELDS = frozenset({"min_value", "max_value", "active"})

# A date cannot hold a year outside these, so a bound past either end is no
# bound at all -- which is also how max_value == 0 spells "open-ended".
_FIRST_YEAR = datetime.date.min.year
_LAST_YEAR = datetime.date.max.year


class ResPartnerAgeRange(models.Model):
    """A generational cohort, keyed on birth year.

    Keyed on the birth *year* rather than on current age, because a cohort is a
    permanent property of a person: someone born in 1983 is Gen Y for good. The
    bounds used to hold ages, which meant everyone crossed into the next cohort
    on a birthday -- 17 of the 138 partners carrying a band had drifted into one
    whose own label contradicted their birth year, and that grows by roughly a
    sixteenth of a cohort every year.
    """

    _name = "res.partner.age.range"
    _inherit = ["mixin.band"]
    _description = "Partner Age Range"
    _order = "min_value"

    name = fields.Char(
        required=True,
    )
    active = fields.Boolean(
        default=True,
    )
    min_value = fields.Float(
        string="From year",
        digits=(16, 0),
        default=lambda self: self._default_min_value(),
        help="First birth year of the cohort, inclusive.",
    )
    max_value = fields.Float(
        string="To year",
        digits=(16, 0),
        help="First birth year *after* the cohort -- it is the lower bound of "
        "the next one. 0 means no upper limit, which the newest cohort should "
        "use so a newborn still classifies. The oldest cohort stays closed on "
        "its lower side: a birth year before it predates every cohort here.",
    )

    _name_uniq = models.Constraint("UNIQUE(name)", "A name must be unique")

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        ranges = super().create(vals_list)
        ranges._add_partners_to_compute(ranges._current_spans())
        return ranges

    def write(self, vals):
        if _CLASSIFYING_FIELDS.isdisjoint(vals):
            return super().write(vals)
        spans = self._current_spans()
        result = super().write(vals)
        self._add_partners_to_compute(spans + self._current_spans())
        return result

    def unlink(self):
        spans = self._current_spans()
        result = super().unlink()
        self._add_partners_to_compute(spans)
        return result

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _current_spans(self):
        return [(band.min_value, band.max_value) for band in self]

    @staticmethod
    def _span_domain(min_value, max_value):
        """Partners a band with these bounds classifies.

        :param float min_value: first birth year of the band, inclusive
        :param float max_value: first birth year after it, 0 for open-ended
        :return: a domain over ``res.partner``
        """
        domain = Domain("birthdate", "!=", False)
        if (first_year := int(min_value)) > _FIRST_YEAR:
            domain &= Domain("birthdate", ">=", datetime.date(first_year, 1, 1))
        if _FIRST_YEAR < (next_year := int(max_value)) <= _LAST_YEAR:
            domain &= Domain("birthdate", "<", datetime.date(next_year, 1, 1))
        return domain

    def _add_partners_to_compute(self, spans):
        # res.partner.age_range_id depends on birthdate, and a birthdate does
        # not change when a cohort does -- so nothing invalidates the stored
        # value when the scale is edited, and it has to be re-applied here.
        #
        # Only a partner born inside a span this write touched can change band.
        # _check_band keeps active bands disjoint, so a birth year outside every
        # bound the write moved is still covered by whatever covered it before,
        # and re-applying the scale to the whole table would be re-deriving a
        # value that cannot have changed. Partners already pointing at one of
        # these bands are swept too, so a value that had drifted outside its own
        # band is repaired rather than pinned there.
        #
        # sudo because the classification must be consistent for everyone, not
        # only for the partners whoever edited the scale may read.
        domain = Domain.OR(starmap(self._span_domain, spans))
        if self.ids:
            domain |= Domain("age_range_id", "in", self.ids)
        partners = self.env["res.partner"].sudo().search(domain)
        if partners:
            self.env.add_to_compute(partners._fields["age_range_id"], partners)

    def _default_min_value(self):
        last = self.search([], order="min_value desc", limit=1)
        return last.max_value if last else 0.0
