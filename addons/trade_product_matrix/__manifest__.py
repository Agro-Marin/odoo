{
    "name": "Trade Product Matrix",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "The variant grid of an order, in either direction",
    "description": """
Trade Product Matrix
====================

Bridge module connecting ``trade`` with ``product_matrix``:
``mixin.order.product.matrix`` loads a product template's variant grid into
an order, applies the quantities edited in it back to the order's lines, and
prints the grids of the order's configurable products on its report. Written
once for sales and purchase orders; a direction names whether the grid shows
extra prices, which lines the grid leaves alone, which templates the report
prints and the message for a variant on several lines.
    """,
    "author": "Odoo Community",
    "website": "https://www.odoo.com",
    "license": "LGPL-3",
    "depends": [
        "trade",
        "product_matrix",
    ],
}
