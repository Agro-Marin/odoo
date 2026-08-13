"""Constants shared by stock's search and quantity implementations.

They live here rather than in a model module because four models import
``PY_OPERATORS`` and none of them owns it: a lookup table reached by
``from odoo.addons.stock.models.product_product import PY_OPERATORS`` makes
``stock.lot`` and ``mrp`` depend on a *model file* for a dict of comparisons.
"""

import operator as py_operator

# Domain operators that can be evaluated in Python against an already-computed
# value. A search on a non-stored quantity field takes the aggregate-in-Python
# path for these and falls back to per-record filtering for the rest.
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

# The quantity fields `product.product._prepare_quantities_vals` fills, in one
# place so a new one cannot be added to the computation and forgotten by the
# callers that zero or roll them up.
QUANTITY_FIELDS = (
    "qty_available",
    "qty_free",
    "qty_incoming",
    "qty_outgoing",
    "qty_available_virtual",
)

# `product.template` rolls up every quantity except `qty_free`, which it does
# not expose: "free to use" has no single meaning across a template's variants.
TEMPLATE_QUANTITY_FIELDS = tuple(f for f in QUANTITY_FIELDS if f != "qty_free")
