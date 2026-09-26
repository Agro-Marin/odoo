{
    "name": "Trade Agreements",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "Blanket orders and order templates agreed with a partner, for both directions",
    "description": """
Trade Agreements
================

What an agreement with a customer or a vendor is, whichever the direction:

* **mixin.agreement** -- a partner, a validity period, an agreement type, its
  lines, the orders placed against it, and its life: draft, confirmed,
  closed, cancelled. A blanket order is confirmed only with a price and a
  quantity on every line; it is closed only once no order against it is
  still a quotation.
* **mixin.agreement.line** -- a product at an agreed price and quantity, and
  how much of it the confirmed orders have taken.
* **mixin.order.agreement** -- an order placed against an agreement takes its
  partner, terms, currency and products from it.

purchase_requisition (vendor blanket orders, purchase templates, calls for
tender) and sale_agreement (customer blanket orders) are its two directions.
    """,
    "author": "Odoo Community",
    "website": "https://www.odoo.com",
    "license": "LGPL-3",
    "depends": [
        "trade",
    ],
}
