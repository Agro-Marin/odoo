{
    "name": "Argentinean eCommerce",
    "version": "1.0",
    "category": "Accounting/Localizations/Website",
    "description": "Bridge Website Sale for Argentina",
    "author": "Odoo S.A.",
    "icon": "/base/static/img/country_flags/ar.png",
    "license": "LGPL-3",
    "depends": [
        "website_sale",
        "l10n_ar",
    ],
    "countries": [
        "ar",
    ],
    "data": [
        "views/res_config_settings_views.xml",
        "views/templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "l10n_ar_website_sale/static/src/interactions/**/*",
            "l10n_ar_website_sale/static/src/scss/*.scss",
        ],
    },
    "installable": True,
    "auto_install": True,
}
