"""
Order Stock Integration Mixins

Bridge mixins connecting order types with stock/delivery tracking.
Consolidates the transfer status computation and effective date logic
shared between sale_stock and purchase_stock.

The order-level ``_compute_transfer_state`` is IDENTICAL between both
modules.  Only ``_compute_date_effective`` differs — sale filters to
customer-destination pickings, purchase to non-supplier-destination.

Field naming matches actual sale_stock/purchase_stock conventions:
``transfer_state``, ``date_effective``, ``qty_to_transfer``.
"""

from odoo import api, fields, models

# ════════════════════════════════════════════════════════════════════
# ORDER-LEVEL STOCK MIXIN
# ════════════════════════════════════════════════════════════════════


class MixinOrderLineStock(models.AbstractModel):
    """Line-level stock move tracking.

    Provides ``qty_to_transfer``, ``_get_procurement_qty()``, and the two
    move-classification hooks shared between sale_stock and purchase_stock.

    The ``_compute_qty_transferred`` implementations differ too much to unify:
    - Sale: simple outgoing/incoming classification by location dest
    - Purchase: complex return + BOM kit + dropship handling

    ``qty_to_transfer`` is derived from the result here, so the overrides only
    have to produce ``qty_transferred``.

    Requires from concrete model:
        ``move_ids`` — One2many to ``stock.move`` (different inverse per model)
        ``product_qty`` — ordered quantity
        ``qty_transferred`` — transferred quantity
        ``product_uom_id`` — UoM for quantity conversion

    Must implement:
        ``_get_stock_moves_outgoing_incoming()`` — classify by warehouse
            direction
        ``_get_procurement_moves()`` — classify by procurement intent
    """

    _name = "mixin.order.line.stock"
    _description = "Order Line Stock Integration"

    # ─── Fields ───────────────────────────────────────────────────

    # Declared plain and writable by base_order's mixin.order.line.fields, so
    # orders work without stock installed; this bridge turns it into a stored
    # compute.  Deliberately no ``string``/``copy``: both are inherited from
    # base_order, and restating them here would silently fork the label and
    # copy semantics.
    qty_to_transfer = fields.Float(
        digits="Product Unit",
        compute="_compute_qty_to_transfer",
        store=True,
    )

    # ─── Compute: Remaining Quantity ──────────────────────────────

    @api.depends("product_qty", "qty_transferred")
    def _compute_qty_to_transfer(self):
        """Derive the outstanding quantity from the transferred one.

        A compute of its own rather than a co-assignment inside each
        ``_compute_qty_transferred`` override: every override — sale, purchase,
        and sale_mrp's kit branches — otherwise has to remember to refresh this
        too, and forgetting leaves a fully transferred line reading 'partial'.
        Keying off ``qty_transferred`` also picks up manual edits to it, which
        the co-assignment could not.
        """
        for line in self:
            line.qty_to_transfer = max(0.0, line.product_qty - line.qty_transferred)

    # ─── Helpers ──────────────────────────────────────────────────

    def _get_stock_moves_outgoing_incoming(self, **kwargs):
        """Classify stock moves as outgoing and incoming.

        THE KEY DIFFERENCE between sale and purchase:
        - Sale: outgoing = customer destination, incoming = returns
        - Purchase: outgoing = returns to supplier, incoming = receipts

        Overrides may add keyword arguments of their own — sale_stock takes a
        ``strict`` flag — so callers that are not model-specific must pass none.

        :returns: ``(outgoing_moves, incoming_moves)`` tuple of recordsets
        """
        raise NotImplementedError(
            f"{self._name} must implement _get_stock_moves_outgoing_incoming()",
        )

    # ─── Procurement Quantity ─────────────────────────────────────

    def _get_procurement_qty(self, previous_product_qty=False):
        """Quantity the line's stock moves have already procured.

        Moves that procure the line count positive, moves that hand the goods
        back count negative.  Which recordset is which is the only thing that
        varies per order type, and ``_get_procurement_moves()`` decides it —
        sale and purchase used to carry this same arithmetic twice with the
        two signs swapped.

        ``previous_product_qty`` is unused here: the moves already reflect any
        quantity change.  It stays in the signature for the overrides that
        cannot read the answer off the moves — kit lines and subscriptions
        compare against the pre-write quantity instead.

        :param previous_product_qty: ``{line_id: qty}`` captured before the
            write that triggered this, or ``False``.  Sale passes it as this
            argument; purchase passes its own through the context (see
            ``purchase_mrp``), and the two are not in the same UoM, so they
            are deliberately left as separate channels.
        :returns: quantity in the line's UoM
        """
        self.ensure_one()
        procured_moves, returned_moves = self._get_procurement_moves()
        return self._sum_moves_qty(procured_moves) - self._sum_moves_qty(returned_moves)

    def _get_procurement_moves(self):
        """Split the line's moves into the ones that procure it and the ones
        that hand the goods back.

        Sale: deliveries procure, customer returns hand back.
        Purchase: receipts procure, returns to the vendor hand back.

        Kept apart from :meth:`_get_stock_moves_outgoing_incoming` because that
        one classifies by warehouse direction, which is the mirror image
        between the two order types; this one classifies by intent, which is
        not.

        :returns: ``(procured_moves, returned_moves)`` tuple of recordsets
        """
        raise NotImplementedError(
            f"{self._name} must implement _get_procurement_moves()",
        )

    def _get_transferable_moves(self):
        """The line's moves that can count toward a transferred quantity.

        Both bridges open ``_get_stock_moves_outgoing_incoming()`` with this
        same filter before classifying by direction: a cancelled move never
        counts, an inventory-destination move is an adjustment rather than a
        transfer, and a move for another product belongs to a kit component,
        not to this line.
        """
        self.ensure_one()
        return self.move_ids.filtered(
            lambda m: (
                m.state != "cancel"
                and m.location_dest_usage != "inventory"
                and m.product_id == self.product_id
            ),
        )

    def _sum_moves_qty(self, moves):
        """Total of ``moves``, converted to the line's UoM.

        A done move counts what actually moved; any other move counts what it
        still intends to move.
        """
        return sum(
            move.product_uom_id._compute_quantity(
                move.quantity if move.state == "done" else move.product_uom_qty,
                self.product_uom_id,
                rounding_method="HALF-UP",
            )
            for move in moves
        )
