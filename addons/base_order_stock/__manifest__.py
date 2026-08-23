{
    "name": "Base Order Stock Integration",
    "version": "19.0.1.2.0",
    "category": "Hidden",
    "summary": "Stock/delivery tracking mixins for order types",
    "description": """
Base Order Stock Integration
=============================

Bridge module connecting ``base_order`` with ``stock``.  Provides abstract
mixins for delivery/receipt tracking shared between sale_stock and
purchase_stock.

Mixins:
-------
* **mixin.order.stock** — transfer status, effective date, incoterms
* **mixin.order.line.stock** — transfer status, qty_to_transfer, move helpers

``transfer_state`` is computed per line from the quantities and rolled up to
the order through ``mixin.order.state.rollup``, the same engine ``base_order``
uses for ``invoice_state``.  Both levels are IDENTICAL between sale_stock and
purchase_stock, which override the wording only; ``_compute_date_effective``
is the one piece that genuinely differs (customer location filter for sale,
non-supplier for purchase).
    """,
    "author": "Odoo Community",
    "website": "https://www.odoo.com",
    "license": "LGPL-3",
    "depends": [
        "base_order",
        "stock",
    ],
}
