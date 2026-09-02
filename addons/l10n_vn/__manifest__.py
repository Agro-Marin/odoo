{
    "name": "Vietnam - Accounting",
    "version": "2.0.3",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
This is the module to manage the accounting chart, bank information for Vietnam in Odoo.
========================================================================================

- This module applies to companies based in Vietnamese Accounting Standard (VAS)
  with Chart of account under Circular No. 200/2014/TT-BTC
- Add Vietnamese bank information (like name, bic ..) as announced and yearly updated by State Bank
  of Viet Nam (https://sbv.gov.vn/webcenter/portal/en/home/sbv/paytreasury/bankidno).
- Add VietQR feature for invoice

**Credits:**
    - General Solutions.
    - Trobz
    - Jean Nguyen - The Bean Family (https://github.com/anhjean/vietqr) for VietQR.

""",
    "author": "General Solutions",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations/vietnam.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "account_qr_code_emv",
        "account_iban",
        "account",
    ],
    "countries": [
        "vn",
    ],
    "data": [
        "data/account_tax_report_data.xml",
        "views/account_move_views.xml",
        "views/res_bank_views.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
