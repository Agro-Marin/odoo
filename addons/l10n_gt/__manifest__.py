{
    "name": "Guatemala - Accounting",
    "version": "3.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the base module to manage the accounting chart for Guatemala.
=====================================================================

Agrega una nomenclatura contable para Guatemala. También icluye impuestos y
la moneda del Quetzal. -- Adds accounting chart for Guatemala. It also includes
taxes and the Quetzal currency.""",
    "author": "Jos\u00e9 Rodrigo Fern\u00e1ndez Menegazzo",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "base",
        "account",
    ],
    "countries": [
        "gt",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
