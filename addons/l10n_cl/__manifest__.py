{
    "name": "Chile - Accounting",
    "version": "3.1",
    "category": "Accounting/Localizations/Account Charts",
    "description": """
Chilean accounting chart and tax localization.
Plan contable chileno e impuestos de acuerdo a disposiciones vigentes.
    """,
    "author": "Blanco Mart\u00edn & Asociados",
    "website": "https://www.odoo.com/documentation/latest/applications/finance/fiscal_localizations/chile.html",
    "icon": "/account/static/description/l10n.png",
    "license": "LGPL-3",
    "depends": [
        "partner",
        "account_vat",
        "l10n_latam_base",
        "l10n_latam_invoice_document",
        "uom",
        "account",
    ],
    "countries": [
        "cl",
    ],
    "data": [
        "views/account_move_view.xml",
        "views/account_tax_view.xml",
        "views/res_bank_view.xml",
        "views/res_country_view.xml",
        "views/res_company_view.xml",
        "views/report_invoice.xml",
        "views/res_partner.xml",
        "views/res_config_settings_view.xml",
        "data/l10n_cl_chart_data.xml",
        "data/account_tax_report_data.xml",
        "data/account_tax_tags_data.xml",
        "data/l10n_latam_identification_type_data.xml",
        "data/l10n_latam.document.type.csv",
        "data/product_data.xml",
        "data/uom_data.xml",
        "data/res.currency.csv",
        "data/res_currency_data.xml",
        "data/res.bank.csv",
        "data/res.country.csv",
        "data/res_partner.xml",
    ],
    "demo": [
        "demo/partner_demo.xml",
        "demo/demo_company.xml",
    ],
    "auto_install": [
        "account",
    ],
}
