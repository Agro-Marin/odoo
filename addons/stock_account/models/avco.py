class AvcoAccumulator:
    __slots__ = ("_uom", "quantity", "unit_cost", "value")

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
        previous_qty = self.quantity
        self.quantity += in_qty
        if previous_qty > 0:
            self.value += in_value
            if self._has_quantity():
                self.unit_cost = self.value / self.quantity
        else:
            if in_qty:
                self.unit_cost = in_value / in_qty
            self.value = self.unit_cost * self.quantity
        return in_value

    def add_out(self, out_qty):
        out_value = out_qty * self.unit_cost
        self.value -= out_value
        self.quantity -= out_qty
        return out_value

    def set_unit_cost(self, unit_cost):
        added_value = unit_cost * self.quantity - self.value
        self.unit_cost = unit_cost
        self.value = unit_cost * self.quantity
        return added_value
