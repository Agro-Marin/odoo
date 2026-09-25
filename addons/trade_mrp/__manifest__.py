{
    "name": "Trade Manufacturing",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "Kit (phantom BoM) quantities of order lines, for both directions",
    "description": """
Trade Manufacturing
===================

Bridge module connecting ``trade_stock`` with ``mrp``. A line that sells or
buys a kit is fulfilled by its components' moves, so what it has delivered or
received is derived from them through the kit's bill of materials:

* **mixin.order.line.stock** gains the kit's side of ``qty_transferred``: the
  BoM that applies to a line (the one its moves were exploded from once it is
  confirmed), the component moves, the quantity they make up, a line whose
  BoM is gone, and a dropshipped kit.

Only the direction differs, and ``TradeDirection`` states it: which component
moves go toward the partner, and which location is the partner's.
    """,
    "author": "Odoo Community",
    "website": "https://www.odoo.com",
    "license": "LGPL-3",
    "depends": [
        "trade_stock",
        "mrp",
    ],
    "auto_install": True,
}
