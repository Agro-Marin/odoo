{
    "name": "Latvia - Accounting",
    "version": "1.0.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Chart of Accounts (COA) Template for Latvia's Accounting.
This module also includes:
* Tax groups,
* Most common Latvian Taxes,
* Fiscal positions,
* Latvian bank list.

author is Allegro IT (visit for more information https://www.allegro.lv)
co-author is Chick.Farm (visit for more information https://www.myacc.cloud)
    """,
    "author": "Allegro IT, Chick.Farm",
    "website": "https://allegro.lv",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_vat",
        "account_edi_ubl_cii",
    ],
    "countries": [
        "lv",
    ],
    "data": [
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
