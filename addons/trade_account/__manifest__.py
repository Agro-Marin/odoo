{
    "name": "Trade Invoicing",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "Invoicing for the order kernel: invoices and bills from orders, in either direction",
    "description": """
Trade Invoicing
===============

Bridge module connecting ``trade`` with ``account``. What an order needs to
invoice, written once for both directions:

* **mixin.order.invoice** — invoices of an order, its invoice status, the
  journal it invoices in, invoiced and to-invoice amounts, invoice creation
  and down payments, the partner's credit warning, and the draft invoices a
  cancellation cancels
* **mixin.order.line.invoice** — quantities and amounts invoiced per line,
  their state, and the journal-item values an order line invoices as
* **mixin.order.line.match** / **mixin.order.document.match** — the SQL
  matching grids between order lines and invoice lines
* **mixin.order.document.import** — orders created from uploaded documents

It extends ``account.move`` (adding order lines to an invoice, and the
invoice's incoterm location from its orders) and ``account.move.line``
(down-payment flag, order-line links carried on copy and into the analytic
distribution).
    """,
    "author": "Odoo Community",
    "website": "https://www.odoo.com",
    "license": "LGPL-3",
    "depends": [
        "trade",
        "account",
    ],
}
