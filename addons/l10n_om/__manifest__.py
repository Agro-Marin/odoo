{
    "name": "Oman - Accounting",
    "version": "1.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Oman Accounting Module
=================================================================
Oman accounting basic charts and localization.
Activates:
- Chart of Accounts
- Taxes
- VAT Return
- Fiscal Positions
- States
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
        "l10n_gcc_invoice",
    ],
    "countries": [
        "om",
    ],
    "data": [
        "data/res.country.state.csv",
        "data/tax_report.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": True,
}
