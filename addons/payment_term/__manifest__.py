{
    "name": "Payment Terms",
    "version": "1.0",
    "category": "Hidden",
    "summary": "When an agreed amount falls due, in instalments, with an early-payment discount",
    "description": """
Payment Terms
=============
The payment conditions a trade document agrees on: the instalments an amount
splits into, the date each one falls due, and the discount for paying early.
Orders show them, invoices schedule their receivables and payables by them,
payments apply their discounts, and a partner carries one for each direction.
    """,
    "author": "Odoo S.A., AgroMarin",
    "license": "LGPL-3",
    "depends": [
        "web",
    ],
    "data": [
        "security/ir.access.csv",
        "views/account_payment_term_views.xml",
        "data/account_payment_term_data.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "payment_term/static/src/scss/account_payment_term.scss",
            "payment_term/static/src/components/**/*",
        ],
    },
}
