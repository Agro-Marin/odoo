{
    "name": "OdooBot",
    "version": "1.3",
    "category": "Productivity/Discuss",
    "summary": "Add OdooBot in discussions",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/app/discuss",
    "license": "LGPL-3",
    "depends": [
        "mail",
    ],
    "data": [
        "views/res_users_views.xml",
        "data/mailbot_data.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mail_bot/static/src/scss/odoobot_style.scss",
        ],
    },
    "installable": True,
    "auto_install": True,
}
