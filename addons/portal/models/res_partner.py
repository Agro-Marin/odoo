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

        :return: True if the current user may edit ``self``
        :rtype: bool
        """
        self.ensure_one()
        current_partner = self._get_current_partner(**kwargs)
        if self == current_partner:
            return True
        # ``id = self.id`` first so Postgres uses the PK index and only
        # validates ``child_of`` + ``type`` on that single row, instead of
        # materialising every child to test one membership in Python.
        return bool(
            self.env["res.partner"].search_count(
                [
                    ("id", "=", self.id),
                    ("id", "child_of", current_partner.commercial_partner_id.id),
                    ("type", "in", ("invoice", "delivery", "other")),
                ],
                limit=1,
            )
        )

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
