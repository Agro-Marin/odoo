{
    "name": "Add Partner GLN",
    "version": "1.0",
    "category": "Accounting/Accounting",
    "summary": "This module adds the Global Location Number to the partner. Used on delivery addresses, it is used to identify stock locations and is mandatory on the UBL/CII eInvoices (but not only). The module is intended be merged with account, later on, in master",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
    ],
    "data": [
        "views/res_partner_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
