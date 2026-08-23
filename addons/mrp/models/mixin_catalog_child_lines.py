from odoo import api, models
from odoo.fields import Command


class MixinCatalogChildLines(models.AbstractModel):
    """Product-catalog editing for a record whose lines live in a named child field.

    `mixin.product.catalog` leaves `_update_order_line_info` a `return 0` stub for
    each consumer to implement, and the two manufacturing consumers implemented the
    same thing: `mrp.bom` over `bom_line_ids` / `byproduct_ids`, `mrp.production`
    over `move_raw_ids` / `move_byproduct_ids`. The bodies were the same shape down
    to the `if not child_field: return 0` guard, differing only in which field
    carries the quantity -- which is what the two hooks below name.

    They are not folded into `mixin.product.catalog` itself: the other four
    implementations in the tree (`base_order`, `account`, `repair`, and `delivery`'s
    override) carry sections, editable-state rules and removed-line pricing that this
    shape has no place for. This is the manufacturing pair, not a universal one.
    """

    _name = "mixin.catalog.child.lines"
    _description = "Catalog Lines Held In A Child Field"

    def _update_catalog_line_quantity(self, line, quantity, **kwargs):
        """Write `quantity` onto an existing line. Override to name the field."""
        raise NotImplementedError

    def _get_new_catalog_line_values(self, product_id, quantity, **kwargs):
        """The values a new line is created with. Override to name the field."""
        raise NotImplementedError

    @api.model
    def _get_catalog_line_price(self, product_id):
        return self.env["product.product"].browse(product_id).standard_price

    def _get_product_catalog_record_lines(
        self, product_ids, *, child_field=False, **kwargs
    ):
        if not child_field:
            return {}
        return (
            self[child_field]
            .filtered(lambda line: line.product_id.id in product_ids)
            .grouped("product_id")
        )

    def _update_order_line_info(
        self, product_id, quantity, *, child_field=False, **kwargs
    ):
        if not child_field:
            return 0
        line = self[child_field].filtered(lambda line: line.product_id.id == product_id)
        if line:
            if quantity != 0:
                self._update_catalog_line_quantity(line, quantity, **kwargs)
            else:
                line.unlink()
        elif quantity > 0:
            self.write(
                {
                    child_field: [
                        Command.create(
                            self._get_new_catalog_line_values(
                                product_id, quantity, **kwargs
                            )
                        )
                    ]
                }
            )
            # Written again on the record that now exists. On `mrp.production` the
            # child is a `stock.move`, whose `product_uom_qty` is computed and stored
            # from `product_qty` (Appendix A), so the value passed to `create` is
            # overwritten by the compute and only a `write` afterwards survives.
            self._update_catalog_line_quantity(
                self[child_field].filtered(
                    lambda line: line.product_id.id == product_id
                )[-1:],
                quantity,
                **kwargs,
            )
        return self._get_catalog_line_price(product_id)
