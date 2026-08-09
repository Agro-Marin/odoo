# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models
from odoo.fields import Domain


class CalendarPrivacyMixin(models.AbstractModel):
    """Delegate record visibility to the ``calendar.event`` a record hangs off.

    ``calendar.event`` protects private events with a matched pair: the
    per-record predicate ``_check_private_event_conditions``, used to mask field
    values after fetching, and its search-domain complement
    ``_get_default_privacy_domain``, used to keep a domain, an order or a
    group-by from becoming an oracle. Neither can be expressed as an
    ``ir.rule``: the default-privacy branch has to read ``res.users.settings``
    through ``sudo()``, which a static domain cannot do.

    Every model hanging off an event inherits the same obligation, and until
    this mixin existed none of them met it. ``calendar.attendee`` handed any
    employee the participants, e-mails and RSVP states of anyone's private
    event; ``calendar.recurrence`` was readable *and writable* by them. Both are
    reached through this one mixin, so the rule lives in a single place and
    cannot drift from the event's own.

    An inheriting model states which field links it to the event through
    ``_privacy_event_fname``, and gets the guard for free.

    Guarding ``_search`` alone is enough to cover reading by id as well: for any
    field with a column, ``BaseModel.fetch`` resolves the records with
    ``self._search([("id", "in", self.ids)])`` and raises an access error for
    whatever the search did not return (``odoo/orm/models/mixins/read.py``). So
    a hidden record is *denied*, not blanked -- which is both stronger than
    masking and safer, since masking writes ``False`` into a field cache shared
    by every environment in the transaction, including the ``sudo()`` ones that
    legitimately need the real value.
    """

    _name = "calendar.privacy.mixin"
    _description = "Calendar Privacy Delegation"

    _privacy_event_fname = "event_id"

    @api.model
    def _get_privacy_domain(self) -> Domain:
        """Domain selecting the records whose event the user may see.

        The default covers a many2one link. ``any`` on a many2one searches the
        comodel with ``active_test=False`` (see ``odoo/orm/domain/constants.py``),
        which is what we want: an archived event still has attendees, and hiding
        them would be a behaviour change rather than a privacy gain. A model
        linked through an x2many must override, because ``any`` on an x2many
        searches with the *field's* context instead and archived events drop out.
        """
        events = self.env["calendar.event"]
        return Domain(
            self._privacy_event_fname,
            "any",
            Domain(events._get_default_privacy_domain()),
        )

    def _privacy_hidden(self):
        """Subset of ``self`` whose event(s) the current user may not see.

        Reuses ``calendar.event._check_private_event_conditions`` rather than
        re-deriving the rule, so this cannot disagree with what the event model
        itself hides.
        """
        if not self:
            return self
        fname = self._privacy_event_fname
        events = self[fname].sudo()
        hidden_ids = set(
            events.filtered(lambda event: event._check_private_event_conditions()).ids
        )
        if not hidden_ids:
            return self.browse()
        # A record linked to no event at all protects nothing and is left alone;
        # otherwise it is hidden only when *every* event it hangs off is.
        return self.filtered(
            lambda record: (linked := record[fname].ids) and not set(linked) - hidden_ids
        )

    def _search(
        self,
        domain,
        offset=0,
        limit=None,
        order=None,
        *,
        active_test=True,
        bypass_access=False,
    ):
        if not (self.env.su or bypass_access):
            domain = Domain.AND([domain, self._get_privacy_domain()])
        return super()._search(
            domain,
            offset=offset,
            limit=limit,
            order=order,
            active_test=active_test,
            bypass_access=bypass_access,
        )
