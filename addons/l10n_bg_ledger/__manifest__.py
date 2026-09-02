{
    "name": "Bulgaria - Report ledger",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Report ledger for Bulgaria
    """,
    "author": "Odoo S.A.",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "l10n_bg",
    ],
    "countries": [
        "bg",
    ],
    "data": [
        "views/account_journal_views.xml",
        "views/account_move_views.xml",
    ],
    "auto_install": True,
}
