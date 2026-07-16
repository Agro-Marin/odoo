# Part of Odoo. See LICENSE file for full copyright and licensing details.


class AvcoAccumulator:
    """Running weighted-average-cost state — the single source of truth for the AVCO
    recurrence.

    The same recurrence is needed in two places that must never disagree:
    ``product._run_average_batch`` (the live valuation that *sets* the average cost)
    and ``stock.avco.report`` (the audit report that *justifies* it). Keeping one
    implementation here prevents the justification from drifting away from the value.

    Quantities are floats in the product's default UoM; values are in the company
    currency. ``uom`` (optional) is used only for the divide-by-zero guard.
    """

    __slots__ = ('_uom', 'quantity', 'unit_cost', 'value')

    def __init__(self, quantity=0.0, value=0.0, unit_cost=0.0, uom=None):
        self.quantity = quantity
        self.value = value
        self.unit_cost = unit_cost
        self._uom = uom

    def _has_quantity(self):
        if self._uom is not None:
            return not self._uom.is_zero(self.quantity)
        return bool(self.quantity)

    def add_in(self, in_qty, in_value):
        """Receive ``in_qty`` units worth ``in_value``; returns the value added."""
        previous_qty = self.quantity
        self.quantity += in_qty
        if previous_qty > 0:
            # Regular case: accumulate the value and re-average.
            self.value += in_value
            if self._has_quantity():
                self.unit_cost = self.value / self.quantity
        else:
            # Coming from a negative (oversold) position: reset the average to the
            # incoming unit price and re-value the whole (possibly still negative) qty.
            if in_qty:
                self.unit_cost = in_value / in_qty
            self.value = self.unit_cost * self.quantity
        return in_value

    def add_out(self, out_qty):
        """Issue ``out_qty`` units at the current average cost; returns the value removed.

        The average cost is intentionally left unchanged by an outgoing move."""
        out_value = out_qty * self.unit_cost
        self.value -= out_value
        self.quantity -= out_qty
        return out_value

    def set_unit_cost(self, unit_cost):
        """Apply a manual unit-cost revaluation (``product.value``); returns the delta."""
        added_value = unit_cost * self.quantity - self.value
        self.unit_cost = unit_cost
        self.value = unit_cost * self.quantity
        return added_value
