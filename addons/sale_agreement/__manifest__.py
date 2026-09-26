{
    "name": "Sales Agreements",
    "version": "19.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Blanket orders agreed with a customer",
    "description": """
Sales Agreements
================

A blanket order records what a customer agreed to buy over a period, at what
price: products, quantities and unit prices, from a start date to an end
date. Orders placed against it take its terms and its prices, and each line
of the agreement shows how much the confirmed orders have already taken.

The sales side of trade_agreement; purchase_requisition is its purchase side.
    """,
    "author": "Odoo Community",
    "website": "https://www.odoo.com",
    "license": "LGPL-3",
    "depends": [
        "sale",
        "trade_agreement",
    ],
    "data": [
        "security/ir.access.csv",
        "data/sale_agreement_data.xml",
        "views/sale_agreement_views.xml",
        "views/sale_order_views.xml",
        "views/sale_agreement_menus.xml",
    ],
}
