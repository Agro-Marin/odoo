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
