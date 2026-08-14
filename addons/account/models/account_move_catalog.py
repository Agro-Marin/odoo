"""Product-catalog integration for account.move."""

# The catalog is the grid used to add products to a document from a picker
# rather than line by line. account.move participates in it through the shared
# `product.catalog.mixin` protocol; these are its answers to that protocol.
# Extracted from account_move.py.

from collections import defaultdict

from odoo import models
from odoo.fields import Domain


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_add_from_catalog(self):
        res = super().action_add_from_catalog()
        res["search_view_id"] = [
            self.env.ref("account.product_view_search_catalog").id,
            "search",
        ]
        return res

    def _get_action_add_from_catalog_extra_context(self):
        res = super()._get_action_add_from_catalog_extra_context()
        if self.is_purchase_document() and self.partner_id:
            res["search_default_seller_ids"] = self.partner_id.name

        res["product_catalog_currency_id"] = self.currency_id.id
        res["product_catalog_digits"] = self.line_ids._fields["price_unit"].get_digits(
            self.env
        )
        res["show_sections"] = bool(self.id)
        return res

    def _get_product_catalog_domain(self):
        domain = super()._get_product_catalog_domain()
        if self.is_sale_document():
            return domain & Domain("sale_ok", "=", True)
        elif self.is_purchase_document():
            return domain & Domain("purchase_ok", "=", True)
        else:  # In case of an entry
            return domain

    def _default_order_line_values(self, child_field=False):
        default_data = super()._default_order_line_values(child_field)
        new_default_data = self.env[
            "account.move.line"
        ]._get_product_catalog_lines_data()
        return {**default_data, **new_default_data}

    def _get_product_catalog_order_data(self, products, **kwargs):
        product_catalog = super()._get_product_catalog_order_data(products, **kwargs)
        for product in products:
            product_catalog[product.id] |= self._get_product_price_and_data(product)
        return product_catalog

    def _get_product_price_and_data(self, product):
        """Return a dict containing the price of the product: the list price ("Sales Price")
        for a sale document, otherwise the standard_price ("Cost").
        For a purchase document a partner-specific price may exist, so check the sellers
        set on the product and update the price and min_qty accordingly.
        """
        self.ensure_one()
        product_infos = {
            "price": product.list_price
            if self.is_sale_document()
            else product.standard_price
        }

        # Check if there is a price and a minimum quantity for the order's vendor.
        if self.is_purchase_document() and self.partner_id:
            seller = product._select_seller(
                partner_id=self.partner_id,
                quantity=None,
                date=self.invoice_date,
                uom_id=product.uom_id,
                ordered_by="min_qty",
                params={"order_id": self},
            )
            if seller:
                product_infos.update(
                    price=seller.price,
                    min_qty=seller.min_qty,
                )
        return product_infos

    def _get_product_catalog_record_lines(
        self, product_ids, *, section_id=None, **kwargs
    ):
        grouped_lines = defaultdict(lambda: self.env["account.move.line"])
        if section_id is None:
            section_id = (
                self.line_ids[:1].id
                if self.line_ids[:1].display_type == "line_section"
                else False
            )
        for line in self.line_ids:
            if (
                line.get_line_parent_section().id == section_id
                and line.display_type == "product"
                and line.product_id.id in product_ids
            ):
                grouped_lines[line.product_id] |= line
        return grouped_lines

    def _update_order_line_info(
        self,
        product_id,
        quantity,
        *,
        section_id=False,
        child_field="line_ids",
        **kwargs,
    ):
        """Update account_move_line information for a given product or create a
        new one if none exists yet.
        :param int product_id: The product, as a `product.product` id.
        :param int quantity: The quantity selected in the catalog
        :param int section_id: The id of section selected in the catalog.
        :return: The unit price of the product, based on the pricelist of the
                 sale order and the quantity selected.
        :rtype: float
        """
        # Several lines can share the same product and section (the catalog
        # aggregates them for display): operate on the first one only, both to
        # avoid writing the aggregated quantity on each of them and because
        # the price_unit read below requires a single record.
        move_line = self.line_ids.filtered(
            lambda line: (
                line.product_id.id == product_id
                and line.get_line_parent_section().id == section_id
            ),
        )[:1]
        if move_line:
            if quantity != 0:
                move_line.quantity = quantity
            elif self.state == "draft":
                price_unit = self._get_product_price_and_data(move_line.product_id)[
                    "price"
                ]
                # The catalog is designed to allow the user to select products quickly.
                # Therefore, sometimes they may select the wrong product or decide to remove
                # some of them from the quotation. The unlink is there for that reason.
                move_line.unlink()
                return price_unit
            else:
                move_line.quantity = 0
        elif quantity > 0:
            move_line = self.env["account.move.line"].create(
                {
                    "move_id": self.id,
                    "quantity": quantity,
                    "product_id": product_id,
                    "sequence": self._get_new_line_sequence(child_field, section_id),
                }
            )
        return move_line.price_unit

    def _is_readonly(self):
        """Return whether the move can no longer be edited via the catalog.

        Only a draft move is catalog-editable: `state != "draft"` also
        covers "posted" (matching the o2m field's own client-side
        `readonly="state != 'draft'"` in the form view), not just
        "cancel" — the previous narrower check let the catalog RPC route
        mutate/create lines on an already-posted, hash-protected entry.
        """
        self.ensure_one()
        return self.state != "draft"

    def _get_parent_field_on_child_model(self):
        return "move_id"

    def _is_line_valid_for_section_line_count(self, line):
        """Check if a line is valid for inclusion in the section's line count.

        :param recordset line: A record of a move line.
        :return: True if this line is a valid, else False.
        :rtype: bool
        """
        return (
            line.product_id
            and line.product_id.product_tmpl_id.type != "combo"
            and line.quantity > 0
        )
