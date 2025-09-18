{
    "name": "Base Account",
    "version": "1.0",
    "summary": "Chart of Accounts foundation",
    "description": """
Base Account
============
Provides the core Chart of Accounts structure: account types, codes,
tags, and multi-company code mappings.  Designed as a lightweight
foundation that heavier accounting modules (``account``, ``account_accountant``)
depend on.
    """,
    "category": "Accounting/Accounting",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/account_account_views.xml",
        "views/account_account_tag_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "author": "Odoo S.A., AgroMarin",
    "license": "LGPL-3",
}
