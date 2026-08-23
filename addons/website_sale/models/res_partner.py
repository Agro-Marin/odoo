# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import SUPERUSER_ID, _, api, models
from odoo.fields import Domain


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.onchange("property_product_pricelist")
    def _onchange_property_product_pricelist(self):
        open_order = (
            self.env["sale.order"]
            .sudo()
            .search(
                [
                    ("partner_id", "=", self._origin.id),
                    ("pricelist_id", "=", self._origin.property_product_pricelist.id),
                    ("pricelist_id", "!=", self.property_product_pricelist.id),
                    ("website_id", "!=", False),
                    ("state", "=", "draft"),
                ],
                limit=1,
            )
        )

        if open_order:
            return {
                "warning": {
                    "title": _("Open Sale Orders"),
                    "message": _(
                        "This partner has an open cart. "
                        "Please note that the pricelist will not be updated on that cart. "
                        "Also, the cart might not be visible for the customer until you update the pricelist of that cart."
                    ),
                }
            }
        return None

    def _get_current_partner(self, *, order_sudo=False, **kwargs):
        """Override `portal` to get current partner from order_sudo if user is not signed up."""
        if order_sudo:
            return (
                (not order_sudo._is_anonymous_cart() and order_sudo.partner_id)
                or self.env["res.partner"]  # Avoid returning public user's partner
            )
        return super()._get_current_partner(order_sudo=order_sudo, **kwargs)

    def _get_fields_frontend_writable(self):
        """Override `portal` to make website whitelist fields writable in portal address."""
        frontend_writable_fields = super()._get_fields_frontend_writable()
        # Internal submission path: run as SUPERUSER to satisfy the editor
        # gate on ``get_fields_authorized`` (the field *names* are used as a
        # whitelist here; no metadata is exposed to the requesting user), as
        # ``extract_data`` already does.
        frontend_writable_fields.update(
            self.env["ir.model"]
            .with_user(SUPERUSER_ID)
            ._get("res.partner")
            ._get_fields_form_writable()
            .keys()
        )

        return frontend_writable_fields

    def _get_order_fiscal_position_recompute_domain(self):
        """Return a domain of sale orders for which we should recompute fiscal position after address update."""
        return Domain(
            [
                ("state", "=", "draft"),
                ("website_id", "!=", False),
                "|",
                ("partner_id", "in", self.ids),
                ("partner_shipping_id", "in", self.ids),
            ]
        )

    def write(self, vals):
        res = super().write(vals)
        if {"country_id", "vat", "zip"} & vals.keys() and self:
            # Recompute fiscal position for open website orders
            order_fpos_recompute_domain = (
                self._get_order_fiscal_position_recompute_domain()
            )
            if (
                orders_sudo := self.env["sale.order"]
                .sudo()
                .search(order_fpos_recompute_domain)
            ):
                orders_by_fpos = orders_sudo.grouped("fiscal_position_id")
                self.env.add_to_compute(
                    orders_sudo._fields["fiscal_position_id"], orders_sudo
                )
                if fpos_changed := orders_sudo.filtered(
                    lambda so: so not in orders_by_fpos.get(so.fiscal_position_id, []),
                ):
                    fpos_changed._recompute_taxes()
                    # other modules may extend the orders to recompute for
                    # non-draft orders (for ex. sale_subscription), we need
                    # to ensure to only recompute prices for draft orders
                    fpos_changed.filtered(
                        lambda order: order.state == "draft"
                    )._recompute_prices()
        return res
