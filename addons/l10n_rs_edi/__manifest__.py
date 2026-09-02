{
    "name": "Serbia - eFaktura E-invoicing",
    "version": "1.0",
    "category": "Accounting/Localizations/EDI",
    "summary": "E-Invoice implementation for Serbia",
    "description": """
eFaktura E-invoice implementation for Serbia
    """,
    "author": "Odoo",
    "license": "LGPL-3",
    "depends": [
        "account_edi_ubl_cii",
        "l10n_rs",
    ],
    "countries": [
        "rs",
    ],
    "data": [
        "views/res_config_settings_views.xml",
        "views/account_move.xml",
        "views/res_partner_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
