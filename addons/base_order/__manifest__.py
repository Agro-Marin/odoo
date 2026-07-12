{
    "name": "Base Order Management",
    "version": "19.0.3.0.0",
    "category": "Hidden",
    "summary": "Foundation mixins for sale and purchase order types",
    "description": """
Base Order Management
=====================

Provides abstract mixins that consolidate common patterns shared between
sale.order and purchase.order. These are AbstractModel classes — no tables,
no views, no menus.

Mixins:
-------
* **order.mixin** — state machine, validation registry, workflow actions,
  mail/portal/catalog integration, duplicate detection
* **order.amount.mixin** — tax computation and credit warning (order-level)
* **order.line.amount.mixin** — pricing and tax computation (line-level)
* **order.line.fields.mixin** — common structural fields, CRUD guards,
  transfer tracking
* **order.invoice.mixin** — invoice tracking (order-level)
* **order.line.invoice.mixin** — invoice tracking (line-level)
* **order.merge.mixin** — quotation/RFQ merge system

Field names match actual sale/purchase conventions (product_qty, qty_invoiced,
amount_taxexc_invoiced, etc.) for drop-in adoption.
    """,
    "depends": [
        "mail",
        "portal",
        "account",
        "product",
    ],
    "author": "Odoo Community",
    "website": "https://www.odoo.com",
    "license": "LGPL-3",
}
