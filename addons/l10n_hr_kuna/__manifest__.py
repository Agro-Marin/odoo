{
    "name": "Croatia - Accounting (Kuna)",
    "version": "13.0",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Croatian localisation.
======================

Author: Goran Kliska, Slobodni programi d.o.o., Zagreb
        https://www.slobodni-programi.hr

Contributions:
  Tomislav Bošnjaković, Storm Computers: tipovi konta
  Ivan Vađić, Slobodni programi: tipovi konta

Description:

Croatian Chart of Accounts (RRIF ver.2012)

RRIF-ov računski plan za poduzetnike za 2012.
Vrste konta
Kontni plan prema RRIF-u, dorađen u smislu kraćenja naziva i dodavanja analitika
Porezne grupe prema poreznoj prijavi
Porezi PDV obrasca
Ostali porezi
Osnovne fiskalne pozicije

Izvori podataka:
 https://www.rrif.hr/dok/preuzimanje/rrif-rp2011.rar
 https://www.rrif.hr/dok/preuzimanje/rrif-rp2012.rar

""",
    "author": "OpenERP Croatian Community",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "countries": [
        "hr",
    ],
    "data": [
        "data/account_tax_report_data.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
}
