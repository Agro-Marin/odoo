from datetime import timedelta

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools.translate import _

# How far back the "Sold" / "Purchased" statistics on a product look.
ORDERED_QTY_WINDOW_DAYS = 365


class ProductProduct(models.Model):
    """Product-side helpers shared by the order types.

    sale and purchase each hang the same four things off ``product.product``:
    a catalog "is this product already on the open order" flag (compute +
    search), a "product is already used on order lines" guard that blocks a
    unit-of-measure change, and the bulk UoM rewrite that follows once the
    guard passes. None of it is order-type specific beyond the line model and
    the field name, so the bodies live here and the concrete modules supply
    those two.
    """

    _inherit = "product.product"

    # ------------------------------------------------------------
    # CATALOG — is this product on the order being edited?
    # ------------------------------------------------------------

    def _compute_is_in_order(self, line_model, field_name):
        """Fill the boolean ``field_name`` from the ``order_id`` context key.

        The catalog kanban renders products with the order it was opened from
        in context; the flag drives the "already added" ribbon.

        :param str line_model: order line model to look in
        :param str field_name: Boolean field on ``product.product`` to fill
        """
        order_id = self.env.context.get("order_id")
        if not order_id:
            self[field_name] = False
            return

        counts = {
            product.id: count
            for product, count in self.env[line_model]._read_group(
                domain=[("order_id", "=", order_id)],
                groupby=["product_id"],
                aggregates=["__count"],
            )
        }
        for product in self:
            product[field_name] = bool(counts.get(product.id))

    def _search_is_in_order(self, line_model):
        """Search domain for the catalog flag computed by ``_compute_is_in_order``.

        Returns a match-nothing domain when no order is in context. Building
        the domain from ``context.get("order_id", "")`` instead — as sale did —
        searches ``("order_id", "=", "")``, which is not a no-op: an empty
        string is falsy, so it matches every line whose ``order_id`` is unset.
        There are none in practice (``order_id`` is required), but the query
        was still issued and the intent was the opposite of what was written.

        :param str line_model: order line model to look in
        """
        order_id = self.env.context.get("order_id")
        if not order_id:
            return [("id", "in", [])]
        product_ids = (
            self.env[line_model]
            .search_fetch([("order_id", "=", order_id)], ["product_id"])
            .product_id.ids
        )
        return [("id", "in", product_ids)]

    # ------------------------------------------------------------
    # ORDERED QUANTITY STATISTICS
    # ------------------------------------------------------------

    def _compute_ordered_qty(self, field_name, model, group, date_field, domain):
        """Fill ``field_name`` with the quantity ordered over the last year.

        Sale's "Sold" and purchase's "Purchased" are the same statistic read
        from different tables: sum ``product_uom_qty`` over confirmed documents
        inside a rolling window, rounded to the product's own unit. Only the
        source model, its date field, the gating group and the confirmed-state
        domain differ, and callers pass those.

        The total is left at 0 for users outside ``group`` rather than computed
        and hidden — same reasoning as ``res.partner._compute_order_count``.

        :param str field_name: Float field on ``product.product`` to fill
        :param str model: model to aggregate (``sale.report``, an order line…)
        :param str group: group the user must hold for a non-zero total
        :param str date_field: date field on ``model`` bounding the window
        :param domain: extra domain, typically restricting to confirmed state
        """
        self[field_name] = 0.0
        if not self.env.user.has_group(group):
            return

        date_from = fields.Date.today() - timedelta(days=ORDERED_QTY_WINDOW_DAYS)
        quantities = {
            product.id: qty
            for product, qty in self.env[model]._read_group(
                Domain.AND(
                    [
                        domain,
                        [
                            ("product_id", "in", self.ids),
                            (date_field, ">=", date_from),
                        ],
                    ],
                ),
                ["product_id"],
                ["product_uom_qty:sum"],
            )
        }
        for product in self:
            # New (unsaved) products have no id to group by and no history.
            if product.id:
                product[field_name] = product.uom_id.round(
                    quantities.get(product.id, 0),
                )

    # ------------------------------------------------------------
    # UNIT OF MEASURE
    # ------------------------------------------------------------

    def _has_order_lines(self, line_model):
        """Whether any line of ``line_model`` references a product in ``self``.

        ``sudo`` on purpose: this gates a UoM change, and the answer must not
        depend on which orders the current user happens to be allowed to read.

        :param str line_model: order line model to look in
        :rtype: bool
        """
        return bool(
            self.env[line_model]
            .sudo()
            .search_count([("product_id", "in", self.ids)], limit=1),
        )

    def _update_uom_on_order_lines(self, line_model, to_uom_id):
        """Rewrite ``product_uom_id`` on every ``line_model`` line of ``self``.

        Refuses the change when a line already uses a unit *other* than the
        product's own: those lines carry a quantity expressed in that unit, and
        rewriting the unit alone would silently reinterpret the quantity.

        The lines are flushed before returning so that the ``product.template``
        write that follows this call sees them, rather than racing the pending
        ORM flush.

        :param str line_model: order line model to rewrite
        :param int to_uom_id: id of the ``uom.uom`` to move the lines to
        :raise UserError: if a line uses a unit other than the product's own
        """
        for uom, product, lines in self.env[line_model]._read_group(
            [("product_id", "in", self.ids)],
            ["product_uom_id", "product_id"],
            ["id:recordset"],
        ):
            if uom != product.product_tmpl_id.uom_id:
                raise UserError(
                    _(
                        "Other units of measure (e.g., %(problem_uom)s) have already "
                        "been used for this product. The unit of measure cannot be "
                        "changed from %(uom)s. If you want to change it, please "
                        "archive the product and create a new one.",
                        problem_uom=uom.display_name,
                        uom=product.product_tmpl_id.uom_id.display_name,
                    ),
                )
            lines.product_uom_id = to_uom_id
            lines.flush_recordset()
