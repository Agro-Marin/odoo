{
    "name": "Trade",
    "version": "19.0.3.7.0",
    "category": "Hidden",
    "summary": "The order kernel sale and purchase share: one trade, two directions",
    "description": """
Trade
=====

Provides abstract mixins that consolidate common patterns shared between
sale.order and purchase.order. The mixins are AbstractModel classes — no
tables, no views, no menus.

Mixins:
-------
* **mixin.order** — state machine, validation registry, workflow actions,
  mail/portal/catalog integration, duplicate detection
* **mixin.order.amount** — tax computation (order-level)
* **mixin.order.line.amount** — pricing and tax computation (line-level)
* **mixin.order.line.fields** — common structural fields, CRUD guards,
  transfer tracking
* **mixin.order.state.rollup** — gathers line states for an order-level rollup
* **mixin.order.merge** — quotation/RFQ merge system
* **mixin.order.report** — shared analytical-report layer over mixin.sql.report
* **mixin.order.mass.cancel** — cancel several orders from a list selection

It also carries the shared ``ir.actions.report`` extension that embeds an
order's EDI XML into its rendered PDF. Concrete modules only declare which of
their reports participate, via ``_get_order_edi_report_map``.

Two non-order models carry order-shaped helpers that both concrete modules
call, rather than each writing its own copy:

* **res.partner** — order counts, the application-statistics tile, and the
  order-activity figures (``recent_orders_count``, ``days_since_last_order``)
  measured against the company's order cycle
* **product.product** — the catalog "already on this order" flag (compute and
  search), and the order-line side of a unit-of-measure change

Invoicing is not here: ``trade_account`` adds it, so an order kernel installs
without a ledger.
    """,
    "author": "Odoo Community",
    "website": "https://www.odoo.com",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "portal",
        "product",
        "analytic",
        "tax",
        "payment_term",
        "mixin_report_sql",
    ],
    "data": [
        "security/ir.access.csv",
        "views/res_partner_tag_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "trade/static/src/components/**/*",
        ],
        "web.assets_unit_tests": [
            "trade/static/tests/**/*.test.js",
        ],
    },
}
