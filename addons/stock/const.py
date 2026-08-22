import operator as py_operator

PY_OPERATORS = {
    "<": py_operator.lt,
    ">": py_operator.gt,
    "<=": py_operator.le,
    ">=": py_operator.ge,
    "=": py_operator.eq,
    "!=": py_operator.ne,
    "in": lambda elem, container: elem in container,
    "not in": lambda elem, container: elem not in container,
}

QUANTITY_FIELDS = (
    "qty_available",
    "qty_free",
    "qty_incoming",
    "qty_outgoing",
    "qty_available_virtual",
)

TEMPLATE_QUANTITY_FIELDS = tuple(f for f in QUANTITY_FIELDS if f != "qty_free")

INVENTORY_REFERENCE_CONFIRMED = "Product Quantity Confirmed"
INVENTORY_REFERENCE_UPDATED = "Product Quantity Updated"
INVENTORY_REFERENCE_RELOCATED = "Quantity Relocated"
INVENTORY_REFERENCE_PACKAGE_RELOCATED = "Package manually relocated"
INVENTORY_REFERENCE_REVERTED = "%s [reverted]"

ADVANCED_STOCK_OPTION_GROUPS = (
    "stock.group_stock_multi_locations",
    "stock.group_tracking_owner",
    "stock.group_tracking_lot",
)

TEMPLATE_STOCK_FLAGS = ("type", "is_storable", "tracking")
