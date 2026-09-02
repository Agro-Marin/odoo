{
    "name": "Croatia - Accounting (Euro)",
    "version": "13.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Croatian Chart of Accounts updated (RRIF ver.2021)

Sources:
https://www.rrif.hr/dok/preuzimanje/Bilanca-2016.pdf
https://www.rrif.hr/dok/preuzimanje/RRIF-RP2021.PDF
https://www.rrif.hr/dok/preuzimanje/RRIF-RP2021-ENG.PDF
    """,
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_vat",
    ],
    "countries": [
        "hr",
    ],
    "data": [
        "data/l10n_hr_chart_data.xml",
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
