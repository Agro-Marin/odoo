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

TRANSFER_STATE = [
    ("no", "Nothing to transfer"),
    ("to do", "To transfer"),
    ("partial", "Partially transferred"),
    ("done", "Fully transferred"),
    ("over done", "Over transferred"),
]


# ════════════════════════════════════════════════════════════════════
# ORDER-LEVEL STOCK MIXIN
# ════════════════════════════════════════════════════════════════════


class OrderStockMixin(models.AbstractModel):
    """Order-level delivery/receipt tracking.

    Provides ``transfer_state``, ``date_effective``, incoterm fields,
    and the ``_get_action_view_picking()`` helper shared between
    sale_stock and purchase_stock.

    Requires from concrete model:
        ``picking_ids`` — One2many to ``stock.picking``
    """

    _name = "order.stock.mixin"
    _description = "Order Stock Integration"

    # ─── Transfer Status ─────────────────────────────────────────

    transfer_state = fields.Selection(
        selection=TRANSFER_STATE,
        string="Transfer Status",
        compute="_compute_transfer_state",
        store=True,
    )

    # ─── Effective Date ──────────────────────────────────────────

    date_effective = fields.Datetime(
        string="Effective Date",
        compute="_compute_date_effective",
        store=True,
        copy=False,
    )

    # ─── Incoterms ───────────────────────────────────────────────

    incoterm_id = fields.Many2one(
        comodel_name="account.incoterms",
        string="Incoterm",
        help="International Commercial Terms are a series of predefined commercial "
        "terms used in international transactions.",
    )
    incoterm_location = fields.Char(string="Incoterm Location")

    # ─── Compute: Transfer State ─────────────────────────────────

    @api.depends("picking_ids", "picking_ids.state")
    def _compute_transfer_state(self):
        """Compute transfer status from picking states.

        IDENTICAL in sale_stock and purchase_stock.  The logic:
        - No pickings or all canceled → ``False``
        - All done/canceled → ``'done'``
        - Some (but not all) done → ``'partial'``
        - Otherwise → ``'to do'``
        """
        for order in self:
            if not order.picking_ids or all(
                p.state == "cancel" for p in order.picking_ids
            ):
                order.transfer_state = False
            elif all(p.state in ["done", "cancel"] for p in order.picking_ids):
                order.transfer_state = "done"
            elif any(p.state == "done" for p in order.picking_ids):
                order.transfer_state = "partial"
            else:
                order.transfer_state = "to do"

    # ─── Compute: Effective Date ─────────────────────────────────

    @api.depends(
        "picking_ids.date_done",
        "picking_ids.state",
        "picking_ids.location_dest_id.usage",
    )
    def _compute_date_effective(self):
        """Compute completion date from first done picking.

        Delegates filtering to ``_filter_effective_pickings()`` hook:
        - Sale: customer-destination pickings
        - Purchase: non-supplier-destination pickings

        The dependencies cover every field those hooks read; ``date_done``
        alone would leave the date stale when a picking reaches ``done`` or
        its destination usage changes without ``date_done`` itself changing.
        """
        for order in self:
            pickings = order._filter_effective_pickings(order.picking_ids)
            dates = [d for d in pickings.mapped("date_done") if d]
            order.date_effective = min(dates, default=False)

    def _filter_effective_pickings(self, pickings):
        """Filter pickings for effective date computation.

        Default: done pickings with ``date_done`` set.

        Sale overrides: ``location_dest_id.usage == 'customer'``
        Purchase overrides: ``location_dest_id.usage != 'supplier'``
        """
        return pickings.filtered(
            lambda p: p.state == "done" and p.date_done,
        )

    # ─── Actions ─────────────────────────────────────────────────

    def _get_action_view_picking(self, pickings):
        """Build the action displaying ``pickings``.

        Form view when there is exactly one picking, list view otherwise
        (including when ``pickings`` is empty — the domain must still be set,
        or the action falls back to listing every picking in the database).

        Concrete models tailor the defaults of records created from the
        action through :meth:`_get_action_view_picking_context`.

        :param pickings: recordset of ``stock.picking``
        :returns: action dict
        """
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock.action_picking_tree_all",
        )
        if len(pickings) == 1:
            form_view = [(self.env.ref("stock.view_stock_picking_form").id, "form")]
            action["views"] = form_view + [
                (state, view)
                for state, view in action.get("views", [])
                if view != "form"
            ]
            action["res_id"] = pickings.id
        else:
            action["domain"] = [("id", "in", pickings.ids)]
        action["context"] = self._get_action_view_picking_context(pickings)
        return action

    def _get_action_view_picking_context(self, pickings):
        """Context of the picking action: defaults for records created from it.

        Replaces the base action's context wholesale, which is what drops its
        default filtering on operation type.
        """
        return {}


# ════════════════════════════════════════════════════════════════════
# LINE-LEVEL STOCK MIXIN
# ════════════════════════════════════════════════════════════════════


class OrderLineStockMixin(models.AbstractModel):
    """Line-level stock move tracking.

    Provides ``qty_to_transfer`` and the ``_get_stock_moves_outgoing_incoming``
    hook shared between sale_stock and purchase_stock.

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
    """

    _name = "order.line.stock.mixin"
    _description = "Order Line Stock Integration"

    # ─── Fields ───────────────────────────────────────────────────

    # Declared plain and writable by base_order's order.line.fields.mixin, so
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
