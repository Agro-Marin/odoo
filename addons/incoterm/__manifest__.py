{
    "name": "Incoterms",
    "version": "1.0",
    "category": "Hidden",
    "summary": "The ICC delivery terms a trade document agrees on",
    "description": """
Incoterms
=========
The ICC Incoterms: who carries the goods, the cost and the risk to which point.
Orders, pickings, invoices and electronic documents name one; none of them owns
the list.
    """,
    "author": "Odoo S.A., AgroMarin",
    "license": "LGPL-3",
    "depends": [
        "base",
    ],
    "data": [
        "security/ir.access.csv",
        "views/account_incoterms_views.xml",
        "data/account_incoterms_data.xml",
    ],
}
