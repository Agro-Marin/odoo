{
    "name": "IAP / Mail",
    "version": "1.0",
    "category": "Hidden/Tools",
    "summary": "Bridge between IAP and mail",
    "description": "Bridge between IAP and mail",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "iap",
        "mail",
    ],
    "data": [
        "data/mail_templates.xml",
        "views/iap_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "iap_mail/static/src/js/**/*",
            "iap_mail/static/src/scss/iap_mail.scss",
        ],
    },
    "installable": True,
    "auto_install": True,
}
