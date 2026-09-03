from collections.abc import Set as AbstractSet

from odoo import api, models

# What the ORM itself accepts as a multi-value search term, mirroring
# odoo.orm.primitives. An `in` arrives as an OrderedSet, not as a list.
COLLECTION_TYPES = (list, tuple, AbstractSet)


class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['mixin.mail.thread.phone', 'res.partner']

    @property
    def _rec_names_search(self):
        return [*super()._rec_names_search, 'phone_mobile_search']

    @api.model
    def _search_display_name_match(self, operator, value, search_fnames):
        """Resolve a short term on the other name fields instead of failing.

        A Many2one autocomplete fires on the first keystroke, and the phone
        search refuses a term below ``_phone_search_min_length``. Left in the
        OR, that refusal takes down the whole lookup, so a contact could no
        longer be picked by typing one or two letters of its name.
        """
        if "phone_mobile_search" in search_fnames and self._phone_term_too_short(value):
            search_fnames = [
                fname for fname in search_fnames if fname != "phone_mobile_search"
            ]
        return super()._search_display_name_match(operator, value, search_fnames)

    @api.model
    def _phone_term_too_short(self, value):
        """Whether a search term is below the minimum the phone search accepts.

        An empty term is not too short: the phone search lets it through as a
        set/unset test rather than rejecting it.
        """
        minimum = self._phone_search_min_length
        if not minimum:
            return False
        values = value if isinstance(value, COLLECTION_TYPES) else [value]
        return any(
            isinstance(term, str) and 0 < len(term.strip()) < minimum for term in values
        )

    @api.onchange('phone', 'country_id', 'company_id')
    def _onchange_phone_validation(self):
        if self.phone:
            self.phone = self._phone_format(fname='phone', force_format='INTERNATIONAL') or self.phone
