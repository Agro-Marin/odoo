{
    "name": "Italy - Accounting",
    "version": "0.8",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Piano dei conti italiano di un'impresa generica.
================================================

Italian accounting chart and localization.
    """,
    "author": "OpenERP Italian Community",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations/italy.html",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_iban",
        "account_vat",
        "account_edi_ubl_cii",
    ],
    "countries": [
        "it",
    ],
    "data": [
        "data/account_account_tag.xml",
        "data/tax_report/annual_report_sections/va.xml",
        "data/tax_report/annual_report_sections/ve.xml",
        "data/tax_report/annual_report_sections/vf.xml",
        "data/tax_report/annual_report_sections/vh.xml",
        "data/tax_report/annual_report_sections/vj.xml",
        "data/tax_report/annual_report_sections/vl.xml",
        "data/tax_report/account_annual_tax_report_data.xml",
        "data/tax_report/account_monthly_tax_report_data.xml",
        "data/tax_report/account_withholding_report_data.xml",
        "views/account_tax_views.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
