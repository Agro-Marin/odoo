{
    "name": "Honduras - Accounting",
    "version": "0.2",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Honduras.
====================================================================

Agrega una nomenclatura contable para Honduras. También incluye impuestos y la
moneda Lempira. -- Adds accounting chart for Honduras. It also includes taxes
and the Lempira currency.""",
    "author": "Salvatore Josue Trimarchi Pinto",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "base",
        "account",
    ],
    "countries": [
        "hn",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
