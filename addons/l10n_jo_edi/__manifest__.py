{
    "name": "Jordan E-Invoicing",
    "version": "1.0",
    "category": "Accounting/Localizations/EDI",
    "summary": "Electronic Invoicing for Jordan UBL 2.1",
    "description": """
       Allows the users to integrate with JoFotara.
    """,
    "author": "Odoo S.A., Smart Way Business Solutions",
    "license": "LGPL-3",
    "depends": [
        "account_edi_ubl_cii",
        "l10n_jo",
    ],
    "countries": [
        "jo",
    ],
    "data": [
        "views/account_move_views.xml",
        "views/report_invoice.xml",
        "views/res_config_settings_views.xml",
    ],
    "demo": [
        "demo/demo_company.xml",
    ],
    "installable": True,
    "auto_install": [
        "l10n_jo",
    ],
    "post_init_hook": "_post_init_hook",
}
