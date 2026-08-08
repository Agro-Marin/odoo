from odoo import api, models
from odoo.fields import Domain


class ResPartner(models.Model):
    """Portal-facing hooks on res.partner: writable-field whitelist and edit-permission gates."""

    _inherit = "res.partner"

    @api.model
    def _get_frontend_writable_fields(self):
        """Define the fields a portal/public user can change on their contact and address records.

        :rtype: set
        """
        return {
            "name",
            "phone",
            "email",
            "street",
            "street2",
            "city",
            "state_id",
            "country_id",
            "zip",
            "vat",
            "company_name",
        }

    def _can_edit_country(self):
        """Override hook: whether the partner's country can still be changed.

        Default is True; modules that issue documents (accounting, fiscal localisation)
        override to return False once invoices/orders have been generated.
        """
        self.ensure_one()
        return True

    def can_edit_vat(self):
        """`vat` is a commercial field, synced between the parent (commercial
        entity) and the children. Only the commercial entity should be able to
        edit it (as in backend)."""
        self.ensure_one()
        return not self.parent_id

    def _can_be_edited_by_current_customer(self, **kwargs):
        """Security gate: may the current portal user edit this partner record?

        Allowed when the partner is the user themselves, or a child contact of
        the user's commercial partner with type ``invoice``, ``delivery``, or
        ``other``. Used by every ``/my/address`` mutation in
        :class:`portal.controllers.portal.CustomerPortal` — bypassing this check
        lets a portal user mutate any address.

        Singleton predicate, kept because that is what the mutation routes ask
        (one partner, one answer) and what overrides extend
        (``delivery_mondialrelay``). Anything iterating addresses should call
        :meth:`_filter_editable_by_current_customer` instead — see there.

        :return: True if the current user may edit ``self``
        :rtype: bool
        """
        self.ensure_one()
        return bool(self._filter_editable_by_current_customer(**kwargs))

    def _filter_editable_by_current_customer(self, **kwargs):
        """Subset of ``self`` the current portal user may edit, in one query.

        Same rule as :meth:`_can_be_edited_by_current_customer`, answered for a
        whole recordset at once. ``/my/addresses`` renders one card per address
        and asked the singleton question inside the ``t-foreach``, so the page
        cost a ``search_count`` (plus its record-rule machinery) per address:
        measured at 32 queries for 12 addresses, growing linearly with a
        customer's address book. This answers the same thing in one search.

        ``id in self.ids`` before ``child_of`` for the reason the singleton
        version gave: Postgres resolves the primary key first and validates the
        hierarchy and type only on those rows, rather than materialising every
        descendant of the commercial partner to intersect in Python.

        :return: the editable subset of ``self``
        :rtype: res.partner
        """
        if not self:
            return self
        current_partner = self._get_current_partner(**kwargs)
        editable = self & current_partner
        candidates = self - current_partner
        if candidates:
            editable |= self.env["res.partner"].search(
                [
                    ("id", "in", candidates.ids),
                    ("id", "child_of", current_partner.commercial_partner_id.id),
                    ("type", "in", ("invoice", "delivery", "other")),
                ]
            )
        return editable

    @api.model
    def _get_current_partner(self, **kwargs):
        """Return the partner backing the current user, or an empty recordset for public sessions.

        :param kwargs: ignored at this level; downstream overrides (e.g. sale's
                       order-flow) may resolve the partner from a sale_order_id
                       or similar context parameter.
        :rtype: res.partner
        """
        if self.env.user._is_public():
            return self.env["res.partner"]
        return self.env.user.partner_id

    def _get_billing_address_domain(self):
        """Domain selecting child contacts usable as a billing address (or self).

        Counterpart of :meth:`_get_delivery_address_domain`, which already
        existed; this one was inlined in ``/my/addresses`` instead, so only half
        of the pair could be overridden by a localisation.
        """
        return Domain(
            [
                ("id", "child_of", self.ids),
                "|",
                ("type", "in", ["invoice", "other"]),
                ("id", "=", self.id),
            ]
        )

    def _get_delivery_address_domain(self):
        """Domain selecting child contacts usable as a delivery address (or self)."""
        return Domain(
            [
                ("id", "child_of", self.ids),
                "|",
                ("type", "in", ["delivery", "other"]),
                ("id", "=", self.id),
            ]
        )
