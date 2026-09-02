{
    "name": "France - Time Off",
    "version": "1.0",
    "category": "Human Resources/Time Off",
    "summary": "Management of leaves for part-time workers in France",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "hr_holidays",
    ],
    "countries": [
        "fr",
    ],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "demo": [
        "data/l10n_fr_hr_holidays_demo.xml",
    ],
    "auto_install": [
        "hr_holidays",
    ],
}
